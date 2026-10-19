"""Dynamic discovery of procedure keys from contingency-dsl conformance corpus.

Each *.json file under `contingency-dsl/conformance/` becomes one procedure
key. The key is the POSIX-style relative path minus the `.json` suffix:

    conformance/operant/atomic.json             -> "operant/atomic"
    conformance/operant/stateful/adjusting.json -> "operant/stateful/adjusting"
    conformance/respondent/elementary.json      -> "respondent/elementary"

README.md and other non-JSON files are ignored. Deleting or renaming a
conformance file on the DSL side automatically removes or renames the
corresponding DOI list file on the next `report` run.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import conformance_root


@dataclass(frozen=True)
class ProcedureType:
    """One procedure key derived from a conformance JSON file."""

    key: str  # e.g. "operant/stateful/adjusting"
    source: Path  # absolute path to the conformance JSON

    @property
    def doi_list_filename(self) -> str:
        """Convert procedure key to a filesystem-safe md filename."""
        return self.key.replace("/", "__") + ".md"


def discover_procedures(root: Path | None = None) -> list[ProcedureType]:
    """Walk the conformance root, return one ProcedureType per JSON file."""
    base = root or conformance_root()
    if not base.is_dir():
        raise FileNotFoundError(f"conformance root missing: {base}")

    procedures: list[ProcedureType] = []
    for path in sorted(base.rglob("*.json")):
        rel = path.relative_to(base).with_suffix("")
        key = rel.as_posix()
        procedures.append(ProcedureType(key=key, source=path))
    return procedures
