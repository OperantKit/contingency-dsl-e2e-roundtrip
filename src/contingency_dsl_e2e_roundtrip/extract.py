"""Procedure plaintext extraction with a cache-first fallback chain.

Fallback order (resolved by the sibling ``papers`` module):

    1. ``corpus/extracted/<slug>.txt`` — this project's cache (gitignored).
    2. Full-paper markdown (resolved by ``Paper.extracted_md_path``).
    3. Raw PDF (resolved by ``Paper.pdf_path``) parsed via pypdf.
    4. Paper note (resolved by ``Paper.note_path``) — Method section only.

Source paths beyond the cache are resolved at runtime by ``papers.resolve``;
this module does not hard-code any cross-package filesystem layout.

Every successful extraction writes back to (1) so subsequent runs are cheap.
"""

from __future__ import annotations

import re
from pathlib import Path

from .config import extracted_dir
from .papers import Paper, resolve


_METHOD_HEADINGS = (
    r"general\s+method",
    r"\bmethod(s)?\b",
    r"procedure",
    r"方法",
    r"手続き",
)
_STOP_HEADINGS = (
    r"general\s+discussion",
    r"\bresults?\b",
    r"\bdiscussion\b",
    r"\backnowledg(e)?ments?\b",
    r"\breferences?\b",
    r"結果",
    r"考察",
    r"引用",
    r"文献",
)
_HEADING_RE = re.compile(
    r"^#{1,6}\s*(?:[A-Z0-9IVX]+\.?\s+)?("
    + "|".join(_METHOD_HEADINGS)
    + r")\b",
    re.IGNORECASE | re.MULTILINE,
)
_STOP_RE = re.compile(
    r"^#{1,6}\s*(?:[A-Z0-9IVX]+\.?\s+)?("
    + "|".join(_STOP_HEADINGS)
    + r")",
    re.IGNORECASE | re.MULTILINE,
)

# Plain-text (non-markdown) headings: bare word on its own line, optionally
# preceded by a roman numeral / capital section marker. This catches pypdf
# output where the original heading style (bold, larger font, centred) was
# lost but the isolated line remains.
_PLAIN_HEADING_RE = re.compile(
    r"^[\s#>*•·\-]*(?:[A-Z0-9IVX]+[.\)]?\s+)?("
    + "|".join(_METHOD_HEADINGS)
    + r")\s*\.?\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_PLAIN_STOP_RE = re.compile(
    r"^[\s#>*•·\-]*(?:[A-Z0-9IVX]+[.\)]?\s+)?("
    + "|".join(_STOP_HEADINGS)
    + r")\s*\.?\s*$",
    re.IGNORECASE | re.MULTILINE,
)


_LIGATURES = {
    "\ufb00": "ff",
    "\ufb01": "fi",
    "\ufb02": "fl",
    "\ufb03": "ffi",
    "\ufb04": "ffl",
    "\ufb05": "st",
    "\ufb06": "st",
}


def _normalize_pdf_text(text: str) -> str:
    """Clean up typical pypdf extraction artifacts.

    1. Replace Unicode typographic ligatures (ﬁ, ﬂ, ﬃ, ...) with ASCII.
    2. Rejoin words split by line-ending hyphens: "persis-\ntence" -> "persistence".
    3. Collapse a single newline inside a paragraph into a space, preserving
       blank lines (paragraph separators).
    4. Normalize smart punctuation spacing artifacts like "de ﬁne" -> "define"
       when a spurious space was inserted before a ligature.
    """
    for src, dst in _LIGATURES.items():
        text = text.replace(src, dst)

    # Step 4 (pre): pypdf sometimes inserts a space before the (now-ASCII)
    # former-ligature letter pair. e.g. "de fi ne" or "de fine".
    # Reglue conservatively: lowercase+space+(fi|fl|ff)+lowercase -> no space.
    text = re.sub(r"(?<=[a-z])\s+(fi|fl|ff|ffi|ffl)(?=[a-z])", r"\1", text)

    # Step 2: line-ending hyphenation. Only when the hyphen joins two
    # alphabetic fragments (skip real hyphenated compounds ending a paragraph).
    text = re.sub(r"([A-Za-z])-\n([a-z])", r"\1\2", text)

    # Step 3: single intra-paragraph newlines -> space. Preserve \n\n+.
    # We use a sentinel to protect double newlines first.
    text = text.replace("\n\n", "\x00PARA\x00")
    text = re.sub(r"(?<!\n)\n(?!\n)", " ", text)
    text = text.replace("\x00PARA\x00", "\n\n")

    # Step 5: collapse runs of spaces the above can introduce.
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text


