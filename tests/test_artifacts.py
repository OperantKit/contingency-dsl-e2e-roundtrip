"""Tests for corpus artifact persistence.

After a round-trip, the intermediate DSL (rendered as surface text),
compiled paper text, and re-extracted DSL must be written to
`corpus/generated/{dsl,compiled,dsl2}/` so they are auditable outside
`state.json`.
"""

from __future__ import annotations

import pytest

from contingency_dsl_e2e_roundtrip import artifacts
from contingency_dsl_e2e_roundtrip.roundtrip import RoundtripResult


@pytest.fixture
def tmp_generated(tmp_path, monkeypatch):
    root = tmp_path / "generated"
    monkeypatch.setattr(artifacts, "GENERATED_ROOT", root)
    monkeypatch.setattr(artifacts, "DSL_DIR", root / "dsl")
    monkeypatch.setattr(artifacts, "COMPILED_DIR", root / "compiled")
    monkeypatch.setattr(artifacts, "DSL2_DIR", root / "dsl2")
    return root


def _result(**overrides):
    base = dict(
        doi="10.1002/jaba.999",
        ok=True,
        a_ast_equiv=True,
        b_reparseable=True,
        c_text_similarity=0.5,
        d_notation_equiv=True,
        error=None,
        ast1={"type": "Atomic", "dist": "F", "domain": "R", "value": 5.0},
        ast2={"type": "Atomic", "dist": "F", "domain": "R", "value": 5.0},
        compiled_text="Pigeons were reinforced on FR 5 schedule.",
    )
    base.update(overrides)
    return RoundtripResult(**base)


def test_save_writes_three_artifacts(tmp_generated):
    paths = artifacts.save(_result())
    assert paths.dsl.exists()
    assert paths.compiled.exists()
    assert paths.dsl2.exists()
    assert paths.dsl.parent.name == "dsl"
    assert paths.compiled.parent.name == "compiled"
    assert paths.dsl2.parent.name == "dsl2"


def test_save_uses_doi_slug_and_dsl_extension(tmp_generated):
    paths = artifacts.save(_result(doi="10.1002/jaba.999"))
    assert paths.dsl.name == "10.1002_jaba.999.dsl"
    assert paths.compiled.name == "10.1002_jaba.999.txt"
    assert paths.dsl2.name == "10.1002_jaba.999.dsl"


def test_save_dsl_is_surface_text_not_json(tmp_generated):
    paths = artifacts.save(_result())
    content = paths.dsl.read_text(encoding="utf-8").strip()
    # Canonical DSL for an FR 5 Atomic is "FR5", not a JSON object.
    assert content == "FR5"


def test_save_compiled_text_roundtrips(tmp_generated):
    text = "Pigeons were reinforced on VI 60 s schedule.\n"
    paths = artifacts.save(_result(compiled_text=text))
    assert paths.compiled.read_text(encoding="utf-8") == text


def test_save_skips_missing_fields(tmp_generated):
    paths = artifacts.save(_result(ast1={"type": "Atomic", "dist": "F", "domain": "R", "value": 1.0},
                                   ast2=None, compiled_text=None))
    assert paths.dsl.exists()
    assert paths.compiled is None
    assert paths.dsl2 is None


def test_save_creates_dirs(tmp_generated):
    assert not tmp_generated.exists()
    artifacts.save(_result())
    assert (tmp_generated / "dsl").is_dir()
    assert (tmp_generated / "compiled").is_dir()
    assert (tmp_generated / "dsl2").is_dir()


def test_save_overwrites_existing(tmp_generated):
    artifacts.save(_result(ast1={"type": "Atomic", "dist": "F", "domain": "R", "value": 1.0}))
    paths = artifacts.save(_result(ast1={"type": "Atomic", "dist": "F", "domain": "R", "value": 9.0}))
    assert paths.dsl.read_text(encoding="utf-8").strip() == "FR9"


def test_render_dsl_fallback_on_unprintable_ast(tmp_generated):
    """AST that cannot be parsed into a Program still produces a file (no crash)."""
    paths = artifacts.save(_result(ast1={"type": "Atomic", "bogus": True}))
    content = paths.dsl.read_text(encoding="utf-8")
    assert content.startswith("# AST not printable as DSL")
    assert '"type": "Atomic"' in content  # JSON fallback included


def test_render_dsl_fallback_handles_non_json_serializable():
    """Non-serializable objects (e.g. set) fall through to repr(), not crash."""
    out = artifacts.render_dsl({"type": "Atomic", "extra": {1, 2, 3}})
    assert out.startswith("# AST not printable as DSL")
    assert "json.dumps failed" in out or "set" in out.lower()


def test_render_dsl_sanitizes_multiline_exc_message():
    """Exception messages with newlines don't break the comment line shape."""

    class MultilineExc(Exception):
        def __str__(self):
            return "line1\nline2"

    # Monkey-patch via direct call using a stub that raises MultilineExc.
    # The public contract: the first line is always a single '#'-prefixed comment.
    out = artifacts._sanitize_reason(MultilineExc())
    assert "\n" not in out
    assert "line1" in out and "line2" in out


def test_save_skips_missing_ast1(tmp_generated):
    """When AST_1 is None (extractor returned no AST), dsl/ is skipped cleanly."""
    result = RoundtripResult(
        doi="10.1002/jaba.xxx",
        ok=False,
        a_ast_equiv=False,
        b_reparseable=None,
        c_text_similarity=None,
        d_notation_equiv=False,
        error="reader(T) returned no AST",
        ast1=None,
        ast2=None,
        compiled_text=None,
    )
    paths = artifacts.save(result)
    assert paths.dsl is None
    assert paths.compiled is None
    assert paths.dsl2 is None


def test_save_is_atomic(tmp_generated, monkeypatch):
    """A crash during write leaves no partial file behind."""
    import os as real_os

    calls = {"n": 0}
    original_replace = real_os.replace

    def boom(*args, **kwargs):
        calls["n"] += 1
        raise OSError("simulated disk failure")

    monkeypatch.setattr(artifacts.os, "replace", boom)

    with pytest.raises(OSError):
        artifacts.save(_result())

    # No .dsl / .txt files, no orphaned .tmp files
    dsl_dir = tmp_generated / "dsl"
    if dsl_dir.exists():
        for entry in dsl_dir.iterdir():
            assert not entry.name.endswith(".dsl"), f"partial write: {entry}"
            assert not entry.name.endswith(".tmp"), f"orphaned tmp: {entry}"
