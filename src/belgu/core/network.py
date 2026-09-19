"""Small bounded HTTP reader used only by discovery providers."""
from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import json
import time
from urllib.parse import urlencode, urljoin, urlsplit, urlunsplit
import zlib

import dns.resolver
import httpcore


class NetworkPolicyError(ValueError):
    pass


class FetchLimitExceeded(RuntimeError):
    pass


def require_public_ip(value: str) -> str:
    address = ipaddress.ip_address(value)
    if getattr(address, 'ipv4_mapped', None):
        address = address.ipv4_mapped
    if not address.is_global or address.is_multicast:
        raise NetworkPolicyError('Yalnız genel internet adresleri sorgulanabilir.')
    return str(address)


def resolve_public(host: str) -> list[str]:
    try:
        return [require_public_ip(host)]
    except ValueError as exc:
        if isinstance(exc, NetworkPolicyError):
            raise
    addresses = []
    resolver = dns.resolver.Resolver()
    for kind in ('A', 'AAAA'):
        try:
            addresses.extend(str(item) for item in resolver.resolve(host, kind, lifetime=4))
        except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN):
            continue
        except dns.exception.DNSException:
            if not addresses:
                raise
    if not addresses:
        raise NetworkPolicyError('Alan adı çözümlenemedi.')
    return list(dict.fromkeys(require_public_ip(a) for a in addresses))


class PublicNetworkBackend(httpcore.NetworkBackend):
    def __init__(self):
        self.backend = httpcore.SyncBackend()

    def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        hostname = host.decode() if isinstance(host, bytes) else host
        addresses = resolve_public(hostname)
        # HTTP core keeps original Host/SNI; the socket receives the validated IP.
        error = None
        for address in addresses:
            try:
                return self.backend.connect_tcp(address, port, timeout=timeout,
                    local_address=local_address, socket_options=socket_options)
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                error = exc
        raise error or NetworkPolicyError('Bağlantı kurulamadı.')

    def connect_unix_socket(self, *args, **kwargs):
        raise NetworkPolicyError('Yerel soket kullanılamaz.')


@dataclass(frozen=True)
class FetchResult:
    url: str
    status_code: int
    headers: dict[str, str]
    body: bytes
    redirects: tuple[str, ...]
    cert_sha256: str | None = None

    @property
    def text(self):
        return self.body.decode('utf-8', errors='replace')

    def json(self):
        return json.loads(self.body)


class SafeHttpClient:
    def __init__(self, budget=None, max_bytes=2 * 1024 * 1024):
        self.budget = budget
        self.max_bytes = max_bytes
        self.pool = httpcore.ConnectionPool(network_backend=PublicNetworkBackend(),
            max_connections=4, max_keepalive_connections=2)

    def close(self):
        self.pool.close()

    def get(self, url, params=None, headers=None):
        return self._request('GET', url, params=params, headers=headers)

    def post(self, url, json_body, headers=None):
        return self._request('POST', url, headers={'Content-Type': 'application/json', **(headers or {})},
                             content=json.dumps(json_body).encode('utf-8'))

    def _request(self, method, url, params=None, headers=None, content=None):
        import hashlib
        if params:
            parts = urlsplit(url)
            query = '&'.join(filter(None, (parts.query, urlencode(params))))
            url = urlunsplit(parts._replace(query=query))
        redirects = []
        started = time.monotonic()
        request_headers = {'User-Agent': 'Belgu/0.1 (analyst research)',
                           'Accept-Encoding': 'identity', **(headers or {})}
        for _ in range(6):
            parts = urlsplit(url)
            if parts.scheme not in ('https', 'http') or not parts.hostname or parts.username:
                raise NetworkPolicyError('HTTP veya HTTPS adresi gerekli.')
            if self.budget and not self.budget.take_request():
                raise FetchLimitExceeded('Araştırma bütçesi doldu.')
            remaining = 15 - (time.monotonic() - started)
            if self.budget:
                remaining = min(remaining, self.budget.remaining_seconds())
            if remaining <= 0:
                raise FetchLimitExceeded('İstek süresi doldu.')
            with self.pool.stream(method, url, headers=request_headers, **({'content': content} if content is not None else {}),
                extensions={'timeout': {'connect': min(5, remaining), 'read': remaining,
                                         'write': remaining, 'pool': remaining}}) as response:
                h = {key.decode().lower(): val.decode('latin1') for key, val in response.headers}
                if response.status in (301, 302, 303, 307, 308) and h.get('location'):
                    if method != 'GET':
                        raise NetworkPolicyError('API isteği yönlendirmesi desteklenmiyor.')
                    redirects.append(url)
                    url = urljoin(url, h['location'])
                    # Never forward provider keys to a different redirected origin.
                    if (urlsplit(url).scheme, urlsplit(url).netloc) != (parts.scheme, parts.netloc):
                        request_headers = {k: v for k, v in request_headers.items()
                                           if k.lower() not in ('api-key', 'auth-key', 'authorization', 'x-api-key', 'argus-api-key')}
                    continue
                data = bytearray()
                for chunk in response.iter_stream():
                    data.extend(chunk)
                    if len(data) > self.max_bytes or time.monotonic() - started > 15:
                        raise FetchLimitExceeded('Yanıt boyutu veya istek süresi aşıldı.')
                body = bytes(data)
                encoding = h.get('content-encoding', '').lower()
                if encoding in ('gzip', 'deflate'):
                    decoder = zlib.decompressobj(16 + zlib.MAX_WBITS if encoding == 'gzip' else zlib.MAX_WBITS)
                    body = decoder.decompress(body, self.max_bytes + 1)
                    if len(body) > self.max_bytes or decoder.unconsumed_tail or not decoder.eof:
                        raise FetchLimitExceeded('Açılmış içerik sınırı aşıldı.')
                certificate = None
                stream = response.extensions.get('network_stream')
                if stream:
                    ssl_object = stream.get_extra_info('ssl_object')
                    if ssl_object:
                        der = ssl_object.getpeercert(True)
                        certificate = hashlib.sha256(der).hexdigest() if der else None
                return FetchResult(url, response.status, h, body, tuple(redirects), certificate)
        raise FetchLimitExceeded('Yönlendirme sınırı aşıldı.')
