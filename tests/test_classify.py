"""Unit tests for classifier response parsing and the out-of-scope schema.

Network-bound paths (Anthropic SDK / claude CLI) are not exercised here; we
test the pure parsing surface only.
"""

from __future__ import annotations

from contingency_dsl_e2e_roundtrip.classify import (
    KEY_DEFINITIONS,
    ClassificationResult,
    _parse_response,
    _system_prompt,
)


ALLOWED = {"operant/atomic", "operant/compound", "operant/stateful/adjusting"}


def test_parse_response_returns_procedures_and_no_reason():
    raw = '{"procedures": ["operant/atomic"], "out_of_scope_reason": null}'
    procs, reason = _parse_response(raw, allowed=ALLOWED)
    assert procs == ["operant/atomic"]
    assert reason is None


def test_parse_response_returns_reason_when_out_of_scope():
    raw = (
        '{"procedures": [], '
        '"out_of_scope_reason": "meta-analysis: model fitting on prior data only"}'
    )
    procs, reason = _parse_response(raw, allowed=ALLOWED)
    assert procs == []
    assert reason == "meta-analysis: model fitting on prior data only"


def test_parse_response_filters_unknown_procedures():
    raw = '{"procedures": ["operant/atomic", "bogus/key"], "out_of_scope_reason": null}'
    procs, reason = _parse_response(raw, allowed=ALLOWED)
    assert procs == ["operant/atomic"]
    assert reason is None


def test_parse_response_handles_legacy_payload_without_reason_key():
    """Older classifier responses had only `procedures`. Treat as in-scope."""
    raw = '{"procedures": ["operant/compound"]}'
    procs, reason = _parse_response(raw, allowed=ALLOWED)
    assert procs == ["operant/compound"]
    assert reason is None


def test_parse_response_treats_empty_string_reason_as_in_scope():
    raw = '{"procedures": ["operant/atomic"], "out_of_scope_reason": ""}'
    procs, reason = _parse_response(raw, allowed=ALLOWED)
    assert procs == ["operant/atomic"]
    assert reason is None


def test_parse_response_strips_leading_prose():
    raw = (
        "Here is the classification:\n"
        '{"procedures": [], "out_of_scope_reason": "human survey"}\n'
        "End of response."
    )
    procs, reason = _parse_response(raw, allowed=ALLOWED)
    assert procs == []
    assert reason == "human survey"


def test_parse_response_returns_empty_on_malformed_json():
    procs, reason = _parse_response("not json at all", allowed=ALLOWED)
    assert procs == []
    assert reason is None


def test_classification_result_default_reason_is_none():
    result = ClassificationResult(
        doi="10.1/x", procedures=("operant/atomic",), model="haiku", raw="{}"
    )
    assert result.out_of_scope_reason is None


def test_classification_result_carries_reason():
    result = ClassificationResult(
        doi="10.1/x",
        procedures=(),
        model="haiku",
        raw="{}",
        out_of_scope_reason="meta-analysis",
    )
    assert result.out_of_scope_reason == "meta-analysis"
    assert result.procedures == ()


def test_prompt_attaches_definition_to_defined_keys_only():
    prompt = _system_prompt(["operant/atomic", "operant/stateful/adjusting"])
    lines = prompt.splitlines()
    atomic = next(line for line in lines if line.startswith("- operant/atomic"))
    assert atomic == f"- operant/atomic: {KEY_DEFINITIONS['operant/atomic']}"
    assert "- operant/stateful/adjusting" in lines


def test_prompt_omits_definitions_for_keys_not_offered():
    prompt = _system_prompt(["operant/stateful/adjusting"])
    assert KEY_DEFINITIONS["operant/atomic"] not in prompt


def test_definitions_cover_the_low_agreement_keys():
    assert set(KEY_DEFINITIONS) == {
        "operant/atomic",
        "operant/compound",
        "operant/timeout",
        "operant/program",
        "experiment/phase",
        "experiment/shaping",
        "annotations/procedure-stimulus",
        "annotations/procedure-temporal",
        "annotations/procedure-trial-structure",
        "annotations/measurement",
    }
    assert all(text.strip() for text in KEY_DEFINITIONS.values())
