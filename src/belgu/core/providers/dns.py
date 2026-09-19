"""DNS adapter, ported from the MIT-licensed discovery core's rdns.py."""
import dns.resolver
import dns.reversename
from belgu.domain.contracts import EntityRef
from belgu.core.providers.base import ResultBuilder, guarded, normalize_host


class DnsProvider:
    name = 'dns'

    @guarded
    def collect(self, target, context):
        result = ResultBuilder(self.name, context)
        resolver = dns.resolver.Resolver()
        query = str(dns.reversename.from_address(target.value)) if target.kind == 'ip' else target.value
        for kind in (('PTR',) if target.kind == 'ip' else ('A', 'AAAA')):
            if not context.budget.take_request():
                return result.result('partial', True, 'collection_limit')
            try:
                rows = resolver.resolve(query, kind, lifetime=min(5, max(.1, context.budget.remaining_seconds())))
            except dns.resolver.NoAnswer:
                continue
            except dns.resolver.NXDOMAIN:
                result.add(target, 'dns_nxdomain', f'dns:{target.value}', {'rcode': 'NXDOMAIN'}, context.now())
                continue
            for row in rows:
                value = str(row).rstrip('.')
                related = EntityRef('domain' if kind == 'PTR' else 'ip', value)
                if kind == 'PTR' and not normalize_host(value):
                    continue
                index = result.add(target, 'dns_' + kind.lower(), f'dns:{query}?type={kind}',
                    {'answer': value, **({'observed_ip': value} if kind != 'PTR' else {}),
                     'rrtype': kind, 'ttl': rows.rrset.ttl}, context.now())
                result.relate(target, related, 'ptr' if kind == 'PTR' else 'resolves_to', index)
        return result.result()
