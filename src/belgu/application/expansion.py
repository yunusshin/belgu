from __future__ import annotations

from dataclasses import dataclass

from belgu.domain.contracts import EntityRef, Limits


@dataclass(frozen=True)
class ExpansionSummary:
    status: str
    counts: dict[str, int]
    truncated: bool


class ExpansionRunner:
    def __init__(self, service, registry):
        self.service = service
        self.registry = registry

    def run(self, investigation_id: str, roots: list[EntityRef], limits: Limits) -> ExpansionSummary:
        queue = [(root, 0) for root in roots]
        seen: set[tuple[str, str]] = set()
        requests = 0
        discovered: set[tuple[str, str]] = set()
        while queue and requests < limits.max_requests and len(discovered) < limits.max_entities:
            entity, depth = queue.pop(0)
            key = (entity.kind, entity.value)
            if key in seen or depth > limits.max_depth:
                continue
            seen.add(key)
            providers = self.registry.providers_for(entity) if hasattr(self.registry, "providers_for") else self.registry
            for provider in providers:
                if requests >= limits.max_requests:
                    break
                result = provider.collect(entity)
                requests += 1
                self.service.record_result(investigation_id, result)
                for observation in result.observations:
                    candidate = (observation.subject.kind, observation.subject.value)
                    if candidate not in seen:
                        discovered.add(candidate)
                        queue.append((observation.subject, depth + 1))
        truncated = bool(queue)
        return ExpansionSummary("partial" if truncated else "completed", {"requests": requests, "new_entities": len(discovered)}, truncated)