_EXPERIMENT_HEADING_RE = re.compile(
    r"^[\s#>*•·\-]*(?:EXPERIMENT|Experiment|Study|実験|研究)[\s\t\u00A0\u3000]*\d+[A-Za-z]*"
    r"(?:\.|:[^\n\r]*)?\s*$",
    re.MULTILINE,
)
_REFERENCES_RE = re.compile(
    r"^[\s#>*•·\-]*(?:REFERENCES?|References?|参考文献|文献)\s*$",
    re.MULTILINE,
)


def _slice_method_section(text: str) -> str | None:
    """Return the text from a Method-like heading up to the next stopping
    heading. Tries markdown-style headings first, then plain-text (bare-line)
    headings.

    Multi-experiment aware: when the text contains two or more
    ``Experiment N`` headings, the stopping boundary is relaxed to only
    stop at References, so each experiment's Results/Discussion is retained
    (otherwise we would truncate at Experiment 1's Results and lose
    Experiments 2+).
    """
    experiment_count = len(_EXPERIMENT_HEADING_RE.findall(text))
    multi_experiment = experiment_count >= 2

    for heading_re, stop_re in (
        (_HEADING_RE, _STOP_RE),
        (_PLAIN_HEADING_RE, _PLAIN_STOP_RE),
    ):
        match = heading_re.search(text)
        if not match:
            continue
        start = match.start()
        tail = text[match.end() :]
        if multi_experiment:
            stop = _REFERENCES_RE.search(tail)
        else:
            stop = stop_re.search(tail)
        end = match.end() + stop.start() if stop else len(text)
        sliced = text[start:end].strip()
        if sliced:
            return sliced
    return None


def _extract_from_markdown(path: Path) -> str | None:
    try:
        body = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    return _slice_method_section(body)


def _read_pdf_pymupdf(path: Path) -> str | None:
    try:
        import pymupdf  # type: ignore[import-not-found]
    except ImportError:
        return None
    try:
        with pymupdf.open(str(path)) as doc:
            return "\n".join(page.get_text("text") or "" for page in doc)
    except Exception:
        return None


def _read_pdf_pypdf(path: Path) -> str | None:
    try:
        from pypdf import PdfReader
    except ImportError:
        return None

    import logging

    # pypdf logs MediaBox duplicates and dangling refs at WARNING; silence them
    # for the duration of this parse so the queue-prepare run stays readable.
    pypdf_logger = logging.getLogger("pypdf")
    prior_level = pypdf_logger.level
    pypdf_logger.setLevel(logging.ERROR)
    try:
        reader = PdfReader(str(path))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception:
        return None
    finally:
        pypdf_logger.setLevel(prior_level)


def _finalize_pdf_text(text: str) -> str | None:
    sliced = _slice_method_section(text)
    final = sliced if sliced else text.strip()
    if not final:
        return None
    return _normalize_pdf_text(final)


def _extract_from_pdf(path: Path) -> str | None:
    """Extract Method-section text from a PDF.

    Tries pymupdf first because it preserves word boundaries on older or
    oddly-encoded PDFs that pypdf collapses (e.g. ``IndianaUniversity``,
    ``VI30-second``). Falls back to pypdf when pymupdf is unavailable or
    yields suspiciously space-deficient output.
    """
    raw = _read_pdf_pymupdf(path)
    if raw is not None:
        finalized = _finalize_pdf_text(raw)
        if finalized is not None and not _looks_space_deficient(finalized):
            return finalized
        # pymupdf produced nothing usable: try pypdf as a fallback.
        primary = finalized
    else:
        primary = None

    raw = _read_pdf_pypdf(path)
    if raw is not None:
        fallback = _finalize_pdf_text(raw)
        if fallback is not None:
            # Prefer whichever backend produced cleaner text.
            if primary is None:
                return fallback
            if _looks_space_deficient(primary) and not _looks_space_deficient(fallback):
                return fallback
            return primary
    return primary


