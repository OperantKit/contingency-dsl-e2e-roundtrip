"""Roundtrip judgments (a), (b), (c), (d).

Pipeline:
    T  ──reader──▶ ast1  ──paper──▶ P  ──reader──▶ ast2

Judgments:
    (a) AST semantic equivalence:    normalize(ast1) == normalize(ast2)
    (b) Reader re-parseable on P:    ast2 is not None
    (c) Text similarity(T, P):       Jaccard over lowercased word tokens
    (d) DSL notation equivalence:    canonical_json(ast1) == canonical_json(ast2)

Overall PASS is determined by (a) alone, per spec. (b)(c)(d) are reported.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class RoundtripResult:
    doi: str
    ok: bool
    a_ast_equiv: bool | None
    b_reparseable: bool | None
    c_text_similarity: float | None
    d_notation_equiv: bool | None
    error: str | None = None
    ast1: Any | None = None
    ast2: Any | None = None
    compiled_text: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # ASTs are already plain dicts/None; no special handling needed.
        return d


_WORD_RE = re.compile(r"[A-Za-z\u3040-\u30ff\u4e00-\u9fff0-9]+")


def _tokens(text: str) -> set[str]:
    return set(m.group(0).lower() for m in _WORD_RE.finditer(text))


def jaccard(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta and not tb:
        return 1.0
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


# Annotation keywords that ``contingency-dsl2procedure.compile_method``
# currently does not emit as deterministic natural language. They are
# stripped from AST equivalence comparison so ast1 vs ast2 converges,
# while remaining in the persisted DSL artifact for human review.
#
# Intent: the round-trip (a) judgment should only penalise mismatches in
# facts that compile_method is actually capable of rendering back.
_NON_ROUNDTRIP_KEYWORDS = frozenset({
    "algorithm",     # e.g. @algorithm("fleshler-hoffman") — citation only
    "sd",            # @sd not emitted as reinsertable SD phrase
    "measurement",
})


def _strip_non_roundtrip_annotations(anns):
    """Return a new annotation list with non-roundtrippable entries dropped.

    @population is conditionally stripped: when @species("human") is in
    the same annotation list, ``compile_method`` substitutes the
    population term for the species word ("Five children served as
    subjects."), so @population *does* round-trip. When the species is
    anything else (or absent), @population is a mixed-extraction
    artefact and is dropped from comparison.
    """
    if not anns:
        return anns
    has_human_species = any(
        isinstance(a, dict)
        and a.get("keyword") == "species"
        and str(a.get("positional", "")).lower() == "human"
        for a in anns
    )
    out = []
    for a in anns:
        if not isinstance(a, dict):
            out.append(a)
            continue
        kw = a.get("keyword")
        if kw in _NON_ROUNDTRIP_KEYWORDS:
            continue
        if kw == "population" and not has_human_species:
            continue
        out.append(a)
    return out


def _normalize_ast(node: Any) -> Any:
    """Deep-normalize for semantic equivalence: drop None-valued keys, sort
    dicts. Also drops annotations whose keywords don't round-trip through
    compile_method so the (a) judgment isn't triggered by emit gaps that
    have nothing to do with the underlying schedule semantics.
    """
    if isinstance(node, dict):
        out = {}
        for k in sorted(node.keys()):
            if k in ("program_annotations", "shared_annotations"):
                filtered = _strip_non_roundtrip_annotations(node[k])
                v = _normalize_ast(filtered)
            else:
                v = _normalize_ast(node[k])
            if v is None:
                continue
            out[k] = v
        return out
    if isinstance(node, list):
        return [_normalize_ast(item) for item in node]
    return node


def canonical_json(node: Any) -> str:
    return json.dumps(node, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


_PROGRAM_ROOT_TYPES = frozenset({"Program", "Experiment", "Paper", "PhaseSequence"})


def _wrap_for_compile(ast: Any) -> Any:
    """Wrap a bare schedule AST in a Program node so compile_method accepts it.

    extract_schedule returns the primary schedule node (e.g. Atomic), but
    compile_method expects a Program/Experiment/Paper/PhaseSequence root. When
    the AST is already one of those roots, return it unchanged.
    """
    if isinstance(ast, dict) and ast.get("type") in _PROGRAM_ROOT_TYPES:
        return ast
    return {
        "type": "Program",
        "program_annotations": [],
        "param_decls": [],
        "bindings": [],
        "schedule": ast,
    }


def _extract_program(text: str):
    """Run the full extractor and assemble a Program / Paper AST.

    Tries ``extract_paper`` first — when a document contains two or more
    ``Experiment N`` headings, the Paper wrapper preserves each experiment's
    body as an independent Program / PhaseSequence, which carries more
    fidelity than a single primary-schedule summary. Papers are then
    normalized so shared facts appear in ``shared_annotations`` rather
    than duplicated per-experiment, which keeps compile → re-extract
    round-trips stable even when the compiled text repeats the same
    subject info in every experiment.

    Falls back to ``extract_all().to_program()`` for single-experiment
    documents. Returns ``(ast_dict_or_None, report_or_None)``.
    """
    from contingency_procedure2dsl import extract_all, extract_paper

    paper = extract_paper(text)
    if paper is not None:
        return _normalize_paper(paper.ast), None

    report = extract_all(text)
    if report.primary_schedule is None:
        return None, report
    return report.to_program(), report


def _normalize_paper(paper: dict) -> dict:
    """Distribute ``shared_annotations`` into every experiment's body.

    ``compile_paper`` expands Paper.shared_annotations by merging them
    into each experiment's program_annotations (with experiment-level
    overrides winning on keyword collision). A subsequent ``extract_paper``
    pass therefore sees only per-body annotations — shared becomes empty.

    To make round-trip comparison stable we apply the same merge to both
    ast1 and ast2: every shared annotation that isn't already overridden
    by a same-keyword annotation in a given experiment is copied into
    that experiment's body, and ``shared_annotations`` is cleared.

    Edge cases:
    - Non-dict input or non-Paper type: returned unchanged.
    - No experiments: shared_annotations is cleared regardless to keep
      ast1/ast2 symmetric (the compile step would emit nothing for an
      empty Paper, and re-extraction therefore produces no shared either).
    - Non-dict experiment body: that experiment is skipped during merge
      but kept in the output. shared_annotations is preserved on the
      Paper in this case so information isn't silently lost — this only
      occurs for malformed extractions.
    """
    if not isinstance(paper, dict) or paper.get("type") != "Paper":
        return paper

    shared = list(paper.get("shared_annotations") or [])
    experiments = list(paper.get("experiments") or [])

    if not experiments:
        # Symmetric clear: empty Paper compiles to no text, so ast2 will
        # have no shared either.
        if shared:
            out = dict(paper)
            out.pop("shared_annotations", None)
            return out
        return paper

    if not shared:
        return paper

    # Bail out (preserve shared_annotations) if any experiment has a
    # non-dict body — we can't safely merge into a malformed body.
    if not all(
        isinstance(exp.get("body"), dict)
        for exp in experiments
        if isinstance(exp, dict)
    ):
        return paper

    new_experiments: list[dict] = []
    for exp in experiments:
        new_exp = dict(exp)
        body = exp.get("body")
        if isinstance(body, dict):
            existing = list(body.get("program_annotations") or [])
            existing_kws = {
                a.get("keyword") for a in existing if isinstance(a, dict)
            }
            merged = list(existing)
            for a in shared:
                if isinstance(a, dict) and a.get("keyword") not in existing_kws:
                    merged.append(a)
            new_body = dict(body)
            new_body["program_annotations"] = merged
            new_exp["body"] = new_body
        new_experiments.append(new_exp)

    out = dict(paper)
    out["experiments"] = new_experiments
    out.pop("shared_annotations", None)
    return out


def _method_text(method) -> str:
    """Join subjects + apparatus + procedure into a single flat string."""
    parts = [method.subjects, method.apparatus, method.procedure]
    joined = " ".join(p for p in parts if p).strip()
    return joined or method.procedure


def _compile_to_text(ast1: dict) -> str:
    """Compile any supported root AST to Method-section-like text.

    Paper inputs are compiled via ``compile_paper`` and stitched back
    together with ``Experiment N`` headings so that a downstream
    ``extract_paper`` pass can re-segment them.
    """
    from contingency_dsl2procedure import compile_method, compile_paper

    if isinstance(ast1, dict) and ast1.get("type") == "Paper":
        sections = compile_paper(ast1)
        if sections:
            chunks: list[str] = []
            for label, method in sections:
                body = _method_text(method)
                if not body:
                    continue
                chunks.append(f"{label}\n\n{body}")
            joined = "\n\n".join(chunks).strip()
            if joined:
                return joined

    compiled = compile_method(_wrap_for_compile(ast1))
    return _method_text(compiled)


def run(doi: str, procedure_text: str) -> RoundtripResult:
    try:
        ast1, _ = _extract_program(procedure_text)
    except Exception as exc:
        return RoundtripResult(
            doi=doi,
            ok=False,
            a_ast_equiv=None,
            b_reparseable=None,
            c_text_similarity=None,
            d_notation_equiv=None,
            error=f"reader(T) failed: {exc}",
        )

    if ast1 is None:
        return RoundtripResult(
            doi=doi,
            ok=False,
            a_ast_equiv=False,
            b_reparseable=None,
            c_text_similarity=None,
            d_notation_equiv=False,
            error="reader(T) returned no AST",
        )

    try:
        compiled_text = _compile_to_text(ast1)
    except Exception as exc:
        return RoundtripResult(
            doi=doi,
            ok=False,
            a_ast_equiv=None,
            b_reparseable=None,
            c_text_similarity=None,
            d_notation_equiv=None,
            error=f"paper(ast1) failed: {exc}",
            ast1=ast1,
        )

    try:
        ast2, _ = _extract_program(compiled_text)
    except Exception as exc:
        return RoundtripResult(
            doi=doi,
            ok=False,
            a_ast_equiv=False,
            b_reparseable=False,
            c_text_similarity=jaccard(procedure_text, compiled_text),
            d_notation_equiv=False,
            error=f"reader(P) failed: {exc}",
            ast1=ast1,
            compiled_text=compiled_text,
        )

    b_reparseable = ast2 is not None
    if ast2 is None:
        return RoundtripResult(
            doi=doi,
            ok=False,
            a_ast_equiv=False,
            b_reparseable=False,
            c_text_similarity=jaccard(procedure_text, compiled_text),
            d_notation_equiv=False,
            error="reader(P) returned no AST",
            ast1=ast1,
            compiled_text=compiled_text,
        )

    a = _normalize_ast(ast1) == _normalize_ast(ast2)
    d = canonical_json(ast1) == canonical_json(ast2)
    c = jaccard(procedure_text, compiled_text)

    return RoundtripResult(
        doi=doi,
        ok=bool(a),
        a_ast_equiv=a,
        b_reparseable=b_reparseable,
        c_text_similarity=c,
        d_notation_equiv=d,
        ast1=ast1,
        ast2=ast2,
        compiled_text=compiled_text,
    )
