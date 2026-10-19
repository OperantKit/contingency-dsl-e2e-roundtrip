"""Tests for extraction-quality detection (space-loss heuristic).

Old or oddly-encoded PDFs make pypdf emit text with collapsed word boundaries
(``IndianaUniversity``, ``VI30-second``). The harness needs to detect these
and prefer a higher-fidelity backend (pymupdf) when available.
"""

from __future__ import annotations

from contingency_dsl_e2e_roundtrip.extract import (
    _looks_space_deficient,
)


GOOD_TEXT = (
    "The procedure was similar to that of Experiment 1. Subjects pressed a "
    "lever for food on a variable-interval 30-s schedule. Sessions ran for "
    "60 minutes daily. The chamber was illuminated by a houselight located "
    "above the lever, and a 0.05-second pulse of 60-cycle current was "
    "delivered through the grid floor when the schedule timed out."
)

# Synthetic: mimics the title block and opening lines of an old journal PDF
# whose extraction lost the word boundaries. Not taken from any paper.
BAD_TEXT_OLD_PDF = (
    "TIMEOUTDURATIONIN FIXED-RATIO AVOIDANCESCHEDULES1 "
    "AUTHORA.EXAMPLEAND AUTHORB.SAMPLE ExampleStateUniversity "
    "Ratioschedulesforresponse-producedpostponementofanoxiousstimulus"
    "arerarelyreportedwithtoneandevenmorerarelywithlight.Atimeoutis "
    "(2)oftentakentobetoo'weak'aconsequencetomaintainstableresponding"
)


def test_good_text_is_not_flagged():
    assert _looks_space_deficient(GOOD_TEXT) is False


def test_extracted_old_pdf_is_flagged():
    assert _looks_space_deficient(BAD_TEXT_OLD_PDF) is True


def test_short_text_is_not_flagged():
    """Heuristic should only fire on enough material to be confident."""
    assert _looks_space_deficient("FR 10") is False
    assert _looks_space_deficient("") is False


def test_table_heavy_text_is_not_flagged():
    """Long mathematical / tabular tokens by themselves should not trip the heuristic."""
    text = (
        "Model fits were obtained using ordinary least squares. "
        "AICc and BIC values were computed across all conditions. "
        "Table 1 reports the residual sum of squares for each subject. "
        "The 95-percent-confidence-interval bounds were tight in every cell."
    )
    assert _looks_space_deficient(text) is False


def test_moderate_space_loss_is_flagged():
    """Partial corruption with several 15-19 char glued tokens must trip the heuristic."""
    text = (
        "The procedurewasidentical to that of Experiment 1. Subjects pressed "
        "alever for foodonafixed ratio of ten responses per reinforcer. "
        "Sessionsranfor sixtyminutes daily and theratswerereturnedtotheir "
        "homecagesbetween sessions. Theapparatuswas a standard operantchamber "
        "withahouselight aboveapanellever. Datawerecollected on a paper tape."
    )
    assert _looks_space_deficient(text) is True


def test_runs_of_concatenated_words_trigger_heuristic():
    """A real Method section with many word-pair concatenations is bad."""
    text = (
        "Theratswerefirsttrainedonacontinuousreinforcementscheduleuntiltheyreliablypressedthe"
        "leverforfoodaftertenminutesofsessiondurationtheschedulewassteppedupto"
        "fixedratiotenwhichremainedinforcefor20sessionsthenwemovedtoavariableinterval"
    )
    assert _looks_space_deficient(text) is True
