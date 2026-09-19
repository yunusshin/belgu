"""Read-only ThreatFox Community API lookup; never submits an IOC."""
from urllib.parse import urlsplit

from belgu.core.providers.base import ResultBuilder, ensure_success, guarded, host_of, parse_time


class ThreatFoxProvider:
    name = 'threatfox'

    @guarded
    def collect(self, target, context):
        result = ResultBuilder(self.name, context)
        key = context.source(self.name)['api_key']
        if not key:
            return result.result('unavailable', error_code='api_key_required')
        host = host_of(target)
        response = context.http.post('https://threatfox-api.abuse.ch/api/v1/',
            json_body={'query': 'search_ioc', 'search_term': host, 'exact_match': False}, headers={'Auth-Key': key})
        ensure_success(response)
        data = response.json()
        status = data.get('query_status')
        if status == 'no_result':
            return result.result()
        if status != 'ok' or not isinstance(data.get('data'), list):
            return result.result('error', error_code='upstream_query_error')
        rows = data['data']
        for row in rows[:200]:
            if not isinstance(row, dict):
                continue
            value = str(row.get('ioc') or '')
            kind = row.get('ioc_type')
            candidate = urlsplit(value).hostname if kind == 'url' else value if kind == 'domain' else None
            if not candidate or candidate.lower().rstrip('.') != host.lower().rstrip('.'):
                continue
            source = 'https://threatfox.abuse.ch/ioc/' + str(row.get('id', '')) + '/'
            result.add(target, 'feed_report', source,
                {'reported_value': value, 'feed_report': True, 'category': row.get('threat_type'),
                 'source_name': self.name, 'ioc_type': kind, 'malware': row.get('malware_printable'),
                 'confidence_level': row.get('confidence_level')}, parse_time(row.get('first_seen')))
        return result.result('partial' if len(rows) > 200 else 'ok', len(rows) > 200)
