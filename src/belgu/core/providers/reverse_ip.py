"""Independent reverse-IP sources; a co-host is a candidate, never an actor attribution."""
from belgu.domain.contracts import EntityRef
from belgu.core.providers.base import ResultBuilder, ensure_success, guarded, normalize_host, parse_time


class ReverseIpProvider:
    def __init__(self, source='mnemonic'):
        self.source = source
        self.name = 'reverse_ip.' + source

    @guarded
    def collect(self, target, context):
        result = ResultBuilder(self.name, context)
        if self.source == 'mnemonic':
            url = 'https://api.mnemonic.no/pdns/v3/' + target.value
            key = context.source('mnemonic')['api_key']
            response = context.http.get(url, params={'limit': 200}, headers={'Argus-API-Key': key} if key else {})
            ensure_success(response)
            records = [(row.get('query'), parse_time(row.get('lastSeenTimestamp')))
                for row in response.json().get('data', [])
                if str(row.get('rrtype', '')).lower() in ('a', 'aaaa') and row.get('answer') == target.value]
        else:
            url = 'https://api.hackertarget.com/reverseiplookup/'
            key = context.source('hackertarget')['api_key']
            response = context.http.get(url, params={'q': target.value}, headers={'X-API-Key': key} if key else {})
            ensure_success(response)
            low = response.text.lower()
            if 'api count exceeded' in low or 'rate limit' in low:
                return result.result('rate_limited', error_code='upstream_rate_limited')
            if 'error' in low and 'no dns' not in low:
                return result.result('error', error_code='upstream_query_error')
            records = [(line, None) for line in response.text.splitlines()]
        seen = set()
        for value, observed_at in records:
            host = normalize_host(value)
            if not host or host in seen:
                continue
            seen.add(host)
            domain = EntityRef('domain', host)
            index = result.add(domain, 'passive_dns', response.url,
                {'answer': target.value, 'observed_ip': target.value, 'domain': host,
                 'relationship': 'shared_hosting_candidate'}, observed_at)
            result.relate(domain, target, 'observed_on', index)
            if len(seen) >= 200:
                return result.result('partial', True)
        return result.result()