def _extract_from_note(paper: Paper) -> str | None:
    if paper.note_path is None:
        return None
    try:
        body = paper.note_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    section = _slice_method_section(body)
    if not section:
        return None
    stripped = re.sub(r"^#{1,6}\s+\S.*$", "", section, count=1, flags=re.MULTILINE).strip()
    if not stripped:
        return None
    # Reject empty Method stubs — paper-note templates often
    # contain only section headings ("### 被験体\n### 手続き\n### 従属変数")
    # with no actual content. An extraction with <= 200 non-heading
    # characters (after stripping all `### ` lines) is assumed to be a stub.
    content_only = re.sub(r"(?m)^#{1,6}[^\n]*$", "", stripped).strip()
    if len(content_only) < 200:
        return None
    return stripped


def _cache_path(slug: str) -> Path:
    return extracted_dir() / f"{slug}.txt"


def ensure_extracted(doi: str, *, force: bool = False) -> tuple[Path, str] | None:
    """Ensure `<slug>.txt` exists in the extraction cache.

    Returns (path, text) when extraction succeeded (cached or fresh),
    or None if no source could produce a Method section.
    """
    paper = resolve(doi)
    cache = _cache_path(paper.slug)

    if cache.is_file() and not force:
        raw = cache.read_text(encoding="utf-8", errors="replace")
        # Reject stub caches (template scaffolds from paper-note sources with
        # no actual content). These caches were written before stub
        # detection existed; treat them as missing and re-extract from source.
        if _is_stub(raw):
            try:
                cache.unlink()
            except OSError:
                pass
        else:
            # Legacy caches may hold the full paper with ligatures and no
            # Method slicing. Detect that by looking for untouched ligatures,
            # re-slice and re-normalize, then rewrite so subsequent runs
            # converge.
            needs_rewrite = any(ch in raw for ch in "\ufb00\ufb01\ufb02\ufb03\ufb04")
            if needs_rewrite:
                sliced = _slice_method_section(raw) or raw
                normalized = _normalize_pdf_text(sliced)
                cache.parent.mkdir(parents=True, exist_ok=True)
                cache.write_text(normalized, encoding="utf-8")
                return cache, normalized
            # Caches written by an older pypdf-only extractor may be
            # space-deficient (word boundaries collapsed). Invalidate when a
            # higher-fidelity backend is now available so re-extraction can
            # rescue these papers.
            if _looks_space_deficient(raw):
                try:
                    cache.unlink()
                except OSError:
                    pass
            else:
                return cache, raw

    text: str | None = None
    if paper.extracted_md_path is not None:
        text = _extract_from_markdown(paper.extracted_md_path)
        if text is not None and _is_stub(text):
            text = None
    if text is None and paper.pdf_path is not None:
        text = _extract_from_pdf(paper.pdf_path)
        if text is not None and _is_stub(text):
            text = None
    if text is None:
        text = _extract_from_note(paper)

    if text is None or not text.strip():
        return None

    # Avoid cache-thrash: a freshly extracted result that is still
    # space-deficient would just be re-detected and re-deleted on the next
    # call. Return the text without caching so callers see best-effort
    # output but the cache stays clean for future re-extraction attempts.
    if _looks_space_deficient(text):
        return cache, text

    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(text, encoding="utf-8")
    return cache, text


_LONG_RUN_RE = re.compile(r"[A-Za-z]{15,}")


def _looks_space_deficient(text: str) -> bool:
    """Heuristic: True when PDF extraction collapsed word boundaries.

    Two complementary signals must both fire so that legitimate long
    technical tokens, math notation, or short snippets do not trip the
    heuristic:

    1. Average inter-space token length is implausibly high (English prose
       averages ~5 characters per token; >8 indicates many missing spaces).
    2. The text contains at least one alphabetic run of 15+ characters,
       which is rare in genuine English (most legitimate long tokens are
       hyphenated or separated by punctuation).
    """
    sample = text.strip()
    if len(sample) < 200:
        return False
    tokens = sample.split()
    if not tokens:
        return False
    avg_token_len = sum(len(t) for t in tokens) / len(tokens)
    has_long_run = bool(_LONG_RUN_RE.search(sample))
    return avg_token_len > 8 and has_long_run


def _is_stub(text: str) -> bool:
    """True when a candidate Method section is an empty template.

    Strips heading lines and blank lines; rejects anything that leaves
    fewer than 200 characters of actual prose.
    """
    content_only = re.sub(r"(?m)^#{1,6}[^\n]*$", "", text).strip()
    return len(content_only) < 200
