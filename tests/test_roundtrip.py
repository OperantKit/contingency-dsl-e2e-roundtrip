from contingency_dsl_e2e_roundtrip.roundtrip import (
    _normalize_ast,
    _wrap_for_compile,
    canonical_json,
    jaccard,
    run,
)


def test_normalize_ast_drops_none_and_sorts():
    a = {"b": 1, "a": None, "c": [{"y": None, "x": 2}]}
    b = {"c": [{"x": 2}], "b": 1}
    assert _normalize_ast(a) == _normalize_ast(b)


def test_canonical_json_stable():
    a = {"b": 1, "a": 2}
    b = {"a": 2, "b": 1}
    assert canonical_json(a) == canonical_json(b)


def test_jaccard_bounds():
    assert jaccard("", "") == 1.0
    assert jaccard("foo", "") == 0.0
    assert 0.0 < jaccard("alpha beta", "beta gamma") < 1.0


def test_wrap_for_compile_wraps_atomic():
    atomic = {"type": "Atomic", "dist": "F", "domain": "I", "value": 30.0}
    wrapped = _wrap_for_compile(atomic)
    assert wrapped["type"] == "Program"
    assert wrapped["schedule"] is atomic


def test_wrap_for_compile_passes_program_through():
    program = {"type": "Program", "schedule": {"type": "Atomic"}}
    assert _wrap_for_compile(program) is program


def test_wrap_for_compile_passes_experiment_through():
    experiment = {"type": "Experiment", "body": {"type": "Program"}}
    assert _wrap_for_compile(experiment) is experiment


def test_run_end_to_end_atomic_roundtrips(monkeypatch):
    """Full reader→paper→reader pipeline on a canonical FI 30 s input.

    Regression guard: prior to wrapping the reader's bare Atomic AST in a
    Program node, compile_method returned an empty procedure and ast2 came
    back None. This test pins the wrap behaviour end-to-end using the real
    reader and paper packages.
    """
    result = run("test/fi-30", "Pigeons were reinforced on FI 30 s schedule.")
    assert result.error is None
    assert result.compiled_text
    assert result.b_reparseable is True
    assert result.ok is True, (
        f"expected roundtrip PASS; got a={result.a_ast_equiv} "
        f"b={result.b_reparseable} compiled={result.compiled_text!r}"
    )


def _empty_report():
    """Build an ExtractionReport with no primary schedule."""
    from contingency_procedure2dsl.result import ExtractionReport
    return ExtractionReport()


def _atomic_report():
    from contingency_procedure2dsl.result import ExtractionReport, ExtractResult
    return ExtractionReport(
        schedules=(
            ExtractResult(
                ast={"type": "Atomic", "dist": "F", "domain": "R", "value": 1.0},
                confidence=1.0,
            ),
        )
    )


def test_run_reports_reader_T_none(monkeypatch):
    import contingency_procedure2dsl

    monkeypatch.setattr(contingency_procedure2dsl, "extract_all", lambda _t: _empty_report())
    result = run("doi/x", "anything")
    assert result.ok is False
    assert result.error == "reader(T) returned no AST"
    assert result.a_ast_equiv is False


def test_run_reports_reader_P_none(monkeypatch):
    import contingency_procedure2dsl
    import contingency_dsl2procedure

    class _Compiled:
        subjects = ""
        apparatus = ""
        procedure = "compiled procedure text"

    calls = {"n": 0}

    def fake_extract_all(_t):
        calls["n"] += 1
        return _atomic_report() if calls["n"] == 1 else _empty_report()

    monkeypatch.setattr(contingency_procedure2dsl, "extract_all", fake_extract_all)
    monkeypatch.setattr(contingency_dsl2procedure, "compile_method", lambda _a: _Compiled())

    result = run("doi/y", "input procedure text")
    assert result.ok is False
    assert result.error == "reader(P) returned no AST"
    assert result.b_reparseable is False
    assert result.compiled_text == "compiled procedure text"


def test_normalize_paper_distributes_shared_to_bodies():
    from contingency_dsl_e2e_roundtrip.roundtrip import _normalize_paper

    paper = {
        "type": "Paper",
        "shared_annotations": [
            {"type": "Annotation", "keyword": "species", "positional": "human"},
            {"type": "Annotation", "keyword": "n", "positional": 5},
        ],
        "experiments": [
            {
                "type": "Experiment",
                "label": "Experiment 1",
                "body": {
                    "type": "Program",
                    "program_annotations": [],
                    "schedule": {"type": "Atomic"},
                },
            },
            {
                "type": "Experiment",
                "label": "Experiment 2",
                "body": {
                    "type": "Program",
                    # experiment-level @species overrides shared
                    "program_annotations": [
                        {"type": "Annotation", "keyword": "species", "positional": "pigeon"},
                    ],
                    "schedule": {"type": "Atomic"},
                },
            },
        ],
    }

    out = _normalize_paper(paper)
    assert "shared_annotations" not in out, "shared must be cleared after merge"
    exp1_anns = out["experiments"][0]["body"]["program_annotations"]
    exp2_anns = out["experiments"][1]["body"]["program_annotations"]

    # Exp 1 received both shared annotations.
    kws1 = {a["keyword"] for a in exp1_anns}
    assert kws1 == {"species", "n"}
    assert any(a["keyword"] == "species" and a["positional"] == "human" for a in exp1_anns)

    # Exp 2 kept its own species (override) and received only @n from shared.
    species2 = [a for a in exp2_anns if a["keyword"] == "species"]
    assert len(species2) == 1 and species2[0]["positional"] == "pigeon"
    assert any(a["keyword"] == "n" and a["positional"] == 5 for a in exp2_anns)


