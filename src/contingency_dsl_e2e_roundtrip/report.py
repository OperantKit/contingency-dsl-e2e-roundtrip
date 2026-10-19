"""Render per-procedure DOI list markdown files from state.json.

One markdown file per procedure key. A DOI appears under every procedure it is
classified into. The checkbox reflects the overall PASS flag from the most
recent roundtrip; judgments (a)(b)(c)(d) are recorded inline for audit.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import doi_lists_dir
from .procedures import ProcedureType, discover_procedures


def _fmt_judgments(rt: dict[str, Any] | None) -> str:
    if rt is None:
        return "(not run)"
    a = rt.get("a_ast_equiv")
    b = rt.get("b_reparseable")
    c = rt.get("c_text_similarity")
    d = rt.get("d_notation_equiv")

    def tick(v: bool | None) -> str:
        return "✓" if v is True else "✗" if v is False else "–"

    c_str = f"{c:.2f}" if isinstance(c, (int, float)) else "–"
    parts = [f"a:{tick(a)}", f"b:{tick(b)}", f"c:{c_str}", f"d:{tick(d)}"]
    status = "PASS" if rt.get("ok") else "FAIL"
    suffix = f" ({rt.get('error')})" if rt.get("error") and not rt.get("ok") else ""
    return f"{status} ({' '.join(parts)}){suffix}"


def _checkbox(rt: dict[str, Any] | None) -> str:
    return "[x]" if rt is not None and rt.get("ok") else "[ ]"


def _entries_by_procedure(state: dict[str, Any]) -> dict[str, list[tuple[str, dict]]]:
    by_proc: dict[str, list[tuple[str, dict]]] = {}
    for doi, entry in state.get("entries", {}).items():
        for key in entry.get("procedures", []):
            by_proc.setdefault(key, []).append((doi, entry))
    return by_proc


def render(
    state: dict[str, Any],
    *,
    procedures: list[ProcedureType] | None = None,
    out_dir: Path | None = None,
) -> list[Path]:
    procs = procedures or discover_procedures()
    target_dir = out_dir or doi_lists_dir()
    target_dir.mkdir(parents=True, exist_ok=True)

    by_proc = _entries_by_procedure(state)
    written: list[Path] = []

    for proc in procs:
        rows = sorted(by_proc.get(proc.key, []), key=lambda pair: pair[0])
        in_scope = [(d, e) for d, e in rows if not e.get("out_of_scope_reason")]
        out_of_scope = [(d, e) for d, e in rows if e.get("out_of_scope_reason")]
        lines = [
            f"# {proc.key}",
            "",
            f"Procedure source: `{proc.source.name}`  ",
            f"Total papers classified: **{len(in_scope)}**  ",
            f"Passing: **{sum(1 for _, e in in_scope if (e.get('roundtrip') or {}).get('ok'))}**",
            "",
            "## DOIs",
            "",
        ]
        if not in_scope:
            lines.append("_(no papers classified into this procedure yet)_")
        else:
            for doi, entry in in_scope:
                rt = entry.get("roundtrip")
                lines.append(f"- {_checkbox(rt)} `{doi}` — {_fmt_judgments(rt)}")

        if out_of_scope:
            lines.append("")
            lines.append("## Out of scope")
            lines.append("")
            for doi, entry in out_of_scope:
                reason = entry.get("out_of_scope_reason", "")
                lines.append(f"- `{doi}` — {reason}")
        lines.append("")

        out = target_dir / proc.doi_list_filename
        out.write_text("\n".join(lines), encoding="utf-8")
        written.append(out)

    _write_index(target_dir, procs, by_proc, state)
    written.append(target_dir / "index.md")
    return written


def _write_index(
    target_dir: Path,
    procs: list[ProcedureType],
    by_proc: dict[str, list[tuple[str, dict]]],
    state: dict[str, Any],
) -> None:
    entries = state.get("entries", {})
    total_papers = len(entries)
    out_of_scope_total = sum(
        1 for e in entries.values() if e.get("out_of_scope_reason")
    )
    lines = [
        "# DOI lists by procedure",
        "",
        f"Total classified DOIs: **{total_papers}**",
        f"Out of scope: **{out_of_scope_total}**",
        "",
    ]
    for proc in procs:
        rows = by_proc.get(proc.key, [])
        in_scope = [(d, e) for d, e in rows if not e.get("out_of_scope_reason")]
        passing = sum(
            1 for _, e in in_scope if (e.get("roundtrip") or {}).get("ok")
        )
        lines.append(
            f"- [{proc.key}]({proc.doi_list_filename}) — {passing}/{len(in_scope)} passing"
        )
    lines.append("")
    (target_dir / "index.md").write_text("\n".join(lines), encoding="utf-8")
