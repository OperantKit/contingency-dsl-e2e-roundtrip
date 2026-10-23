"""The codex-cli backend and `e2e second-rate`, with the subprocess stubbed."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from contingency_dsl_e2e_roundtrip import classify as classify_mod
from contingency_dsl_e2e_roundtrip import cli
from contingency_dsl_e2e_roundtrip import extract as extract_mod
from contingency_dsl_e2e_roundtrip import state as state_mod
from contingency_dsl_e2e_roundtrip.procedures import ProcedureType


KEYS = ["operant/atomic", "operant/compound"]
PROCS = [ProcedureType(key=k, source=Path("unused.json")) for k in KEYS]


def _fake_codex(calls: list[list[str]], reply: dict):
    def run(cmd, *, input, capture_output, text, timeout, cwd):  # noqa: A002
        calls.append(cmd)
        assert "Method section:" in input
        out = Path(cmd[cmd.index("-o") + 1])
        out.write_text(json.dumps(reply), encoding="utf-8")
        schema = json.loads(Path(cmd[cmd.index("--output-schema") + 1]).read_text())
        assert schema["properties"]["procedures"]["items"]["enum"] == KEYS
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
    return run


def test_codex_backend_runs_codex_exec_and_parses_output(monkeypatch):
    calls: list[list[str]] = []
    monkeypatch.setattr(classify_mod.shutil, "which", lambda name: "/bin/" + name)
    monkeypatch.setattr(classify_mod.subprocess, "run", _fake_codex(
        calls, {"procedures": ["operant/atomic", "bogus/key"], "out_of_scope_reason": None}
    ))
    monkeypatch.setenv("E2E_CLASSIFIER_BACKEND", "codex-cli")

    result = classify_mod.classify("10.1/a", "Method text", procedures=PROCS)

    assert result.procedures == ("operant/atomic",)
    assert result.model == classify_mod.DEFAULT_CODEX_MODEL
    cmd = calls[0]
    assert cmd[:2] == ["codex", "exec"]
    assert cmd[cmd.index("-m") + 1] == classify_mod.DEFAULT_CODEX_MODEL
    for flag in ("--skip-git-repo-check", "--ephemeral"):
        assert flag in cmd
    assert cmd[cmd.index("-s") + 1] == "read-only"
    assert cmd[-1] == "-"


def test_codex_backend_unavailable_without_binary(monkeypatch):
    monkeypatch.setattr(classify_mod.shutil, "which", lambda name: None)
    monkeypatch.setenv("E2E_CLASSIFIER_BACKEND", "codex-cli")
    with pytest.raises(classify_mod.ClassifierUnavailable):
        classify_mod.classify("10.1/a", "Method text", procedures=PROCS)


def test_second_rate_appends_rows_skips_done_and_leaves_state_alone(
    tmp_path, monkeypatch, capsys
):
    state_path = tmp_path / "state.json"
    original = json.dumps({"version": 1, "entries": {
        "10.1/a": {"procedures": ["operant/compound"], "classified_with": "haiku"},
    }})
    state_path.write_text(original, encoding="utf-8")
    monkeypatch.setattr(state_mod, "STATE_PATH", state_path)
    monkeypatch.setattr(extract_mod, "ensure_extracted",
                        lambda doi, force=False: (tmp_path / "x.txt", "Method text"))
    seen: list[str] = []

    def fake_classify(doi, text, *, model=None, procedures=None, backend=None):
        seen.append(doi)
        assert backend == "codex-cli"
        return classify_mod.ClassificationResult(
            doi=doi, procedures=("operant/atomic",), model=model or "m", raw="",
        )

    monkeypatch.setattr(classify_mod, "classify", fake_classify)
    dois = tmp_path / "dois.txt"
    dois.write_text("10.1/A\n\n10.1/b\n", encoding="utf-8")
    out = tmp_path / "second.jsonl"
    out.write_text(json.dumps({"doi": "10.1/b", "procedures": [],
                               "out_of_scope_reason": None, "model": "m",
                               "backend": "codex-cli"}) + "\n", encoding="utf-8")

    rc = cli.main(["second-rate", str(dois), "--out", str(out), "--model", "gpt-x"])

    assert rc == 0
    assert seen == ["10.1/a"]
    rows = [json.loads(line) for line in out.read_text().splitlines()]
    assert [r["doi"] for r in rows] == ["10.1/b", "10.1/a"]
    assert rows[1] == {"doi": "10.1/a", "procedures": ["operant/atomic"],
                       "out_of_scope_reason": None, "model": "gpt-x",
                       "backend": "codex-cli"}
    assert state_path.read_text(encoding="utf-8") == original