def test_normalize_paper_empty_experiments_clears_shared():
    from contingency_dsl_e2e_roundtrip.roundtrip import _normalize_paper

    paper = {
        "type": "Paper",
        "shared_annotations": [
            {"type": "Annotation", "keyword": "species", "positional": "human"},
        ],
        "experiments": [],
    }
    out = _normalize_paper(paper)
    # Symmetric clear so re-extraction comparison agrees.
    assert "shared_annotations" not in out
    assert out["experiments"] == []


def test_normalize_paper_non_dict_body_preserves_shared():
    from contingency_dsl_e2e_roundtrip.roundtrip import _normalize_paper

    paper = {
        "type": "Paper",
        "shared_annotations": [
            {"type": "Annotation", "keyword": "species", "positional": "human"},
        ],
        "experiments": [
            {"type": "Experiment", "label": "1", "body": {"type": "Program"}},
            {"type": "Experiment", "label": "2", "body": "not-a-dict"},
        ],
    }
    out = _normalize_paper(paper)
    # Bail out: shared retained because we can't safely merge into a non-dict body.
    assert out.get("shared_annotations") == paper["shared_annotations"]


def test_normalize_paper_non_paper_passthrough():
    from contingency_dsl_e2e_roundtrip.roundtrip import _normalize_paper

    program = {"type": "Program", "schedule": {"type": "Atomic"}}
    assert _normalize_paper(program) is program
    assert _normalize_paper({"type": "Atomic"}) == {"type": "Atomic"}
    assert _normalize_paper(None) is None


def test_normalize_strips_sd_and_algorithm():
    from contingency_dsl_e2e_roundtrip.roundtrip import _normalize_ast

    program = {
        "type": "Program",
        "program_annotations": [
            {"type": "Annotation", "keyword": "species", "positional": "rat"},
            {"type": "Annotation", "keyword": "sd", "positional": "red"},
            {"type": "Annotation", "keyword": "algorithm", "positional": "fh"},
        ],
        "schedule": {"type": "Special", "kind": "EXT"},
    }
    out = _normalize_ast(program)
    kws = {a["keyword"] for a in out["program_annotations"]}
    assert kws == {"species"}


def test_normalize_keeps_population_when_species_human():
    """@population round-trips when species is human (population-as-species substitution)."""
    from contingency_dsl_e2e_roundtrip.roundtrip import _normalize_ast

    program = {
        "type": "Program",
        "program_annotations": [
            {"type": "Annotation", "keyword": "species", "positional": "human"},
            {"type": "Annotation", "keyword": "population", "positional": "children"},
        ],
        "schedule": {"type": "Atomic"},
    }
    out = _normalize_ast(program)
    kws = {a["keyword"] for a in out["program_annotations"]}
    assert "population" in kws, "@population must survive comparison when species=human"


def test_normalize_strips_population_when_species_not_human():
    """@population is dropped from comparison when species is non-human (mixed-extraction artefact)."""
    from contingency_dsl_e2e_roundtrip.roundtrip import _normalize_ast

    program = {
        "type": "Program",
        "program_annotations": [
            {"type": "Annotation", "keyword": "species", "positional": "pigeon"},
            {"type": "Annotation", "keyword": "population", "positional": "adults"},
        ],
        "schedule": {"type": "Atomic"},
    }
    out = _normalize_ast(program)
    kws = {a["keyword"] for a in out["program_annotations"]}
    assert "population" not in kws


def test_run_includes_annotations_in_ast1(monkeypatch):
    """Regression: annotations extracted from T must be present in ast1.

    The prior implementation used extract_schedule() which returned only
    the bare schedule AST, silently dropping @species / @strain etc.
    """
    import contingency_procedure2dsl
    from contingency_procedure2dsl.result import ExtractionReport, ExtractResult

    annotated = ExtractionReport(
        schedules=(
            ExtractResult(
                ast={"type": "Atomic", "dist": "F", "domain": "R", "value": 5.0},
                confidence=1.0,
            ),
        ),
        annotations=(
            ExtractResult(
                ast={"type": "Annotation", "keyword": "species", "positional": "rat"},
                confidence=1.0,
            ),
        ),
    )
    monkeypatch.setattr(contingency_procedure2dsl, "extract_all", lambda _t: annotated)

    # Stub compile_method so we don't care about its output here.
    import contingency_dsl2procedure

    class _Compiled:
        procedure = "stubbed"

    monkeypatch.setattr(contingency_dsl2procedure, "compile_method", lambda _a: _Compiled())

    result = run("doi/z", "input")
    assert result.ast1 is not None
    assert result.ast1.get("type") == "Program"
    assert result.ast1.get("program_annotations"), "annotations were dropped from ast1"
    assert result.ast1["program_annotations"][0]["keyword"] == "species"
