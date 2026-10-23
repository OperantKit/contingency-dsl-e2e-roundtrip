"""Inter-rater agreement between ``state.json`` and a second rater.

The first rater is whatever classified the paper into ``state.json``; the
second rater is a JSONL file of ``{"doi", "procedures", "out_of_scope_reason",
"model", "backend"}`` rows (the output of ``e2e second-rate``).

For every taxonomy key the two raters' binary decisions (assigned / not
assigned) over the matched papers form a 2 x 2 table, summarised with
Cohen's (1960) kappa. ``micro`` pools every (key, paper) decision into one
table, ``macro`` is the mean kappa over keys where kappa is defined, and
``in-scope`` compares "has at least one procedure" between the raters.

Cohen, J. (1960). A coefficient of agreement for nominal scales. Educational
and Psychological Measurement, 20(1), 37-46.
https://doi.org/10.1177/001316446002000104
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass
from typing import Any, Iterable

from .state import normalize_doi


@dataclass(frozen=True)
class KeyAgreement:
    key: str
    both: int  # a: both raters assigned
    only1: int  # b: first rater only
    only2: int  # c: second rater only
    neither: int  # d

    @property
    def n(self) -> int:
        return self.both + self.only1 + self.only2 + self.neither

    @property
    def n1(self) -> int:
        return self.both + self.only1

    @property
    def n2(self) -> int:
        return self.both + self.only2

    @property
    def p_o(self) -> float | None:
        return (self.both + self.neither) / self.n if self.n else None

    @property
    def kappa(self) -> float | None:
        return kappa_2x2(self.both, self.only1, self.only2, self.neither)

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "n1": self.n1,
            "n2": self.n2,
            "p_o": self.p_o,
            "kappa": self.kappa,
        }


@dataclass(frozen=True)
class AgreementTable:
    n: int
    unmatched: int
    first_raters: dict[str, int]
    second_raters: dict[str, int]
    rows: tuple[KeyAgreement, ...]
    micro: KeyAgreement
    in_scope: KeyAgreement
    n_keys: int

    @property
    def macro(self) -> float | None:
        defined = [r.kappa for r in self.rows if r.kappa is not None]
        return sum(defined) / len(defined) if defined else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "n": self.n,
            "unmatched": self.unmatched,
            "first_raters": self.first_raters,
            "second_raters": self.second_raters,
            "rows": [r.to_dict() for r in self.rows],
            "micro": self.micro.to_dict(),
            "macro": self.macro,
            "in_scope": self.in_scope.to_dict(),
            "n_keys": self.n_keys,
        }


def kappa_2x2(a: int, b: int, c: int, d: int) -> float | None:
    """Cohen's kappa for a 2 x 2 table; None when chance agreement is 1."""
    n = a + b + c + d
    if n == 0:
        return None
    p_o = (a + d) / n
    p_e = ((a + b) * (a + c) + (c + d) * (b + d)) / (n * n)
    if p_e >= 1.0:
        return None
    return (p_o - p_e) / (1.0 - p_e)


def _tally(key: str, pairs: Iterable[tuple[bool, bool]]) -> KeyAgreement:
    counts = Counter(pairs)
    return KeyAgreement(
        key=key,
        both=counts[(True, True)],
        only1=counts[(True, False)],
        only2=counts[(False, True)],
        neither=counts[(False, False)],
    )


