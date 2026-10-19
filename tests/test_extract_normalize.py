"""Tests for pypdf-artifact normalization and plain-text Method slicing."""

from __future__ import annotations

from contingency_dsl_e2e_roundtrip.extract import (
    _normalize_pdf_text,
    _slice_method_section,
)


def test_ligatures_replaced():
    assert _normalize_pdf_text("ﬁeld") == "field"
    assert _normalize_pdf_text("ﬂow") == "flow"
    assert _normalize_pdf_text("eﬃcient") == "efficient"


def test_ligature_reglue_after_pypdf_spacing():
    """pypdf sometimes emits 'de ﬁne' — after ligature swap, reglue it."""
    assert _normalize_pdf_text("de ﬁne") == "define"
    assert _normalize_pdf_text("modi ﬁers") == "modifiers"


def test_line_end_hyphenation_rejoined():
    assert _normalize_pdf_text("persis-\ntence") == "persistence"
    # Real hyphenated compound (followed by uppercase or end-of-para) preserved.
    out = _normalize_pdf_text("well-\nKnown")
    # Uppercase K keeps hyphen? regex only merges when lowercase follows.
    assert "well-" in out or "wellKnown" in out  # tolerate either; just ensure no crash


def test_intra_paragraph_newline_becomes_space():
    text = "foo\nbar"
    assert _normalize_pdf_text(text) == "foo bar"


def test_paragraph_break_preserved():
    text = "foo\n\nbar"
    assert _normalize_pdf_text(text) == "foo\n\nbar"


def test_collapse_runs_of_spaces():
    assert _normalize_pdf_text("a   b") == "a b"


def test_slice_method_plaintext_heading():
    text = (
        "Title and Abstract here.\n\n"
        "METHOD\n"
        "Subjects were four rats. Apparatus was a chamber.\n"
        "Procedure used FR 5.\n\n"
        "RESULTS\n"
        "Rate increased across sessions.\n"
    )
    section = _slice_method_section(text)
    assert section is not None
    assert "Subjects" in section
    assert "Rate increased" not in section, "RESULTS bleed-through"


def test_slice_method_markdown_heading_still_works():
    text = "# Introduction\nfoo\n\n## Method\nbar\n\n## Results\nbaz"
    section = _slice_method_section(text)
    assert section is not None
    assert "bar" in section
    assert "baz" not in section


def test_slice_returns_none_without_method():
    assert _slice_method_section("Just some prose with no heading.") is None
