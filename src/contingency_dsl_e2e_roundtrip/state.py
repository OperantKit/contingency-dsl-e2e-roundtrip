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
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import config


# Override hook (tests); None means `config.state_path()` at call time.
STATE_PATH: Path | None = None


_LARGE_FIELDS = ("ast1", "ast2", "compiled_text")


def load(path: Path | None = None) -> dict[str, Any]:
    p = path or STATE_PATH or config.state_path()
    if not p.is_file():
        return {"version": 1, "entries": {}}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"version": 1, "entries": {}}


def save(state: dict[str, Any], path: Path | None = None) -> None:
    p = path or STATE_PATH or config.state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
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
    entry = entries.setdefault(doi, {})
    entry["procedures"] = procedures
    entry["classified_with"] = model
    if out_of_scope_reason:
        entry["out_of_scope_reason"] = out_of_scope_reason
    else:
        entry.pop("out_of_scope_reason", None)


def upsert_roundtrip(state: dict[str, Any], doi: str, result: dict[str, Any]) -> None:
    entries = state.setdefault("entries", {})
    entry = entries.setdefault(doi, {})
    compact = {k: v for k, v in result.items() if k not in _LARGE_FIELDS}
    entry["roundtrip"] = compact
