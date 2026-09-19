from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from functools import wraps
from threading import Lock
import time
from typing import Callable
from urllib.parse import urlsplit

from belgu.domain.contracts import EvidenceDraft, EntityRef, Limits, ProviderResult, RelationDraft
from belgu.core.network import FetchLimitExceeded, SafeHttpClient


class Budget:
    def __init__(self, limits: Limits, cancelled=None):
        self.limits = limits
        self.started = time.monotonic()
        self.requests = 0
        self.cancelled = False
        self._cancel = cancelled or (lambda: False)
        self.lock = Lock()

    def remaining_seconds(self):
        return max(0, self.limits.max_seconds - (time.monotonic() - self.started))

    def stopped(self):
        return self.cancelled or self._cancel() or not self.remaining_seconds()

    def take_request(self):
        with self.lock:
            if self.stopped() or self.requests >= self.limits.max_requests:
                return False
            self.requests += 1
            return True

    def snapshot(self):
        return {'requests': self.requests,
                'remaining_requests': max(0, self.limits.max_requests - self.requests),
                'elapsed_seconds': int(time.monotonic() - self.started)}


@dataclass
class CollectionContext:
    http: SafeHttpClient
    budget: Budget
    now: Callable[[], datetime]
    provider_settings: dict | None = None

    def source(self, name):
        if self.provider_settings is None:
            from belgu.integrations import defaults
            return defaults()['sources'][name]
        return self.provider_settings[name]


def parse_time(value):
    if not value:
        return None
    try:
        if isinstance(value, (float, int)):
            return datetime.fromtimestamp(value / 1000 if value > 100000000000 else value, timezone.utc)
        parsed = datetime.fromisoformat(str(value).replace(' UTC', '+00:00').replace('Z', '+00:00'))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (ValueError, OverflowError, TypeError):
        return None


def normalize_host(value):
    value = str(value or '').strip().removeprefix('*.').rstrip('.').lower()
    if not value or '@' in value or '/' in value or ' ' in value or '.' not in value:
        return None
    try:
        host = value.encode('idna').decode('ascii')
    except UnicodeError:
        return None
    return host if len(host) <= 253 else None


def host_of(target):
    return urlsplit(target.value).hostname if target.kind == 'url' else target.value


class UpstreamError(RuntimeError):
    def __init__(self, status, code):
        self.status, self.code = status, code
        super().__init__(code)


def ensure_success(response):
    if response.status_code == 429:
        raise UpstreamError('rate_limited', 'upstream_rate_limited')
    if response.status_code in (401, 403):
        raise UpstreamError('unavailable', 'upstream_access_denied')
    if response.status_code >= 400:
        raise UpstreamError('error', f'upstream_http_{response.status_code}')


def guarded(fn):
    @wraps(fn)
    def wrapped(self, target, context):
        try:
            return fn(self, target, context)
        except UpstreamError as exc:
            return ProviderResult(self.name, exc.status, error_code=exc.code)
        except FetchLimitExceeded:
            return ProviderResult(self.name, 'partial', truncated=True, error_code='collection_limit')
        except Exception as exc:
            return ProviderResult(self.name, 'error', error_code=type(exc).__name__)
    return wrapped


class ResultBuilder:
    def __init__(self, provider, context):
        self.provider, self.context = provider, context
        self.observations, self.relations = [], []

    def add(self, subject, kind, source_ref, payload, observed_at=None):
        self.observations.append(EvidenceDraft(subject, kind, source_ref, observed_at,
                                              self.context.now(), payload))
        return len(self.observations) - 1

    def relate(self, src, dst, kind, index):
        self.relations.append(RelationDraft(src, dst, kind, (index,)))

    def result(self, status='ok', truncated=False, error_code=None):
        return ProviderResult(self.provider, status, tuple(self.observations),
                              tuple(self.relations), truncated, error_code)
