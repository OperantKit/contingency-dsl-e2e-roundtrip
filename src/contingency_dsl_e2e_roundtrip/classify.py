"""LLM-based procedure classifier with two backends.

Backends (auto-selected unless forced by ``E2E_CLASSIFIER_BACKEND`` env var):

1. ``anthropic`` — Direct Anthropic SDK call. Requires ``ANTHROPIC_API_KEY``
   and the ``[llm]`` extra installed.
2. ``claude-cli`` — Subprocess to the ``claude`` CLI (Claude Code). Uses the
   user's existing CLI session, so no API key is needed. Slower per call
   because each invocation rebuilds the session context cache.

Auto-selection order:
    ANTHROPIC_API_KEY set  -> ``anthropic``
    ``claude`` on PATH      -> ``claude-cli``
    neither                 -> ClassifierUnavailable

The classifier itself is side-effect-free with respect to filesystem.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass

from .procedures import ProcedureType, discover_procedures


DEFAULT_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_CLI_MODEL = "haiku"
_MAX_INPUT_CHARS = 18_000


@dataclass(frozen=True)
class ClassificationResult:
    doi: str
    procedures: tuple[str, ...]
    model: str
    raw: str
    out_of_scope_reason: str | None = None


class ClassifierUnavailable(RuntimeError):
    """Raised when no backend is usable."""


def _system_prompt(keys: list[str]) -> str:
    bullet_list = "\n".join(f"- {k}" for k in keys)
    return (
        "You classify behavior-analysis Method sections against a fixed taxonomy "
        "derived from the contingency-dsl conformance corpus.\n\n"
        "Return ONLY a JSON object of the form\n"
        '  {"procedures": [...], "out_of_scope_reason": null | "<short reason>"}\n'
        "where each entry of `procedures` is one of the taxonomy keys listed "
        "below.\n\n"
        "Set `out_of_scope_reason` to a short string (and `procedures` to []) "
        "when the paper does NOT report an experimental procedure that the "
        "contingency-dsl can represent. Use this for, but not limited to:\n"
        "- meta-analysis or re-analysis of prior data (no new procedure)\n"
        "- pure mathematical / quantitative model fitting with no experiment\n"
        "- hypothetical-choice or delay-discounting questionnaires where no "
        "reinforcer is actually delivered (subjects only state preferences)\n"
        "- human survey or interview with no operant/respondent contingency "
        "in effect\n"
        "- review / theoretical paper with no Method section of its own\n"
        "- simulation-only or computational model paper\n"
        "A paper that mentions schedules only as inclusion criteria for "
        "selecting other people's datasets is out of scope, not in-scope "
        "under the cited schedules.\n"
        "Otherwise leave `out_of_scope_reason` as null and populate "
        "`procedures` with every matching key.\n\n"
        "Taxonomy keys:\n" + bullet_list
    )


def _pick_backend() -> str:
    forced = os.environ.get("E2E_CLASSIFIER_BACKEND")
    if forced:
        return forced
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    if shutil.which("claude"):
        return "claude-cli"
    raise ClassifierUnavailable(
        "no classifier backend available: set ANTHROPIC_API_KEY or install the `claude` CLI"
    )


def classify(
    doi: str,
    procedure_text: str,
    *,
    model: str | None = None,
    procedures: list[ProcedureType] | None = None,
) -> ClassificationResult:
    backend = _pick_backend()
    procs = procedures or discover_procedures()
    keys = [p.key for p in procs]
    truncated = procedure_text[:_MAX_INPUT_CHARS]

    if backend == "anthropic":
        return _classify_anthropic(doi, truncated, keys, model or DEFAULT_MODEL)
    if backend == "claude-cli":
        return _classify_cli(doi, truncated, keys, model or DEFAULT_CLI_MODEL)
    raise ClassifierUnavailable(f"unknown backend: {backend}")


def _classify_anthropic(
    doi: str, text: str, keys: list[str], model: str
) -> ClassificationResult:
    try:
        import anthropic
    except ImportError as exc:
        raise ClassifierUnavailable(
            "anthropic SDK not installed. Install with: pip install -e '.[llm]'"
        ) from exc

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ClassifierUnavailable("ANTHROPIC_API_KEY is not set")

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model=model,
        max_tokens=512,
        system=[
            {
                "type": "text",
                "text": _system_prompt(keys),
                "cache_control": {"type": "ephemeral"},
            },
        ],
        messages=[
            {"role": "user", "content": f"DOI: {doi}\n\nMethod section:\n{text}"},
        ],
    )
    raw = "".join(block.text for block in message.content if block.type == "text")
    procs, reason = _parse_response(raw, allowed=set(keys))
    return ClassificationResult(
        doi=doi,
        procedures=tuple(procs),
        model=model,
        raw=raw,
        out_of_scope_reason=reason,
    )


def _classify_cli(
    doi: str, text: str, keys: list[str], model: str
) -> ClassificationResult:
    if not shutil.which("claude"):
        raise ClassifierUnavailable("`claude` CLI not found on PATH")

    schema = {
        "type": "object",
        "properties": {
            "procedures": {
                "type": "array",
                "items": {"type": "string", "enum": keys},
            },
            "out_of_scope_reason": {
                "type": ["string", "null"],
            },
        },
        "required": ["procedures", "out_of_scope_reason"],
        "additionalProperties": False,
    }
    prompt = (
        _system_prompt(keys)
        + f"\n\nDOI: {doi}\n\nMethod section:\n{text}"
    )
    cmd = [
        "claude",
        "-p",
        "--model",
        model,
        "--output-format",
        "json",
        "--json-schema",
        json.dumps(schema, ensure_ascii=False),
        "--no-session-persistence",
    ]
    proc = subprocess.run(
        cmd,
        input=prompt,
        capture_output=True,
        text=True,
        timeout=180,
        cwd="/tmp",
    )
    if proc.returncode != 0:
        raise RuntimeError(f"claude CLI exited {proc.returncode}: {proc.stderr[:300]}")

    try:
        envelope = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"claude CLI returned non-JSON: {proc.stdout[:300]}") from exc

    structured = envelope.get("structured_output")
    allowed = set(keys)
    if isinstance(structured, dict):
        parsed = [c for c in structured.get("procedures", []) if c in allowed]
        reason = _normalize_reason(structured.get("out_of_scope_reason"))
    else:
        result_text = envelope.get("result", "") or ""
        parsed, reason = _parse_response(result_text, allowed=allowed)

    return ClassificationResult(
        doi=doi,
        procedures=tuple(parsed),
        model=model,
        raw=proc.stdout,
        out_of_scope_reason=reason,
    )


def _parse_response(
    raw: str, *, allowed: set[str]
) -> tuple[list[str], str | None]:
    """Extract `(procedures, out_of_scope_reason)` from a classifier reply.

    Tolerates leading/trailing prose around a single JSON object and missing
    keys (legacy responses without ``out_of_scope_reason`` are treated as
    in-scope).
    """
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1:
        return [], None
    try:
        payload = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return [], None
    candidates = payload.get("procedures", [])
    procs = [c for c in candidates if isinstance(c, str) and c in allowed]
    reason = _normalize_reason(payload.get("out_of_scope_reason"))
    return procs, reason


def _normalize_reason(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None
