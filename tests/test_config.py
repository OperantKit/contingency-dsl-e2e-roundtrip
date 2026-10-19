"""Location resolution is independent of where the package is checked out."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from contingency_dsl_e2e_roundtrip import agent_gen, cli, config, papers, procedures


def test_conformance_root_prefers_env(tmp_path, monkeypatch):
    monkeypatch.setenv(config.ENV_CONFORMANCE_ROOT, str(tmp_path))
    assert config.conformance_root() == tmp_path


def test_conformance_root_missing_raises(tmp_path, monkeypatch):
    monkeypatch.delenv(config.ENV_CONFORMANCE_ROOT, raising=False)
    monkeypatch.setattr(config, "_SOURCE_ROOT", tmp_path / "pkg")
    with pytest.raises(FileNotFoundError, match=config.ENV_CONFORMANCE_ROOT):
        config.conformance_root()


def test_conformance_root_uses_sibling_checkout(tmp_path, monkeypatch):
    monkeypatch.delenv(config.ENV_CONFORMANCE_ROOT, raising=False)
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "pyproject.toml").write_text("", encoding="utf-8")
    sibling = tmp_path / "contingency-dsl" / "conformance"
    sibling.mkdir(parents=True)
    monkeypatch.setattr(config, "_SOURCE_ROOT", pkg)
    assert config.conformance_root() == sibling


def test_discover_procedures_reads_env_root(tmp_path, monkeypatch):
    (tmp_path / "operant").mkdir()
    (tmp_path / "operant" / "atomic.json").write_text("[]", encoding="utf-8")
    monkeypatch.setenv(config.ENV_CONFORMANCE_ROOT, str(tmp_path))
    keys = [p.key for p in procedures.discover_procedures()]
    assert keys == ["operant/atomic"]


def test_paper_sources_disabled_without_env(monkeypatch):
    monkeypatch.delenv(config.ENV_PAPER_SOURCES_ROOT, raising=False)
    paper = papers.resolve("10.1002/jaba.226")
    assert (paper.note_path, paper.extracted_md_path, paper.pdf_path) == (None, None, None)
    assert papers.all_dois_with_any_asset() == []


def test_paper_sources_from_env(tmp_path, monkeypatch):
    pdf_dir = tmp_path / "reference" / "papers" / "pdf"
    pdf_dir.mkdir(parents=True)
    (pdf_dir / "10.1_x.pdf").write_bytes(b"%PDF")
    monkeypatch.setenv(config.ENV_PAPER_SOURCES_ROOT, str(tmp_path))
    assert papers.resolve("10.1/x").pdf_path == pdf_dir / "10.1_x.pdf"
    assert papers.all_dois_with_any_asset() == ["10.1/x"]


def test_cli_corpus_option_redirects_state(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "_corpus_root", config._corpus_root)
    corpus = tmp_path / "c"
    rc = cli.main(["--corpus", str(corpus), "report"])
    assert rc == 0
    assert config.state_path() == corpus.resolve() / "state.json"
    assert (corpus / "doi-lists" / "index.md").is_file()


def test_agent_written_inside_package(tmp_path, monkeypatch):
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "pyproject.toml").write_text("", encoding="utf-8")
    monkeypatch.setattr(config, "_SOURCE_ROOT", pkg)
    written = agent_gen.write_agent_markdown()
    assert written == pkg / ".claude" / "agents" / "procedure-classifier.md"
    assert written.read_text(encoding="utf-8").startswith("---\nname: procedure-classifier")
