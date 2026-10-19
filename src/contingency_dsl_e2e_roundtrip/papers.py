"""Index over the optional paper-source directory, keyed by DOI.

Paper sources are consulted only when ``$E2E_PAPER_SOURCES_ROOT`` points at
a directory laid out as::

    <root>/notes/papers/*.md               (notes with a ``doi:`` frontmatter)
    <root>/reference/papers/extracted/*.md (full-paper markdown)
    <root>/reference/papers/pdf/*.pdf      (raw PDFs)

Without it, every DOI resolves to no assets and extraction relies on the
``corpus/extracted/`` cache alone.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .config import paper_sources_root, slug_for_doi


_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_DOI_RE = re.compile(r'^\s*doi:\s*"?([^"\n]+?)"?\s*$', re.MULTILINE)


@dataclass(frozen=True)
class Paper:
    doi: str
    slug: str
    note_path: Path | None
    extracted_md_path: Path | None
    pdf_path: Path | None


@dataclass(frozen=True)
class _SourceDirs:
    notes: Path
    extracted: Path
    pdf: Path


def _source_dirs() -> _SourceDirs | None:
    root = paper_sources_root()
    if root is None:
        return None
    return _SourceDirs(
        notes=root / "notes" / "papers",
        extracted=root / "reference" / "papers" / "extracted",
        pdf=root / "reference" / "papers" / "pdf",
    )


def _read_doi_from_note(path: Path) -> str | None:
    try:
        head = path.read_text(encoding="utf-8", errors="replace")[:2048]
    except OSError:
        return None
    match = _FRONTMATTER_RE.match(head)
    if not match:
        return None
    fm = match.group(1)
    doi_match = _DOI_RE.search(fm)
    return doi_match.group(1).strip() if doi_match else None


@lru_cache(maxsize=4)
def _note_index(notes_dir: Path) -> dict[str, Path]:
    """Map DOI -> first note file declaring it."""
    index: dict[str, Path] = {}
    if not notes_dir.is_dir():
        return index
    for path in sorted(notes_dir.glob("*.md")):
        doi = _read_doi_from_note(path)
        if doi and doi not in index:
            index[doi] = path
    return index


def resolve(doi: str) -> Paper:
    """Resolve a DOI to all known assets. Missing assets are represented as None."""
    slug = slug_for_doi(doi)
    dirs = _source_dirs()
    if dirs is None:
        return Paper(doi=doi, slug=slug, note_path=None,
                     extracted_md_path=None, pdf_path=None)
    note = _note_index(dirs.notes).get(doi)
    extracted = dirs.extracted / f"{slug}.md"
    pdf = dirs.pdf / f"{slug}.pdf"
    return Paper(
        doi=doi,
        slug=slug,
        note_path=note,
        extracted_md_path=extracted if extracted.is_file() else None,
        pdf_path=pdf if pdf.is_file() else None,
    )


def all_dois_with_any_asset() -> list[str]:
    """Every DOI that has at least one of: note, extracted md, or PDF."""
    dirs = _source_dirs()
    if dirs is None:
        return []
    seen: set[str] = set(_note_index(dirs.notes).keys())
    for path in dirs.extracted.glob("*.md"):
        seen.add(path.stem.replace("_", "/", 1))
    for path in dirs.pdf.glob("*.pdf"):
        seen.add(path.stem.replace("_", "/", 1))
    return sorted(seen)
