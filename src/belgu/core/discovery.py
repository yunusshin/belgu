"""Bounded breadth-first discovery with one independent result per upstream source."""
from __future__ import annotations

from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Callable
from urllib.parse import urlsplit

from belgu.domain.contracts import EntityRef, Limits, ProviderResult, RelationDraft
from belgu.domain.targets import parse_target
from belgu.core.network import SafeHttpClient
from belgu.core.providers.base import Budget, CollectionContext
from belgu.core.providers.dns import DnsProvider
from belgu.core.providers.crtsh import CrtshProvider
from belgu.core.providers.reverse_ip import ReverseIpProvider
from belgu.core.providers.urlscan import UrlscanProvider
from belgu.core.providers.page import PageProvider
from belgu.core.providers.favicon import FaviconProvider
from belgu.core.feeds.openphish import OpenPhishProvider
from belgu.core.feeds.local import LocalFeedProvider
from belgu.core.feeds.threatfox import ThreatFoxProvider
from belgu.integrations import defaults


@dataclass
class DiscoveryResult:
    results: list[ProviderResult]
    status: str
    counts: dict
    truncated: bool = False


def _trim(result, known, limit):
    """Trim complete evidence/relations together, retaining valid local indexes."""
    observations, relations, mapping = [], [], {}
    clipped = False

    def admit(entity):
        nonlocal clipped
        if entity in known:
            return True
        if len(known) >= limit:
            clipped = True
            return False
        known.add(entity)
        return True

    for index, evidence in enumerate(result.observations):
        if admit(evidence.subject):
            mapping[index] = len(observations)
            observations.append(evidence)
    for relation in result.relations:
        if all(index in mapping for index in relation.evidence_indexes) and admit(relation.src) and admit(relation.dst):
            relations.append(RelationDraft(relation.src, relation.dst, relation.kind,
                tuple(mapping[index] for index in relation.evidence_indexes)))
    return replace(result, observations=tuple(observations), relations=tuple(relations),
                   truncated=result.truncated or clipped,
                   status='partial' if clipped and result.status == 'ok' else result.status)


def discover(value: str, limits: Limits | None = None,
             cancelled: Callable[[], bool] | None = None,
             progress: Callable[[dict], None] | None = None,
             provider_settings: dict | None = None) -> DiscoveryResult:
    limits = limits or Limits()
    target = parse_target(value)
    seed = EntityRef(target.kind, target.canonical_value)
    budget = Budget(limits, cancelled)
    http = SafeHttpClient(budget)
    sources = provider_settings if provider_settings is not None else defaults()['sources']
    context = CollectionContext(http, budget, lambda: datetime.now(timezone.utc), sources)
    queue = deque([(seed, 0)])
    known = {seed}
    visited = set()
    results = []
    truncated = False
    is_cancelled = cancelled or (lambda: False)

    def announce(provider, message):
        if progress:
            progress({**budget.snapshot(), 'entities': len(known), 'provider': provider, 'message': message})

    try:
        with ThreadPoolExecutor(max_workers=max(1, min(limits.provider_concurrency, 4))) as pool:
            while queue and not budget.stopped():
                current, depth = queue.popleft()
                if current in visited or depth > limits.max_depth:
                    continue
                visited.add(current)
                if current.kind == 'url':
                    domain = EntityRef('domain', urlsplit(current.value).hostname)
                    if domain not in visited:
                        queue.appendleft((domain, depth))
                        if len(known) < limits.max_entities:
                            known.add(domain)
                    providers = [PageProvider()]
                elif current.kind == 'domain':
                    providers = [DnsProvider()]
                    if depth == 0:
                        providers += [CrtshProvider(), UrlscanProvider(), FaviconProvider()]
                        if seed.kind != 'url':
                            providers.append(PageProvider())
                        if sources['openphish']['enabled']:
                            providers.append(OpenPhishProvider())
                        providers.append(LocalFeedProvider('sgb'))
                        providers.append(LocalFeedProvider('threatfox') if sources['threatfox']['mode'] == 'local' else ThreatFoxProvider())
                    elif depth <= limits.max_depth:
                        providers.append(PageProvider())
                elif current.kind == 'ip':
                    # One-hop reverse expansion is useful even on shared hosting; the
                    # evidence states co-hosting, never a campaign classification.
                    providers = [DnsProvider(), ReverseIpProvider('mnemonic'), ReverseIpProvider('hackertarget')]
                    if depth == 0:
                        providers.append(UrlscanProvider())
                else:
                    continue
                providers = [provider for provider in providers
                             if sources.get(provider.name.removeprefix('reverse_ip.'), {}).get('enabled', True)]
                announce('', f'{current.value} araştırılıyor')
                futures = {pool.submit(provider.collect, current, context): provider.name for provider in providers}
                for future in as_completed(futures):
                    result = future.result()
                    before = set(known)
                    result = _trim(result, known, limits.max_entities)
                    results.append(result)
                    truncated |= result.truncated
                    for discovered in sorted(known - before, key=lambda item: (item.kind, item.value)):
                        if discovered.kind in ('domain', 'ip') and discovered not in visited:
                            queue.append((discovered, depth + 1))
                    announce(result.provider, f'{result.provider}: {len(result.observations)} gözlem · {result.status}')
                if budget.requests >= limits.max_requests or len(known) >= limits.max_entities:
                    truncated = True
                    break
            if queue and budget.stopped():
                truncated = True
    finally:
        http.close()
    has_errors = any(result.status in ('error', 'rate_limited', 'partial') for result in results)
    status = 'cancelled' if is_cancelled() else 'partial' if truncated or has_errors else 'completed'
    counts = {**budget.snapshot(), 'entities': len(known), 'new_entities': max(0, len(known) - 1),
              'observations': sum(len(r.observations) for r in results), 'providers': len(results)}
    announce('', 'Araştırma tamamlandı' if status == 'completed' else 'Araştırma sonuçları kaydedildi')
    return DiscoveryResult(results, status, counts, truncated)
