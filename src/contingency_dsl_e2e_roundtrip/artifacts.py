"""Persist round-trip intermediates to `corpus/generated/`.

For every DOI processed by the round-trip harness, three artifacts are
written in their human-readable surface forms so they can be audited
outside the compact `state.json`:

    corpus/generated/dsl/<slug>.dsl        -- AST_1 rendered as canonical DSL
    corpus/generated/compiled/<slug>.txt   -- P (dsl2procedure paper text)
    corpus/generated/dsl2/<slug>.dsl       -- AST_2 rendered as canonical DSL

`<slug> = doi.replace("/", "_")`. AST dicts that cannot be wrapped into a
valid Program (e.g. partial Experiment / Paper nodes) are rendered with
a best-effort Program wrapper; if even that fails, a commented JSON
fallback is written so no round-trip result is silently lost.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from contingency_dsl import format_program, from_dict

from .config import generated_root, slug_for_doi
from .roundtrip import RoundtripResult


# Override hooks (tests); None means `<corpus>/generated/<sub>` at call time.
GENERATED_ROOT: Path | None = None
DSL_DIR: Path | None = None
COMPILED_DIR: Path | None = None
DSL2_DIR: Path | None = None


def _out_dir(override: Path | None, sub: str) -> Path:
    if override is not None:
        return override
    return (GENERATED_ROOT or generated_root()) / sub

_PROGRAM_ROOT_TYPES = frozenset({"Program", "Experiment", "Paper", "PhaseSequence"})


@dataclass(frozen=True)
class ArtifactPaths:
    dsl: Path | None
    compiled: Path | None
    dsl2: Path | None


def render_dsl(ast: Any) -> str:
    """Render an AST dict as canonical DSL surface text.

    Paper / Experiment roots are rendered as concatenated labelled Program
    blocks separated by a blank line, since ``contingency_dsl.from_dict``
    only accepts Program roots directly.

    Falls back to a JSON sidecar comment if a Program can't be parsed.
    If even JSON fails (non-serializable), a repr() sidecar is emitted so
    no round-trip result is ever silently lost.
    """
    if isinstance(ast, dict):
        t = ast.get("type")
        if t == "Paper":
            return _render_paper(ast)
        if t == "Experiment":
            return _render_experiment(ast)

    program = _wrap_program(ast)
    return _render_program_dict(program, ast)


def _render_program_dict(program: dict, original: Any) -> str:
    try:
        parsed = from_dict(program)
        return format_program(parsed) + "\n"
    except Exception as exc:
        reason = _sanitize_reason(exc)
        try:
            body = json.dumps(original, ensure_ascii=False, indent=2, sort_keys=True)
        except Exception as json_exc:
            body = f"# json.dumps failed: {_sanitize_reason(json_exc)}\n{original!r}"
        return f"# AST not printable as DSL ({reason})\n{body}\n"


def _render_paper(ast: dict) -> str:
    chunks: list[str] = []
    shared = ast.get("shared_annotations") or []
    if shared:
        shared_lines = ["# shared (applies to every experiment)"]
        for ann in shared:
            shared_lines.append(_format_annotation(ann))
        chunks.append("\n".join(shared_lines) + "\n")
    for exp in ast.get("experiments", []) or []:
        chunks.append(_render_experiment(exp))
    return "\n".join(chunks) if chunks else "# empty Paper\n"


def _format_annotation(ann: dict) -> str:
    """Best-effort one-line rendering of an @annotation for display."""
    kw = ann.get("keyword", "?")
    pos = ann.get("positional")
    params = ann.get("params") or {}
    if params:
        pairs = ", ".join(f"{k}={v!r}" for k, v in params.items())
        return f"@{kw}({pairs})"
    if isinstance(pos, str):
        return f'@{kw}("{pos}")'
    if pos is None:
        return f"@{kw}()"
    return f"@{kw}({pos})"


def _render_experiment(ast: dict) -> str:
    label = ast.get("label", "Experiment").strip() or "Experiment"
    body = ast.get("body", {})
    body_type = body.get("type") if isinstance(body, dict) else None
    if body_type == "PhaseSequence":
        rendered = _render_program_dict(body, body)
    else:
        rendered = _render_program_dict(_wrap_program(body), body)
    return f"# {label}\n{rendered}"


def _sanitize_reason(exc: BaseException) -> str:
    """Flatten exception text to a single line for safe embedding in a comment."""
    msg = f"{type(exc).__name__}: {exc}"
    return msg.replace("\n", " ").replace("\r", " ")


def _wrap_program(ast: Any) -> dict:
    if isinstance(ast, dict) and ast.get("type") in _PROGRAM_ROOT_TYPES:
        return ast
    return {
        "type": "Program",
        "program_annotations": [],
        "param_decls": [],
        "bindings": [],
        "schedule": ast,
    }


def _write_text(path: Path, text: str) -> None:
    """Atomically write `text` to `path` (temp file + os.replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp_name, path)
    except Exception:
        # Best-effort cleanup; mkstemp creates the file so it always exists here.
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def save(result: RoundtripResult) -> ArtifactPaths:
    """Write DSL surface forms of AST_1 / AST_2 and the compiled paper text."""
    slug = slug_for_doi(result.doi)

    dsl_path: Path | None = None
    compiled_path: Path | None = None
    dsl2_path: Path | None = None

    if result.ast1 is not None:
        dsl_path = _out_dir(DSL_DIR, "dsl") / f"{slug}.dsl"
        _write_text(dsl_path, render_dsl(result.ast1))

    if result.compiled_text is not None:
        compiled_path = _out_dir(COMPILED_DIR, "compiled") / f"{slug}.txt"
        _write_text(compiled_path, result.compiled_text)

    if result.ast2 is not None:
        dsl2_path = _out_dir(DSL2_DIR, "dsl2") / f"{slug}.dsl"
        _write_text(dsl2_path, render_dsl(result.ast2))

    return ArtifactPaths(dsl=dsl_path, compiled=compiled_path, dsl2=dsl2_path)
