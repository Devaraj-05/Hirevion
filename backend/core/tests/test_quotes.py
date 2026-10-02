"""Quotes the AI gives as evidence must really be in the document (master plan §3.2(3))."""

from hirevion_core.documents.quotes import verified

TEXT = "We need 5+ years of Python\nand strong “system design” skills — Kubernetes a plus."


def test_a_quote_found_in_the_text_is_verified() -> None:
    assert verified("5+ years of Python", TEXT)
    assert verified("python and strong", TEXT)  # case and line breaks don't matter
    assert verified('strong "system design" skills - Kubernetes', TEXT)  # nor quote/dash styles


def test_a_made_up_or_empty_quote_is_not() -> None:
    assert not verified("10 years of Rust", TEXT)
    assert not verified("", TEXT)
    assert not verified("   ", TEXT)
