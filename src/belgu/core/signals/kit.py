"""URL/title indicators adapted from the MIT-licensed kitsig module.

These explain similarities; they do not identify an attacker or prove phishing.
"""
from urllib.parse import parse_qs, urlsplit

KIT_URL_SCHEMAS = (frozenset({'sg', 'mc', 'ts', 'src', 'ct'}),
                   frozenset({'email_from_url', 'eid', 'mid', 'campaign'}))
KIT_GATE_MARKERS = ('quick verification', 'confirm access', 'security check',
                    'checking your browser', 'verifying you are human')


def kit_signals(url: str, title: str | None) -> list[str]:
    params = frozenset(parse_qs(urlsplit(url).query, keep_blank_values=True))
    result = []
    if not params & {'w55c', 'dxver'} and any(len(params & schema) >= 3 for schema in KIT_URL_SCHEMAS):
        result.append('known_parameter_schema')
    if any(marker in (title or '').lower() for marker in KIT_GATE_MARKERS):
        result.append('verification_gate_copy')
    return result
