"""Filesystem locations, resolved at call time.

Nothing here depends on where the package sits inside a larger checkout:

- The DSL conformance tree comes from ``$E2E_CONFORMANCE_ROOT``, else from a
  sibling ``contingency-dsl/conformance`` next to the source checkout.
- Optional paper sources (notes / extracted markdown / PDFs) are only used
  when ``$E2E_PAPER_SOURCES_ROOT`` is set.
- The corpus directory defaults to ``./corpus`` and can be changed with
  :func:`set_corpus_root` (the CLI's ``--corpus`` option).
"""

from __future__ import annotations

import os
from pathlib import Path


ENV_CONFORMANCE_ROOT = "E2E_CONFORMANCE_ROOT"
ENV_PAPER_SOURCES_ROOT = "E2E_PAPER_SOURCES_ROOT"

_HERE = Path(__file__).resolve()
# src/contingency_dsl_e2e_roundtrip/config.py -> package source root
_SOURCE_ROOT: Path = _HERE.parent.parent.parent

_corpus_root: Path = Path("corpus")


def source_root() -> Path | None:
    """The package's source checkout, or None when installed as a wheel."""
    if (_SOURCE_ROOT / "pyproject.toml").is_file():
        return _SOURCE_ROOT
    return None


def conformance_root() -> Path:
    """Resolve the contingency-dsl ``conformance/`` directory.

    Raises FileNotFoundError when neither the environment variable nor the
    sibling checkout provides one.
    """
    env = os.environ.get(ENV_CONFORMANCE_ROOT)
    if env:
        return Path(env).expanduser()
    root = source_root()
    if root is not None:
        sibling = root.parent / "contingency-dsl" / "conformance"
        if sibling.is_dir():
            return sibling
    raise FileNotFoundError(
        "contingency-dsl conformance root not found; set "
        f"{ENV_CONFORMANCE_ROOT} to the path of contingency-dsl/conformance"
    )


def paper_sources_root() -> Path | None:
    """Directory holding ``notes/papers``, ``reference/papers/{extracted,pdf}``."""
    env = os.environ.get(ENV_PAPER_SOURCES_ROOT)
    return Path(env).expanduser() if env else None


def set_corpus_root(path: Path) -> None:
    global _corpus_root
    _corpus_root = Path(path)


def corpus_root() -> Path:
    return _corpus_root.resolve()


def doi_lists_dir() -> Path:
    return corpus_root() / "doi-lists"


def extracted_dir() -> Path:
    return corpus_root() / "extracted"


def generated_root() -> Path:
    return corpus_root() / "generated"


def work_dir() -> Path:
    """Classification work queue, results, and per-DOI prompt files."""
    return corpus_root() / "work"


def state_path() -> Path:
    return corpus_root() / "state.json"


def agent_dir() -> Path:
    """Where generated subagent definitions are written (inside the package)."""
    root = source_root() or Path.cwd()
    return root / ".claude" / "agents"


def slug_for_doi(doi: str) -> str:
    """Filesystem-safe slug used across paper sources and corpus/."""
    return doi.replace("/", "_")
