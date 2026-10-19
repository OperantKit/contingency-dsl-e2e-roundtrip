"""Batch-mode classification queue/result helpers.

Splits LLM classification into three disjoint steps so the CLI never has to
invoke an LLM itself:

    1. ``prepare_queue(out)`` writes a JSONL queue of {doi, method_text,
       allowed_keys} for every DOI that is not yet classified in state.json.
       Extraction is ensured en route.
    2. An external driver (typically a Claude Code subagent invoked by the
       interactive session) works through the queue: ``next_batch(n)`` cuts
       the next ``n`` unclassified rows into prompt files, and
       ``ingest_batch(path)`` appends the driver's {doi, procedures} lines
       to the results JSONL.
    3. ``ingest_results(path)`` folds the result file into state.json.

The queue, results, and prompt files live under ``<corpus>/work/``, which is
gitignored except for its README.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, TextIO

from . import config
from . import extract as extract_mod
from . import state as state_mod
from .papers import all_dois_with_any_asset
from .procedures import discover_procedures


QUEUE_FILENAME = "classify-queue.jsonl"
RESULTS_FILENAME = "classify-results.jsonl"
PENDING_DIRNAME = "pending"
DEFAULT_SUBAGENT_MODEL_TAG = "procedure-classifier-haiku"


def default_queue_path() -> Path:
    return config.work_dir() / QUEUE_FILENAME


def default_results_path() -> Path:
    return config.work_dir() / RESULTS_FILENAME


def default_pending_dir() -> Path:
    return config.work_dir() / PENDING_DIRNAME

# Keep one queue row comfortably below Haiku 200K context after taxonomy +
# template overhead, and avoid shipping entire textbooks or multi-chapter PDFs
# that the Method-section slicer occasionally lets through.
DEFAULT_MAX_METHOD_CHARS = 18_000
# Anything shorter than this is almost certainly a note template with no real
# Method section content (e.g. "### 被験体  ### 手続き  ### 従属変数").
DEFAULT_MIN_METHOD_CHARS = 80


def prepare_queue(
    out_path: Path | None = None,
    *,
    dois: Iterable[str] | None = None,
    skip_classified: bool = True,
    max_chars: int = DEFAULT_MAX_METHOD_CHARS,
    min_chars: int = DEFAULT_MIN_METHOD_CHARS,
) -> tuple[Path, int, int]:
    """Write one JSONL row per DOI that needs classification.

    Rows with Method-section plaintext shorter than ``min_chars`` are skipped
    (most likely empty note templates). Rows longer than ``max_chars`` are
    truncated in-place so a single queue row stays within Haiku's context.

    Returns (path, enqueued_count, skipped_count).
    """
    if out_path is None:
        out_path = default_queue_path()
    procedures = discover_procedures()
    allowed_keys = [p.key for p in procedures]
    state = state_mod.load()
    classified = {
        doi for doi, e in state.get("entries", {}).items()
        if e.get("procedures") is not None
    }

    candidates = list(dois) if dois is not None else all_dois_with_any_asset()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    enqueued = 0
    skipped = 0
    with out_path.open("w", encoding="utf-8") as fh:
        for doi in candidates:
            if skip_classified and doi in classified:
                skipped += 1
                continue
            extracted = extract_mod.ensure_extracted(doi)
            if extracted is None:
                skipped += 1
                continue
            _, text = extracted
            if len(text) < min_chars:
                skipped += 1
                continue
            truncated = len(text) > max_chars
            text_out = text[:max_chars] if truncated else text
            row = {
                "doi": doi,
                "allowed_keys": allowed_keys,
                "method_text": text_out,
                "truncated": truncated,
            }
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            enqueued += 1
    return out_path, enqueued, skipped


@dataclass(frozen=True)
class PendingItem:
    doi: str
    prompt_file: Path


def _read_jsonl_dois(path: Path) -> set[str]:
    dois: set[str] = set()
    if not path.exists():
        return dois
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            doi = json.loads(line)["doi"]
        except (json.JSONDecodeError, KeyError, TypeError):
            continue
        if isinstance(doi, str):
            dois.add(doi)
    return dois


def next_batch(
    n: int,
    *,
    queue_path: Path | None = None,
    results_path: Path | None = None,
    pending_dir: Path | None = None,
) -> tuple[list[PendingItem], int]:
    """Cut the next ``n`` unclassified queue rows into prompt files.

    A row counts as classified once its DOI appears in the results JSONL.
    Each emitted DOI's subagent prompt is written to
    ``<pending_dir>/<slug>.txt``.

    Returns (emitted_items, remaining) where ``remaining`` counts every
    unclassified DOI in the queue, including the ones just emitted.
    """
    if n <= 0:
        raise ValueError("n must be positive")
    queue_path = queue_path or default_queue_path()
    results_path = results_path or default_results_path()
    pending_dir = pending_dir or default_pending_dir()
    if not queue_path.is_file():
        raise FileNotFoundError(
            f"queue not found: {queue_path} (run `e2e classify-prepare` first)"
        )

    done = _read_jsonl_dois(results_path)
    pending_dir.mkdir(parents=True, exist_ok=True)
    emitted: list[PendingItem] = []
    remaining = 0
    for line in queue_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        doi = row["doi"]
        if doi in done:
            continue
        remaining += 1
        if len(emitted) >= n:
            continue
        path = pending_dir / f"{config.slug_for_doi(doi)}.txt"
        path.write_text(
            f"DOI: {doi}\n\nMethod section:\n{row['method_text']}",
            encoding="utf-8",
        )
        emitted.append(PendingItem(doi=doi, prompt_file=path))
    return emitted, remaining


def _validate_result_row(line: str) -> tuple[dict | None, str | None]:
    try:
        obj = json.loads(line)
    except json.JSONDecodeError as exc:
        return None, f"invalid JSON: {exc}"
    if not isinstance(obj, dict) or "doi" not in obj or "procedures" not in obj:
        return None, "missing doi or procedures"
    if not isinstance(obj["doi"], str):
        return None, "doi must be a string"
    procedures = obj["procedures"]
    if not isinstance(procedures, list) or not all(
        isinstance(p, str) for p in procedures
    ):
        return None, "procedures must be list[str]"
    return obj, None


def ingest_batch(
    batch_path: Path | None,
    *,
    results_path: Path | None = None,
    pending_dir: Path | None = None,
    stdin: TextIO | None = None,
    log: TextIO | None = None,
) -> tuple[int, int]:
    """Append a driver's result lines to the results JSONL (append-only).

    ``batch_path`` of ``None`` reads the lines from ``stdin`` instead. Valid
    lines (``{"doi": str, "procedures": [str, ...]}``) get a ``model`` tag if
    missing and are appended; invalid lines are reported to ``log`` and
    skipped. The matching prompt files are removed, and so is the batch file.

    Returns (appended_count, skipped_count).
    """
    results_path = results_path or default_results_path()
    pending_dir = pending_dir or default_pending_dir()
    log = log or sys.stderr
    if batch_path is None:
        text = (stdin or sys.stdin).read()
    else:
        text = batch_path.read_text(encoding="utf-8")

    appended = 0
    skipped = 0
    results_path.parent.mkdir(parents=True, exist_ok=True)
    with results_path.open("a", encoding="utf-8") as out:
        for lineno, raw in enumerate(text.splitlines(), 1):
            line = raw.strip()
            if not line:
                continue
            obj, error = _validate_result_row(line)
            if obj is None:
                print(f"line {lineno}: {error}", file=log)
                skipped += 1
                continue
            row = {**obj, "model": obj.get("model", DEFAULT_SUBAGENT_MODEL_TAG)}
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
            (pending_dir / f"{config.slug_for_doi(obj['doi'])}.txt").unlink(
                missing_ok=True
            )
            appended += 1

    if batch_path is not None:
        batch_path.unlink(missing_ok=True)
    return appended, skipped


def ingest_results(
    results_path: Path | None = None,
    *,
    default_model: str = "procedure-classifier-subagent",
) -> tuple[int, int]:
    """Apply a JSONL result file to state.json.

    Each row must have ``{"doi": str, "procedures": [str, ...]}``. Unknown
    procedure keys (not in the current DSL taxonomy) are dropped silently.

    Returns (applied_count, dropped_count).
    """
    if results_path is None:
        results_path = default_results_path()
    allowed = {p.key for p in discover_procedures()}
    state = state_mod.load()
    applied = 0
    dropped = 0
    with results_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                dropped += 1
                continue
            doi = row.get("doi")
            procedures = row.get("procedures") or []
            if not isinstance(doi, str) or not isinstance(procedures, list):
                dropped += 1
                continue
            filtered = [p for p in procedures if isinstance(p, str) and p in allowed]
            raw_reason = row.get("out_of_scope_reason")
            reason = (
                raw_reason.strip()
                if isinstance(raw_reason, str) and raw_reason.strip()
                else None
            )
            state_mod.upsert_classification(
                state,
                doi,
                filtered,
                row.get("model", default_model),
                out_of_scope_reason=reason,
            )
            applied += 1
    state_mod.save(state)
    return applied, dropped
