"""LLM-based procedure classifier with two backends.

Backends (auto-selected unless forced by ``E2E_CLASSIFIER_BACKEND`` env var):

1. ``anthropic`` — Direct Anthropic SDK call. Requires ``ANTHROPIC_API_KEY``
   and the ``[llm]`` extra installed.
2. ``claude-cli`` — Subprocess to the ``claude`` CLI (Claude Code). Uses the
   user's existing CLI session, so no API key is needed. Slower per call
   because each invocation rebuilds the session context cache.
3. ``codex-cli`` — Subprocess to the OpenAI ``codex`` CLI (``codex exec``).
   Never auto-selected; it exists so a model from a different vendor can act
   as a second rater for inter-rater agreement (``e2e second-rate``).

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
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .procedures import ProcedureType, discover_procedures


DEFAULT_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_CLI_MODEL = "haiku"
DEFAULT_CODEX_MODEL = "gpt-6.1-sol"
_CLI_TIMEOUT_S = 180
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


# Keys whose bare names were read in more than one way by different raters.
# Each definition states what the key's conformance file covers.
KEY_DEFINITIONS: dict[str, str] = {
    "operant/atomic": (
        "the paper runs at least one simple schedule on its own (FR, VR, RR, FI, "
        "VI, RI, FT, VT, RT, CRF, or EXT) as the contingency of a condition or "
        "phase. Do not add it only because the components inside a compound "
        "schedule are simple schedules."
    ),
    "operant/compound": (
        "two or more schedules are combined into one arrangement: concurrent, "
        "chained, tandem, alternative, conjunctive, multiple, or mixed schedules, "
        "or punishment superimposed on a reinforcement baseline (including "
        "changeover delays/ratios and blackouts between components). A compound "
        "stimulus (several stimulus elements presented together) is not a "
        "compound schedule."
    ),
    "operant/timeout": (
        "a timeout period follows a response or event, during which the schedule "
        "is suspended and responses have no programmed consequence (resetting or "
        "non-resetting). A blackout between multiple-schedule components or an "
        "ordinary intertrial interval alone is not a timeout."
    ),
    "operant/program": (
        "program-level declarations shared by several schedules are needed: a "
        "limited hold applied to every schedule, or the same named schedule reused "
        "across several conditions (e.g., a baseline reinstated after a probe). "
        "Do not add it merely because the paper has a schedule."
    ),
    "experiment/phase": (
        "the paper runs two or more successive conditions (e.g., baseline, "
        "treatment, reversal, extinction after acquisition), each lasting a set "
        "number of sessions or until a stability criterion is met. A single "
        "condition does not qualify."
    ),
    "experiment/shaping": (
        "the target response is established by shaping, i.e., reinforcing "
        "successive approximations (by experimenter judgment, percentile "
        "schedules, or pre-set stages). Magazine training or autoshaping alone "
        "is not shaping."
    ),
    "annotations/procedure-stimulus": (
        "the Method identifies the stimuli of the procedure: the reinforcer or "
        "punisher (e.g., food pellet, sucrose, token with its backup reinforcer), "
        "discriminative stimuli for each component, brief stimuli in second-order "
        "schedules, or stimulus classes with trained and tested relations "
        "(stimulus equivalence)."
    ),
    "annotations/procedure-temporal": (
        "the Method reports timing infrastructure: the time resolution or unit of "
        "the controlling program, a warm-up period before the session, or the "
        "algorithm generating variable schedule values (e.g., Fleshler & Hoffman, "
        "1962; arithmetic progression). Do not add it merely because schedule "
        "values are given in seconds."
    ),
    "annotations/procedure-trial-structure": (
        "one session mixes trial types of a named design: peak procedure "
        "(reinforced fixed-interval trials interspersed with longer unreinforced "
        "probe trials), reinstatement (response-independent reinforcers delivered "
        "during extinction), or temporal bisection (short and long anchor "
        "durations with intermediate probes). Do not add it for ordinary "
        "discrete-trial procedures."
    ),
    "annotations/measurement": (
        "the Method specifies how sessions and phases are measured or ended: "
        "session-end rules (time and/or reinforcer count), stability or "
        "phase-change criteria, baseline/operant-level sessions before training, "
        "dependent measures beyond overall response rate (e.g., bouts, IRTs, "
        "log-survivor plots, changeovers), event logging resolution, exclusion of "
        "a warm-up from analysis, or the trial/block structure and probe policy "
        "of a session."
    ),
}


def _key_line(key: str) -> str:
    definition = KEY_DEFINITIONS.get(key)
    return f"- {key}: {definition}" if definition else f"- {key}"


def _system_prompt(keys: list[str]) -> str:
    bullet_list = "\n".join(_key_line(k) for k in keys)
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
        "Taxonomy keys (a key followed by a definition applies only when the "
        "definition holds):\n" + bullet_list
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
    backend: str | None = None,
) -> ClassificationResult:
    """Classify one Method section.

    ``backend`` forces a backend; otherwise ``_pick_backend`` decides.
    """
    backend = backend or _pick_backend()
    procs = procedures or discover_procedures()
    keys = [p.key for p in procs]
    truncated = procedure_text[:_MAX_INPUT_CHARS]

    if backend == "anthropic":
        return _classify_anthropic(doi, truncated, keys, model or DEFAULT_MODEL)
    if backend == "claude-cli":
        return _classify_cli(doi, truncated, keys, model or DEFAULT_CLI_MODEL)
    if backend == "codex-cli":
        return _classify_codex(doi, truncated, keys, model or DEFAULT_CODEX_MODEL)
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

    schema = _output_schema(keys)
    prompt = _cli_prompt(doi, text, keys)
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
        timeout=_CLI_TIMEOUT_S,
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


def _classify_codex(
    doi: str, text: str, keys: list[str], model: str
) -> ClassificationResult:
    """Run ``codex exec`` read-only in a scratch directory with the same
    prompt and JSON schema as the ``claude-cli`` backend."""
    if not shutil.which("codex"):
        raise ClassifierUnavailable("`codex` CLI not found on PATH")

    with tempfile.TemporaryDirectory(prefix="e2e-codex-") as tmp:
        workdir = Path(tmp)
        schema_path = workdir / "schema.json"
        out_path = workdir / "out.json"
        schema_path.write_text(json.dumps(_output_schema(keys)), encoding="utf-8")
        cmd = [
            "codex",
            "exec",
            "--skip-git-repo-check",
            "--ephemeral",
            "-s",
            "read-only",
            "-C",
            str(workdir),
            "-m",
            model,
            "--output-schema",
            str(schema_path),
            "-o",
            str(out_path),
            "-",
        ]
        proc = subprocess.run(
            cmd,
            input=_cli_prompt(doi, text, keys),
            capture_output=True,
            text=True,
            timeout=_CLI_TIMEOUT_S,
            cwd=str(workdir),
        )
        if proc.returncode != 0:
            raise RuntimeError(f"codex CLI exited {proc.returncode}: {proc.stderr[:300]}")
        if not out_path.is_file():
            raise RuntimeError("codex CLI wrote no output file")
        raw = out_path.read_text(encoding="utf-8")

    parsed, reason = _parse_response(raw, allowed=set(keys))
    return ClassificationResult(
        doi=doi,
        procedures=tuple(parsed),
        model=model,
        raw=raw,
        out_of_scope_reason=reason,
    )


def _cli_prompt(doi: str, text: str, keys: list[str]) -> str:
    return _system_prompt(keys) + f"\n\nDOI: {doi}\n\nMethod section:\n{text}"


def _output_schema(keys: list[str]) -> dict[str, object]:
    return {
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
