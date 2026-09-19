"""Read existing public scan metadata; never submit an analyst's URL."""
import ipaddress
from belgu.domain.contracts import EntityRef
from belgu.core.providers.base import ResultBuilder, ensure_success, guarded, normalize_host, parse_time
from belgu.domain.targets import parse_target


_LUCENE_RESERVED = set('+-=&|><!(){}[]^"~*?:\\/')


def _quoted_query(field, value):
    escaped = ''.join('\\' + character if character in _LUCENE_RESERVED else character
                      for character in value)
    return f'{field}:"{escaped}"'


def _canonical_ip(value):
    try:
        return ipaddress.ip_address(str(value)).compressed
    except ValueError:
        return None


class UrlscanProvider:
    name = 'urlscan'

    @guarded
    def collect(self, target, context):
        key = context.source('urlscan')['api_key']
        headers = {'API-Key': key} if key else {}
        if target.kind == 'ip':
            expected_ip = _canonical_ip(target.value)
            if not expected_ip:
                raise ValueError('invalid IP target')
            expected_host = None
            query = _quoted_query('page.ip', expected_ip)
        else:
            expected_host = normalize_host(target.value)
            if not expected_host:
                raise ValueError('invalid domain target')
            expected_ip = None
            query = _quoted_query('page.domain.keyword', expected_host)
        response = context.http.get('https://urlscan.io/api/v1/search/',
            params={'q': query, 'size': 100}, headers=headers)
        ensure_success(response)
        data = response.json()
        result = ResultBuilder(self.name, context)
        for row in data.get('results', []):
            page, task = row.get('page') or {}, row.get('task') or {}
            host = normalize_host(page.get('domain'))
            if not host:
                continue
            primary_ip = _canonical_ip(page.get('ip'))
            if expected_host is not None and host != expected_host:
                continue
            if expected_ip is not None and primary_ip != expected_ip:
                continue
            scan_id = str(row.get('_id') or '').strip()
            if not scan_id:
                continue
            domain = EntityRef('domain', host)
            ref = 'https://urlscan.io/result/' + scan_id + '/'
            index = result.add(domain, 'existing_scan', ref,
                {'url': page.get('url'), 'title': page.get('title'), 'answer': primary_ip,
                 'observed_ip': primary_ip,
                 'country': page.get('country'), 'asn': page.get('asn'),
                 'scan_id': scan_id, 'scan_source': task.get('source')}, parse_time(task.get('time')))
            if primary_ip:
                result.relate(domain, EntityRef('ip', primary_ip), 'observed_on', index)
            if page.get('url'):
                try:
                    page_target = parse_target(page['url'])
                except (TypeError, ValueError):
                    page_target = None
                if page_target and page_target.kind == 'url' and page_target.hostname == host:
                    result.relate(EntityRef('url', page_target.canonical_value), domain, 'url_host', index)
        has_more = bool(data.get('has_more'))
        return result.result('partial' if has_more else 'ok', has_more)
