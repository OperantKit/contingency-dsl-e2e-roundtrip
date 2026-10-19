"""Integration test: `e2e run --doi <doi>` writes artifacts for a real paper.

Uses an already-extracted paper from corpus/extracted/ that is known to
round-trip cleanly (10.1002/jaba.226). No network / LLM calls.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from contingency_dsl_e2e_roundtrip import artifacts, cli, config, state as state_mod


FIXTURE_DOI = "10.1002/jaba.226"
FIXTURE_SLUG = FIXTURE_DOI.replace("/", "_")


def _fixture_has_extracted() -> bool:
    return (config.extracted_dir() / f"{FIXTURE_SLUG}.txt").is_file()


@pytest.mark.skipif(
    not _fixture_has_extracted(),
    reason=f"corpus/extracted/{FIXTURE_SLUG}.txt not present",
)
def test_run_writes_artifacts_for_real_doi(tmp_path, monkeypatch):
    # Redirect state + generated output to tmp so we don't clobber corpus.
    state_path = tmp_path / "state.json"
    monkeypatch.setattr(state_mod, "STATE_PATH", state_path)

    gen_root = tmp_path / "generated"
    monkeypatch.setattr(artifacts, "GENERATED_ROOT", gen_root)
    monkeypatch.setattr(artifacts, "DSL_DIR", gen_root / "dsl")
    monkeypatch.setattr(artifacts, "COMPILED_DIR", gen_root / "compiled")
    monkeypatch.setattr(artifacts, "DSL2_DIR", gen_root / "dsl2")

    # Pre-seed minimal state so cmd_run picks up the DOI.
    state_path.write_text(
        json.dumps(
            {
                "version": 1,
                "entries": {
                    FIXTURE_DOI: {
                        "procedures": ["operant/atomic"],
                        "classified_with": "test-fixture",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    rc = cli.main(["run", "--doi", FIXTURE_DOI])
    assert rc == 0

    dsl_path = gen_root / "dsl" / f"{FIXTURE_SLUG}.dsl"
    compiled_path = gen_root / "compiled" / f"{FIXTURE_SLUG}.txt"
    dsl2_path = gen_root / "dsl2" / f"{FIXTURE_SLUG}.dsl"

    assert dsl_path.exists(), "AST_1 was not persisted"
    assert compiled_path.exists(), "Compiled procedure text was not persisted"
    assert dsl2_path.exists(), "AST_2 was not persisted"

    # Sanity: DSL text non-empty, compiled paper text non-empty.
    assert dsl_path.read_text(encoding="utf-8").strip()
    assert compiled_path.read_text(encoding="utf-8").strip()