def agreement_table(
    state_entries: dict[str, dict[str, Any]],
    second_rows: list[dict[str, Any]],
    keys: list[str],
) -> AgreementTable:
    """Match second-rater rows to state entries by normalized DOI and tally."""
    first = {normalize_doi(doi): entry for doi, entry in state_entries.items()}
    second: dict[str, dict[str, Any]] = {}
    unmatched = 0
    for row in second_rows:
        doi = normalize_doi(str(row.get("doi", "")))
        if doi not in first:
            unmatched += 1
            continue
        second[doi] = row

    matched = sorted(second)
    sets1 = {d: set(first[d].get("procedures") or []) for d in matched}
    sets2 = {d: set(second[d].get("procedures") or []) for d in matched}

    rows = tuple(
        _tally(k, ((k in sets1[d], k in sets2[d]) for d in matched)) for k in keys
    )
    micro = KeyAgreement(
        key=f"micro ({len(keys)} keys)",
        both=sum(r.both for r in rows),
        only1=sum(r.only1 for r in rows),
        only2=sum(r.only2 for r in rows),
        neither=sum(r.neither for r in rows),
    )
    in_scope = _tally(
        "in-scope", ((bool(sets1[d]), bool(sets2[d])) for d in matched)
    )
    return AgreementTable(
        n=len(matched),
        unmatched=unmatched,
        first_raters=dict(sorted(Counter(
            str(first[d].get("classified_with", "?")) for d in matched
        ).items())),
        second_raters=dict(sorted(Counter(
            str(second[d].get("model", "?")) for d in matched
        ).items())),
        rows=rows,
        micro=micro,
        in_scope=in_scope,
        n_keys=len(keys),
    )


def load_jsonl(text: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def _sorted_rows(table: AgreementTable, used_only: bool) -> list[KeyAgreement]:
    rows = [r for r in table.rows if not used_only or r.n1 or r.n2]
    defined = sorted((r for r in rows if r.kappa is not None),
                     key=lambda r: (r.kappa, r.key))
    undefined = sorted((r for r in rows if r.kappa is None), key=lambda r: r.key)
    return defined + undefined


def _reading(kappa: float | None) -> str:
    """Landis & Koch (1977) conventional bands."""
    if kappa is None:
        return "—"
    if kappa < 0:
        return "poor"
    for upper, label in ((0.20, "slight"), (0.40, "fair"), (0.60, "moderate"),
                         (0.80, "substantial")):
        if kappa <= upper:
            return label
    return "almost perfect"


def _fmt(value: float | None) -> str:
    return "—" if value is None else f"{value:.3f}"


def header_line(table: AgreementTable) -> str:
    first = ",".join(f"{k}:{v}" for k, v in table.first_raters.items())
    second = ",".join(table.second_raters) or "?"
    return f"N={table.n} unmatched={table.unmatched} first={first} second={second}"


_COLUMNS = ("key", "n1", "n2", "both", "only1", "only2", "p_o", "kappa", "reading")


def _cells(r: KeyAgreement) -> list[str]:
    return [r.key, str(r.n1), str(r.n2), str(r.both), str(r.only1), str(r.only2),
            _fmt(r.p_o), _fmt(r.kappa), _reading(r.kappa)]


def _summary_cells(table: AgreementTable) -> list[list[str]]:
    macro = table.macro
    return [
        _cells(table.in_scope),
        _cells(table.micro),
        ["macro (defined keys)", "", "", "", "", "", "", _fmt(macro), _reading(macro)],
    ]


def format_md(table: AgreementTable, *, used_only: bool = False) -> str:
    lines = [header_line(table), "",
             "| " + " | ".join(_COLUMNS) + " |",
             "|" + "---|" * len(_COLUMNS)]
    body = [_cells(r) for r in _sorted_rows(table, used_only)]
    for cells in body + _summary_cells(table):
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def format_tsv(table: AgreementTable, *, used_only: bool = False) -> str:
    lines = ["# " + header_line(table), "\t".join(_COLUMNS)]
    body = [_cells(r) for r in _sorted_rows(table, used_only)]
    for cells in body + _summary_cells(table):
        lines.append("\t".join(cells))
    return "\n".join(lines) + "\n"


def format_json(table: AgreementTable, *, used_only: bool = False) -> str:
    payload = table.to_dict()
    payload["rows"] = [r.to_dict() for r in _sorted_rows(table, used_only)]
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
