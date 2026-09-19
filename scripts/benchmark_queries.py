"""Measure actual case queries against generated local data; never contacts a provider."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import statistics
import tempfile
import time

from belgu.application.service import BelguService
from belgu.domain.contracts import EntityRef, EvidenceDraft, ProviderResult, RelationDraft


def percentile(values, fraction):
    return sorted(values)[max(0, int(len(values) * fraction + .999) - 1)]


def run_scale(domains, ips):
    with tempfile.TemporaryDirectory(prefix='belgu-scale-') as folder:
        service = BelguService.open('sqlite:///' + str(Path(folder) / 'data.db'))
        brand = service.create_brand('Ölçek doğrulaması', ['benchmark.test'])
        case = service.create_investigation(brand.id, f'{domains} alan adı / {ips} IP')
        now = datetime.now(timezone.utc)
        started = time.perf_counter()
        # Batches bound fixture creation memory. All observations are synthetic.
        for offset in range(0, domains, 500):
            observations, relations = [], []
            for i in range(offset, min(domains, offset + 500)):
                domain = EntityRef('domain', f'site-{i:05d}.test')
                ip = EntityRef('ip', '2001:db8::' + format(i % ips + 1, 'x'))
                index = len(observations)
                observations.append(EvidenceDraft(domain, 'dns_a', f'urn:benchmark:{i}', now, now,
                    {'observed_ip': ip.value, 'answer': ip.value, 'fictional': True}))
                relations.append(RelationDraft(domain, ip, 'resolves_to', (index,)))
            service.record_result(case.id, ProviderResult('benchmark_fixture', 'ok', tuple(observations), tuple(relations)))
        creation_ms = (time.perf_counter() - started) * 1000
        groups_ms, entities_ms = [], []
        for i in range(35):
            started = time.perf_counter()
            groups = service.list_groups(case.id, 'observed_ip', limit=50)
            middle = time.perf_counter()
            service.list_entities(case.id, kind='domain', limit=100)
            ended = time.perf_counter()
            if i >= 5:
                groups_ms.append((middle-started)*1000)
                entities_ms.append((ended-middle)*1000)
        cursor, seen = None, set()
        while True:
            page = service.list_entities(case.id, kind='domain', limit=100, cursor=cursor)
            ids = {row.id for row in page.items}
            assert not seen.intersection(ids), 'duplicate entity on later page'
            seen.update(ids)
            cursor = page.next_cursor
            if cursor is None:
                break
        assert len(seen) == domains, (len(seen), domains)
        assert groups.total_groups == ips, (groups.total_groups, ips)
        service.close()
        return {'domains': domains, 'ips': ips, 'fixture_creation_ms': round(creation_ms, 2),
                'groups_p50_ms': round(statistics.median(groups_ms), 2),
                'groups_p95_ms': round(percentile(groups_ms, .95), 2),
                'entities_p50_ms': round(statistics.median(entities_ms), 2),
                'entities_p95_ms': round(percentile(entities_ms, .95), 2),
                'reachable_unique_domains': len(seen), 'samples': 30, 'warmup': 5}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default='.local/validation/query-scale.json')
    args = parser.parse_args()
    results = [run_scale(1000, 100), run_scale(10000, 1000)]
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(results, indent=2))
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
