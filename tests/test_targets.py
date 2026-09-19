import pytest

from belgu.domain.targets import parse_target


def test_full_url_and_query_are_preserved():
    raw = "https://ORNEK.test/Giris?ref=A%2Fb&x=1"
    target = parse_target(raw)
    assert target.raw_value == raw
    assert target.canonical_value == "https://ornek.test/Giris?ref=A%2Fb&x=1"
    assert target.hostname == "ornek.test"
    assert target.kind == "url"


@pytest.mark.parametrize(
    ("raw", "kind", "canonical"),
    [
        ("203.0.113.7", "ip", "203.0.113.7"),
        ("[2001:db8::1]", "ip", "2001:db8::1"),
        ("Banka.TEST.", "domain", "banka.test"),
        ("https://bücher.test/a", "url", "https://xn--bcher-kva.test/a"),
    ],
)
def test_target_normalization(raw, kind, canonical):
    target = parse_target(raw)
    assert (target.kind, target.canonical_value) == (kind, canonical)


def test_empty_target_is_rejected():
    with pytest.raises(ValueError):
        parse_target("  ")
