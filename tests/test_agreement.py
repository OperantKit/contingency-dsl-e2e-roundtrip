"""Inter-rater agreement between state.json and a second rater's JSONL."""

from __future__ import annotations

import json

import pytest

from contingency_dsl_e2e_roundtrip import agreement
from contingency_dsl_e2e_roundtrip import cli
from contingency_dsl_e2e_roundtrip import state as state_mod


KEYS = ["operant/atomic", "operant/compound", "experiment/phase"]


def _entries(procs_by_doi: dict[str, list[str]]) -> dict[str, dict]:
    return {
        doi: {"procedures": procs, "classified_with": "haiku"}
        for doi, procs in procs_by_doi.items()
    }


def _second(procs_by_doi: dict[str, list[str]]) -> list[dict]:
    return [
        {
            "doi": doi,
            "procedures": procs,
            "out_of_scope_reason": None,
            "model": "second-model",
            "backend": "codex-cli",
        }
        for doi, procs in procs_by_doi.items()
    ]


def _row(table: agreement.AgreementTable, key: str) -> agreement.KeyAgreement:
    return next(r for r in table.rows if r.key == key)


def test_kappa_2x2_balanced_table_is_zero():
    assert agreement.kappa_2x2(1, 1, 1, 1) == pytest.approx(0.0)


def test_kappa_2x2_is_undefined_when_both_raters_are_constant():
    assert agreement.kappa_2x2(0, 0, 0, 4) is None
    assert agreement.kappa_2x2(4, 0, 0, 0) is None


def test_perfect_agreement_gives_kappa_one():
    first = {
        "10.1/a": ["operant/atomic"],
        "10.1/b": ["operant/atomic", "operant/compound"],
        "10.1/c": [],
        "10.1/d": ["operant/compound"],
    }
    table = agreement.agreement_table(_entries(first), _second(first), KEYS)
    assert table.n == 4
    assert table.unmatched == 0
    assert _row(table, "operant/atomic").kappa == pytest.approx(1.0)
    assert _row(table, "operant/compound").kappa == pytest.approx(1.0)
    assert _row(table, "experiment/phase").kappa is None
    assert table.micro.kappa == pytest.approx(1.0)
    assert table.in_scope.kappa == pytest.approx(1.0)


def test_chance_level_agreement_gives_kappa_zero():
    first = {"10.1/a": ["operant/atomic"], "10.1/b": ["operant/atomic"],
             "10.1/c": [], "10.1/d": []}
    second = {"10.1/a": ["operant/atomic"], "10.1/b": [],
              "10.1/c": ["operant/atomic"], "10.1/d": []}
    table = agreement.agreement_table(_entries(first), _second(second), KEYS)
    row = _row(table, "operant/atomic")
    assert (row.both, row.only1, row.only2, row.neither) == (1, 1, 1, 1)
    assert row.kappa == pytest.approx(0.0)


def test_second_rater_assigning_nothing_gives_zero_or_undefined():
    first = {"10.1/a": ["operant/atomic"], "10.1/b": ["operant/atomic"],
             "10.1/c": ["operant/compound"], "10.1/d": []}
    second = {doi: [] for doi in first}
    table = agreement.agreement_table(_entries(first), _second(second), KEYS)
    atomic = _row(table, "operant/atomic")
    assert atomic.n1 == 2 and atomic.n2 == 0
    assert atomic.kappa == pytest.approx(0.0)
    assert _row(table, "operant/compound").kappa == pytest.approx(0.0)
    assert _row(table, "experiment/phase").kappa is None
    assert table.in_scope.kappa in (None, pytest.approx(0.0))
    assert table.micro.kappa == pytest.approx(0.0)


def test_cli_matches_case_insensitively_and_counts_unmatched(
    tmp_path, monkeypatch, capsys
):
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({"version": 1, "entries": _entries({
        "10.1/a": ["operant/atomic"],
        "10.1/b": [],
    })}), encoding="utf-8")
    monkeypatch.setattr(state_mod, "STATE_PATH", state_path)
    second_path = tmp_path / "second.jsonl"
    rows = _second({
        "10.1/A": ["operant/atomic"],
        "10.1/b": [],
        "10.9/not-in-state": ["operant/atomic"],
    })
    second_path.write_text(
        "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8"
    )

    rc = cli.main(["agreement", str(second_path), "--format", "json"])

    out = capsys.readouterr()
    assert rc == 0
    payload = json.loads(out.out)
    assert payload["n"] == 2
    assert payload["unmatched"] == 1
    assert "unmatched=1" in out.err
    atomic = next(r for r in payload["rows"] if r["key"] == "operant/atomic")
    assert atomic["kappa"] == pytest.approx(1.0)


def test_cli_returns_two_when_nothing_matches(tmp_path, monkeypatch, capsys):
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({"version": 1, "entries": {}}), encoding="utf-8")
    monkeypatch.setattr(state_mod, "STATE_PATH", state_path)
    second_path = tmp_path / "second.jsonl"
    second_path.write_text(json.dumps(_second({"10.1/a": []})[0]) + "\n",
                           encoding="utf-8")
    assert cli.main(["agreement", str(second_path)]) == 2


def test_markdown_output_has_header_rows_and_summary_lines():
    first = {"10.1/a": ["operant/atomic"], "10.1/b": []}
    table = agreement.agreement_table(_entries(first), _second(first), KEYS)
    md = agreement.format_md(table)
    assert md.splitlines()[0].startswith("N=2 unmatched=0 first=haiku:2 second=second-model")
    assert "| operant/atomic |" in md
    assert "| in-scope |" in md
    assert "| micro (3 keys) |" in md
    assert "| macro (defined keys) |" in md
