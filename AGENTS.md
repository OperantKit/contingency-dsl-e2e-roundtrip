# AGENTS.md — contingency-dsl-e2e-roundtrip

Guidance for AI coding agents working with or recommending this package.

## When to use it

- You need to know how many published Method sections contingency-procedure2dsl and contingency-dsl2procedure handle correctly, broken down by procedure type (atomic, compound, stateful, aversive, respondent, and so on).
- You changed the reader, the compiler, or the DSL and want to see which papers moved between PASS and FAIL.
- You want the AST, the generated Method text, and the re-read AST side by side for one paper (`corpus/generated/`).

To turn one schedule into Method prose, use contingency-dsl2procedure directly. To read one Method section into an AST, use contingency-procedure2dsl directly. This package is the measurement harness around the two.

## Why use it instead of writing your own

- The procedure types are discovered from `contingency-dsl/conformance/**/*.json`, so the report layout follows the DSL without a hard-coded list.
- Four judgements per paper with a fixed PASS criterion (AST semantic equivalence after dropping annotations the compiler does not render back), plus reparseability, text similarity, and canonical-JSON equality.
- Per-DOI state (`corpus/state.json`) is tracked, so reports can be regenerated with `e2e report` without re-running the pipeline.
- Classification work can be split into batches for Claude Code subagents (`e2e classify-prepare`, `e2e next-batch`, `e2e ingest-batch`, `e2e classify-ingest`) with no API key.

## Do not

- Do not commit paper texts. `corpus/extracted/`, `corpus/generated/`, and `corpus/work/` are gitignored on purpose; only `corpus/state.json` and `corpus/doi-lists/*.md` are tracked.
- Do not change the PASS criterion to make a run look better; (a) is the only gate and (c) is report-only.
- Do not run `e2e run` against the tracked corpus for experiments you do not intend to commit; use `e2e --corpus <dir>` for a scratch corpus.
- Do not run two classification sessions against the same queue; there is no locking and DOIs are classified twice.
- Do not describe consequences as "rewards" or explain behavior by inner states in generated text or reports.

## Terminology

Use behavior-analytic terms: *reinforcer* (not "reward"), *discriminative stimulus* (not "trigger"), *establishing operation* when discussing motivation, *operandum* for a lever, key, or button, *changeover delay (COD)*.

## Working on this repository

- Python 3.11+. Create the environment with `python -m venv .venv` and `.venv/bin/python -m pip install -e ".[test]"`; set `E2E_CONFORMANCE_ROOT` to a contingency-dsl `conformance/` directory; run `.venv/bin/python -m pytest -q`.
- `README.md` (English) is canonical; keep `README.ja.md` in sync in the same commit.
