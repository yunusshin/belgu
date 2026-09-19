from __future__ import annotations
from hashlib import sha256
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

import httpcore

from belgu.domain.contracts import EntityRef
from belgu.core.providers.base import ResultBuilder, ensure_success, guarded
from belgu.core.network import FetchLimitExceeded
from belgu.domain.targets import parse_target


_CONNECT_FAILURES = (httpcore.ConnectError, httpcore.ConnectTimeout)
_TRANSPORT_FAILURES = (httpcore.NetworkError, httpcore.TimeoutException, httpcore.ProtocolError)


def _host_ref(url):
    hostname = urlsplit(url).hostname
    target = parse_target(hostname or '')
    return EntityRef(target.kind, target.canonical_value)


def _fallback_block_reason(context):
    budget = context.budget
    cancelled = budget.cancelled or bool(budget._cancel())
    if cancelled:
        return 'cancelled'
    if not budget.remaining_seconds() or budget.requests >= budget.limits.max_requests:
        return 'collection_limit'
    return None


def _record_attempt_failure(result, context, url, error):
    subject = EntityRef('url', url)
    index = result.add(subject, 'page_attempt_failed', url,
        {'url': url, 'failure': 'transport', 'error_type': type(error).__name__,
         'reason': str(error)[:500]}, context.now())
    result.relate(subject, _host_ref(url), 'url_host', index)


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title_parts, self.parts, self.scripts, self.forms = [], [], [], []
        self.credential_form = False
        self.favicon = None
        self._hidden, self._title = 0, False

    @property
    def title(self):
        return ' '.join(self.title_parts).strip()[:300]

    @property
    def text(self):
        return ' '.join(self.parts).strip()[:12000]

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ('script', 'style', 'noscript'):
            self._hidden += 1
        if tag == 'title':
            self._title = True
        if tag == 'script' and attrs.get('src'):
            self.scripts.append(attrs['src'])
        if tag == 'form':
            self.forms.append({'action': attrs.get('action', ''), 'method': attrs.get('method', 'get')})
        if tag == 'input' and attrs.get('type', '').lower() == 'password':
            self.credential_form = True
        if tag == 'link' and 'icon' in attrs.get('rel', ''):
            self.favicon = attrs.get('href')

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'noscript'):
            self._hidden = max(0, self._hidden - 1)
        if tag == 'title':
            self._title = False

    def handle_data(self, data):
        text = ' '.join(data.split())
        if text and not self._hidden:
            self.parts.append(text)
            if self._title:
                self.title_parts.append(text)


class PageProvider:
    name = 'page'

    @guarded
    def collect(self, target, context):
        result = ResultBuilder(self.name, context)
        bare_domain = target.kind == 'domain'
        url = target.value if target.kind == 'url' else 'https://' + target.value + '/'
        had_transport_failure = False
        try:
            response = context.http.get(url)
        except _CONNECT_FAILURES as error:
            had_transport_failure = True
            _record_attempt_failure(result, context, url, error)
            if not bare_domain:
                return result.result('error', error_code='page_' + type(error).__name__.lower())
            block_reason = _fallback_block_reason(context)
            if block_reason:
                return result.result('partial', truncated=True, error_code=block_reason)
            url = 'http://' + target.value + '/'
            try:
                response = context.http.get(url)
            except _TRANSPORT_FAILURES as fallback_error:
                _record_attempt_failure(result, context, url, fallback_error)
                return result.result('error', error_code='page_' + type(fallback_error).__name__.lower())
            except FetchLimitExceeded:
                return result.result('partial', truncated=True, error_code='collection_limit')

        parser = PageParser()
        content_type = response.headers.get('content-type', '')
        if 'html' in content_type or response.body.lstrip().startswith(b'<'):
            parser.feed(response.text)
        requested = EntityRef('url', url)
        final_target = parse_target(response.url)
        subject = EntityRef('url', final_target.canonical_value)
        index = result.add(subject, 'page_content', response.url,
            {'url': response.url, 'requested_url': url, 'final_url': response.url, 'title': parser.title,
             'text': parser.text, 'credential_form': parser.credential_form,
             'forms': parser.forms[:10], 'redirects': list(response.redirects),
             'status_code': response.status_code, 'content_type': content_type,
             'body_sha256': sha256(response.body).hexdigest(),
             'bytes': len(response.body)}, context.now())
        initial_host = _host_ref(url)
        host = _host_ref(response.url)
        result.relate(subject, host, 'url_host', index)
        if final_target.canonical_value != url:
            redirect_index = result.add(requested, 'redirect_chain', url,
                {'requested_url': url, 'final_url': response.url,
                 'hops': [*response.redirects, response.url]}, context.now())
            result.relate(requested, subject, 'redirects_to', redirect_index)
            result.relate(requested, initial_host, 'url_host', redirect_index)
        if response.cert_sha256:
            i = result.add(host, 'tls_certificate', response.url,
                           {'cert_sha256': response.cert_sha256}, context.now())
            result.relate(host, EntityRef('cert', response.cert_sha256), 'certificate', i)
        # Hash a small number of actual script bodies, not their names or URLs.
        scripts = parser.scripts if response.status_code < 400 else []
        for src in list(dict.fromkeys(scripts))[:2]:
            if context.budget.stopped():
                break
            script_url = urljoin(response.url, src)
            try:
                script = context.http.get(script_url)
                ensure_success(script)
                if not script.body:
                    continue
                digest = sha256(script.body).hexdigest()
                i = result.add(host, 'javascript_content', script.url,
                    {'js_sha256': digest, 'script_url': script.url, 'bytes': len(script.body)}, context.now())
                result.relate(host, EntityRef('js_hash', digest), 'loads_script', i)
            except Exception as exc:
                result.add(host, 'script_unavailable', script_url, {'reason': type(exc).__name__})
        from belgu.core.signals.kit import kit_signals
        signals = kit_signals(response.url, parser.title)
        if signals:
            result.add(subject, 'kit_indicators', response.url, {'signals': signals, 'rule_version': 'kit-indicators-v1'}, context.now())
        if response.status_code >= 400:
            return result.result('partial', error_code=f'upstream_http_{response.status_code}')
        if had_transport_failure:
            return result.result('partial', error_code='https_transport_failed')
        return result.result()
