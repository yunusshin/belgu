"""Certificate transparency name relationships with certificate identity retained."""
from belgu.domain.contracts import EntityRef
from belgu.core.providers.base import ResultBuilder, ensure_success, guarded, normalize_host, parse_time


class CrtshProvider:
    name = 'crtsh'

    @guarded
    def collect(self, target, context):
        response = context.http.get('https://crt.sh/', params={'q': target.value, 'output': 'json'})
        ensure_success(response)
        result = ResultBuilder(self.name, context)
        rows = response.json()
        seen = set()
        for row in rows[:200]:
            names = {normalize_host(name) for name in str(row.get('name_value', '')).splitlines()}
            names.discard(None)
            for host in names:
                key = (host, row.get('id'))
                if key in seen:
                    continue
                seen.add(key)
                subject = EntityRef('domain', host)
                index = result.add(subject, 'certificate_transparency',
                    f"https://crt.sh/?id={row.get('id', '')}",
                    {'certificate_id': row.get('id'), 'issuer': row.get('issuer_name'),
                     'names': sorted(names), 'not_before': row.get('not_before'), 'not_after': row.get('not_after')},
                    parse_time(row.get('entry_timestamp')))
                # A query hit alone is not a shared-certificate edge.
                if host != target.value and target.value in names:
                    result.relate(target, subject, 'certificate_names', index)
        return result.result('partial' if len(rows) > 200 else 'ok', len(rows) > 200)
