"""Per-DOI persistent state.

Schema (JSON):
    {
      "version": 1,
      "entries": {
        "<doi>": {
          "procedures": ["operant/atomic", ...],
          "roundtrip": { <RoundtripResult.to_dict() minus large AST fields> } | null,
          "classified_with": "<model-id>"
        }
      }
    }

Large fields (ast1, ast2, compiled_text) are kept out of state.json to prevent
it from ballooning. They are regenerable from the extraction cache.

DOIs are case-insensitive, so every key is stored lowercased. ``load`` and
``save`` fold case variants of the same DOI into one entry (see
``merge_entries``), and the ``upsert_*`` helpers normalize the DOI they get.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import config


# Override hook (tests); None means `config.state_path()` at call time.
STATE_PATH: Path | None = None


_LARGE_FIELDS = ("ast1", "ast2", "compiled_text")


def normalize_doi(doi: str) -> str:
    """The key under which a DOI is stored: stripped and lowercased."""
    return doi.strip().lower()


def _rank(entry: dict[str, Any]) -> tuple[int, int, int]:
    return (
        0 if entry.get("out_of_scope_reason") else 1,
        len(entry.get("procedures") or []),
        1 if entry.get("roundtrip") else 0,
    )


def merge_entries(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """Pick one of two entries recorded for the same DOI.

    Entries carry no timestamp, so the one with more information wins:
    in scope over out of scope, then more procedures, then one with a
    roundtrip result. On a tie the second argument wins.
    """
    return a if _rank(a) > _rank(b) else b


def _fold_case(entries: dict[str, Any]) -> dict[str, Any]:
    folded: dict[str, Any] = {}
    # Lowercase keys last so they win ties against their case variants.
    for doi in sorted(entries, key=lambda k: (k == normalize_doi(k), k)):
        key = normalize_doi(doi)
        entry = entries[doi]
        folded[key] = merge_entries(folded[key], entry) if key in folded else entry
    return folded


def _with_folded_entries(state: dict[str, Any]) -> dict[str, Any]:
    return {**state, "entries": _fold_case(state.get("entries", {}))}


def load(path: Path | None = None) -> dict[str, Any]:
    p = path or STATE_PATH or config.state_path()
    if not p.is_file():
        return {"version": 1, "entries": {}}
    try:
        return _with_folded_entries(json.loads(p.read_text(encoding="utf-8")))
    except json.JSONDecodeError:
        return {"version": 1, "entries": {}}


def save(state: dict[str, Any], path: Path | None = None) -> None:
    p = path or STATE_PATH or config.state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(_with_folded_entries(state), ensure_ascii=False, indent=2,
                   sort_keys=True) + "\n",
        encoding="utf-8",
    )


def upsert_classification(
    state: dict[str, Any],
    doi: str,
    procedures: list[str],
    model: str,
    *,
    out_of_scope_reason: str | None = None,
) -> None:
    entries = state.setdefault("entries", {})
    entry = entries.setdefault(normalize_doi(doi), {})
    entry["procedures"] = procedures
    entry["classified_with"] = model
    if out_of_scope_reason:
        entry["out_of_scope_reason"] = out_of_scope_reason
    else:
        entry.pop("out_of_scope_reason", None)


def upsert_roundtrip(state: dict[str, Any], doi: str, result: dict[str, Any]) -> None:
    entries = state.setdefault("entries", {})
    entry = entries.setdefault(normalize_doi(doi), {})
    compact = {k: v for k, v in result.items() if k not in _LARGE_FIELDS}
    entry["roundtrip"] = compact
