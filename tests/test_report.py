from pathlib import Path

from contingency_dsl_e2e_roundtrip.procedures import ProcedureType
from contingency_dsl_e2e_roundtrip.report import render


def test_render_writes_per_procedure_files(tmp_path: Path):
    procs = [
        ProcedureType(key="operant/atomic", source=tmp_path / "atomic.json"),
        ProcedureType(key="operant/stateful/adjusting", source=tmp_path / "adj.json"),
    ]
    state = {
        "version": 1,
        "entries": {
            "10.1/x": {
                "procedures": ["operant/atomic"],
                "roundtrip": {
                    "ok": True,
                    "a_ast_equiv": True,
                    "b_reparseable": True,
                    "c_text_similarity": 0.9,
                    "d_notation_equiv": True,
                },
            },
            "10.2/y": {
                "procedures": ["operant/atomic"],
                "roundtrip": None,
            },
        },
    }
    written = render(state, procedures=procs, out_dir=tmp_path)
    names = {p.name for p in written}
    assert "operant__atomic.md" in names
    assert "operant__stateful__adjusting.md" in names
    assert "index.md" in names

    atomic = (tmp_path / "operant__atomic.md").read_text()
    assert "- [x] `10.1/x`" in atomic
    assert "- [ ] `10.2/y`" in atomic

    empty = (tmp_path / "operant__stateful__adjusting.md").read_text()
    assert "no papers classified" in empty


def test_render_excludes_out_of_scope_from_tally(tmp_path: Path):
    procs = [ProcedureType(key="operant/atomic", source=tmp_path / "atomic.json")]
    state = {
        "version": 1,
        "entries": {
            "10.1/in-scope-pass": {
                "procedures": ["operant/atomic"],
                "roundtrip": {"ok": True, "a_ast_equiv": True, "b_reparseable": True},
            },
            "10.2/in-scope-fail": {
                "procedures": ["operant/atomic"],
                "roundtrip": {"ok": False, "a_ast_equiv": False},
            },
            "10.3/meta-analysis": {
                "procedures": ["operant/atomic"],
                "out_of_scope_reason": "meta-analysis: model fitting on prior data",
                "roundtrip": None,
            },
        },
    }
    render(state, procedures=procs, out_dir=tmp_path)
    atomic = (tmp_path / "operant__atomic.md").read_text()

    # Out-of-scope DOI must not contribute to the in-scope tally.
    assert "Total papers classified: **2**" in atomic
    assert "Passing: **1**" in atomic

    # It must still surface so the human can see why it was excluded.
    assert "10.3/meta-analysis" in atomic
    assert "out of scope" in atomic.lower()
    assert "model fitting" in atomic

    # Index aggregates the same way.
    index = (tmp_path / "index.md").read_text()
    assert "1/2 passing" in index
    assert "out of scope" in index.lower()


def test_render_index_counts_out_of_scope_total(tmp_path: Path):
    procs = [ProcedureType(key="operant/atomic", source=tmp_path / "atomic.json")]
    state = {
        "version": 1,
        "entries": {
            "10.1/x": {"procedures": ["operant/atomic"], "roundtrip": None},
            "10.2/y": {
                "procedures": ["operant/atomic"],
                "out_of_scope_reason": "human questionnaire",
                "roundtrip": None,
            },
        },
    }
    render(state, procedures=procs, out_dir=tmp_path)
    index = (tmp_path / "index.md").read_text()
    # Top-level total still counts every classified DOI; out-of-scope tally is separate.
    assert "Total classified DOIs: **2**" in index
    assert "Out of scope: **1**" in index
