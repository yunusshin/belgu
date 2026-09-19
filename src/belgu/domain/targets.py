from __future__ import annotations

import ipaddress
from urllib.parse import SplitResult, urlsplit, urlunsplit

from belgu.domain.contracts import EntityKind, EntityRef, Target


def _idna(hostname: str) -> str:
    return hostname.rstrip(".").encode("idna").decode("ascii").lower()


def parse_target(raw: str) -> Target:
    value = raw.strip()
    if not value:
        raise ValueError("target cannot be empty")
    bare_ip = value[1:-1] if value.startswith("[") and value.endswith("]") else value
    try:
        parsed_ip = ipaddress.ip_address(bare_ip)
        return Target(raw, "ip", parsed_ip.compressed, None)
    except ValueError:
        pass

    if "://" not in value:
        if any(char in value for char in "/?#"):
            raise ValueError("URL must include http:// or https://")
        hostname = _idna(value)
        if "." not in hostname:
            raise ValueError("invalid domain")
        return Target(raw, "domain", hostname, hostname)

    parts = urlsplit(value)
    if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
        raise ValueError("only absolute HTTP(S) URLs are supported")
    hostname = _idna(parts.hostname)
    host = f"[{hostname}]" if ":" in hostname else hostname
    if parts.port is not None:
        host = f"{host}:{parts.port}"
    if parts.username is not None:
        auth = parts.username
        if parts.password is not None:
            auth += f":{parts.password}"
        host = f"{auth}@{host}"
    canonical = urlunsplit(SplitResult(parts.scheme.lower(), host, parts.path or "", parts.query, parts.fragment))
    return Target(raw, "url", canonical, hostname)


def canonicalize_entity(ref: EntityRef) -> EntityRef:
    if ref.kind in {"url", "domain", "ip"}:
        target = parse_target(ref.value)
        expected: EntityKind = ref.kind
        if target.kind != expected:
            raise ValueError(f"expected {expected}, got {target.kind}")
        return EntityRef(ref.kind, target.canonical_value)
    return EntityRef(ref.kind, ref.value.strip().lower())
