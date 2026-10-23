# contingency-dsl-e2e-roundtrip

:jp: [日本語版 README](README.ja.md)

End-to-end round-trip harness that verifies the Method section of a paper
survives the full pipeline intact:

```
paper text T ──▶ contingency-procedure2dsl ──▶ DSL-AST ① (= ast1)
                                               │
                                               ▼
                                     contingency-dsl2procedure
                                               │
                                               ▼
                                         paper text P
                                               │
                                               ▼
                               contingency-procedure2dsl ──▶ DSL-AST ② (= ast2)
```

Four judgements are recorded per paper. The overall PASS is determined by (a).

| Key  | Judgement                                   | PASS condition                               |
|------|---------------------------------------------|----------------------------------------------|
| a    | AST semantic equivalence                    | `normalize(ast1) == normalize(ast2)`         |
| b    | Reparseability of compiled text `P`         | `reader(P)` returns a non-null AST           |
| c    | Text similarity between `T` and `P`         | Jaccard ≥ threshold (report-only, not gating) |
| d    | DSL surface-syntax equivalence (form①=form②) | `canonical_json(ast1) == canonical_json(ast2)` |

## Procedure classification

Procedure kinds are discovered **dynamically** from
`contingency-dsl/conformance/**/*.json`. Each JSON file becomes one
procedure key (e.g. `operant/atomic`, `operant/stateful/adjusting`,
`respondent/elementary`). Adding or renaming conformance files on the DSL
side propagates automatically into this project's DOI-list layout (no
hardcoded list).

One markdown file per procedure key is generated under `corpus/doi-lists/`,
each DOI displayed as a checkbox status line:

```
- [x] 10.1901/jeab.2005.33-03 — PASS (a:✓ b:✓ c:0.82 d:✓)
- [ ] 10.1002/jaba.226        — FAIL (a:✗ b:✓ c:0.41 d:✗)
```

Classification reliability was checked on a stratified sample of N=60 papers.
Both raters classified the sample with the current prompt, which gives a short
definition for each key whose bare name raters had read in different ways: the
first rater is Claude haiku via the `claude` CLI and the second rater is OpenAI
gpt-6.1-sol via the Codex CLI, with the same prompt and output schema
(`e2e second-rate --backend claude-cli|codex-cli`, then
`e2e agreement <second.jsonl> --first <first.jsonl>`; without `--first` the
classifications stored in `state.json` are the first rater). Per-key Cohen's κ
(assigned / not assigned) pooled over all keys gives micro κ = 0.795; among the
14 keys that both raters assigned to at least 5 papers, `experiment/paper` is
lowest (κ = 0.343) and `annotations/measurement` and
`annotations/procedure-stimulus` are highest (κ = 1.000).

## Generated artifacts (gitignored)

Every `e2e run` writes the three round-trip intermediates per DOI in their
human-readable surface forms under `corpus/generated/`:

```
corpus/generated/
├── dsl/<slug>.dsl        # AST_1 rendered as canonical DSL (e.g. "FR5")
├── compiled/<slug>.txt   # P — dsl2procedure paper text
└── dsl2/<slug>.dsl       # AST_2 rendered as canonical DSL
```

This directory is **gitignored** (regenerable from `corpus/extracted/`).
ASTs that cannot be rendered into a valid Program (e.g. partial
Experiment / Paper nodes) fall back to a commented JSON sidecar so no
round-trip result is silently lost.

## Extraction cache (gitignored)

Procedure plain text is cached under `corpus/extracted/<doi-slug>.txt`.
This directory is **gitignored**. If a file exists, extraction is skipped.

Fallback order when the cache is missing. Steps 2–4 are used only when
`E2E_PAPER_SOURCES_ROOT` points at a directory of your own paper sources:

1. `corpus/extracted/<doi-slug>.txt` (this project)
2. `$E2E_PAPER_SOURCES_ROOT/reference/papers/extracted/<doi-slug>.md`
   (whole-paper markdown) — slice the Method section from it
3. `$E2E_PAPER_SOURCES_ROOT/reference/papers/pdf/<doi-slug>.pdf` (raw PDF)
   — slice the Method section
4. `$E2E_PAPER_SOURCES_ROOT/notes/papers/*.md` (notes with a `doi:`
   front-matter field) — use the procedure section

`<doi-slug> = doi.replace("/", "_")`.

## Setup

The harness reads the procedure taxonomy from the
[contingency-dsl](https://github.com/OperantKit/contingency-dsl)
conformance tree, so clone it as well and point `E2E_CONFORMANCE_ROOT` at
its `conformance/` directory:

```bash
git clone https://github.com/OperantKit/contingency-dsl-e2e-roundtrip
git clone https://github.com/OperantKit/contingency-dsl
cd contingency-dsl-e2e-roundtrip
python -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
# Optional: Anthropic SDK classification backend (requires ANTHROPIC_API_KEY)
.venv/bin/python -m pip install -e '.[llm]'

export E2E_CONFORMANCE_ROOT="$PWD/../contingency-dsl/conformance"  # required
.venv/bin/python -m pytest -q
```

`pip` installs contingency-dsl-py from PyPI and contingency-procedure2dsl /
contingency-dsl2procedure from their GitHub tags, so no other checkout is
needed. Python 3.11 or later.

| Variable                 | Required | Meaning                                                                 |
|--------------------------|----------|-------------------------------------------------------------------------|
| `E2E_CONFORMANCE_ROOT`   | yes      | Path to `contingency-dsl/conformance`. A sibling `../contingency-dsl/conformance` next to this checkout is used when it is unset. |
| `E2E_PAPER_SOURCES_ROOT` | no       | Your own paper notes / markdown / PDFs, used as extraction fallbacks 2–4 above. Unset = only `corpus/extracted/` is read. |
| `E2E_CLASSIFIER_BACKEND` | no       | Force `anthropic` or `claude-cli` (see below).                          |

The paper texts behind `corpus/state.json` are not distributed;
`corpus/extracted/` starts empty in a fresh clone. Supply Method text
yourself as shown in the next section.

## 30-second example

Round-trip one Method passage. Write the text to the extraction cache
under a DOI of your choice (here a placeholder DOI in a scratch corpus, so
the tracked `corpus/state.json` is left untouched), then run it:

```bash
mkdir -p demo/corpus/extracted
cat > demo/corpus/extracted/10.0000_demo.txt <<'EOF'
Procedure
Lever presses were reinforced under a fixed-ratio 5 schedule: every fifth response produced a food pellet. Sessions were conducted daily and ended after 60 reinforcers or 60 min, whichever came first. Training continued until response rates were stable across five consecutive sessions.
EOF
.venv/bin/e2e --corpus demo/corpus run --doi 10.0000/demo
# [PASS] 10.0000/demo: a=True b=True c=0.2 d=True
cat demo/corpus/generated/dsl/10.0000_demo.dsl        # FR5
cat demo/corpus/generated/compiled/10.0000_demo.txt   # Responses were reinforced under a fixed-ratio (FR) 5 schedule.
```

The cached text must contain at least 200 characters of prose; shorter
files are treated as empty templates and discarded. `run` needs no LLM:
the classification step (`classify`) is the only one that calls a model.

### Classification backends

The classifier selects a backend automatically:

| Backend      | Requirement                                   | When used                                              |
|--------------|-----------------------------------------------|--------------------------------------------------------|
| `anthropic`  | `ANTHROPIC_API_KEY`, `[llm]` extra            | Preferred when the env var is set                      |
| `claude-cli` | `claude` binary (Claude Code CLI)             | Fallback — reuses existing CLI session, no API key     |

You can force-select via `E2E_CLASSIFIER_BACKEND={anthropic,claude-cli}`.
The CLI backend spawns `claude -p` per call with `cwd=/tmp` and
`--no-session-persistence`. Because it rebuilds the session cache each
time, it is slower than the SDK path and burns more tokens.

## CLI

```bash
.venv/bin/e2e list-procedures               # Show all DSL procedure keys
.venv/bin/e2e extract --doi <doi>           # Populate extracted/<slug>.txt
.venv/bin/e2e classify --doi <doi>          # Classify via LLM (needs ANTHROPIC_API_KEY or claude CLI)
.venv/bin/e2e classify-prepare              # Write corpus/work/classify-queue.jsonl for subagent consumption
.venv/bin/e2e next-batch 15                 # Cut the next 15 unclassified rows into corpus/work/pending/*.txt
.venv/bin/e2e ingest-batch <file>           # Append {doi, procedures} lines ('-' = stdin) to corpus/work/classify-results.jsonl
.venv/bin/e2e classify-ingest [<results>]   # Fold subagent results JSONL back into state
.venv/bin/e2e regenerate-agent              # (Re)publish the procedure-classifier subagent md
.venv/bin/e2e run --doi <doi>               # Round-trip a single DOI
.venv/bin/e2e run --all                     # Round-trip every classified paper
.venv/bin/e2e report                        # Regenerate doi-lists/*.md from state
```

## Classification via Claude Code sub-agent (no API key required)

When running inside an interactive Claude Code session, the fastest path
is to dispatch classification to a sub-agent via the `Agent` tool. No
`ANTHROPIC_API_KEY` and no `claude -p` subprocess required.

1. Publish / regenerate the sub-agent definition (written to
   `.claude/agents/procedure-classifier.md` inside this project):

   ```bash
   .venv/bin/e2e regenerate-agent
   ```

   Then restart Claude Code once so the new agent type is discovered
   (Claude Code reads agent definitions only at session start).

2. Prepare the DOI queue to be classified:

   ```bash
   .venv/bin/e2e classify-prepare          # writes corpus/work/classify-queue.jsonl
   ```

3. Inside Claude Code, ask the session to perform batch classification.
   The session cuts prompts with `e2e next-batch 15`, calls
   `Agent(subagent_type="procedure-classifier", ...)` in parallel, and
   appends one JSON object per DOI — `{"doi": "...", "procedures": [...]}`
   — to `corpus/work/classify-results.jsonl` with `e2e ingest-batch`.

4. Fold the results back into state and regenerate the per-procedure
   DOI lists:

   ```bash
   .venv/bin/e2e classify-ingest           # reads corpus/work/classify-results.jsonl
   .venv/bin/e2e report
   ```

Until the new agent is discovered (i.e. until step 1 and the restart
complete), you can fall back to `subagent_type="general-purpose"` with
the taxonomy pasted inline into the prompt.

### Bulk runs via the `classify-queue` skill with Haiku

For queues in the hundreds-of-DOIs range, the cheapest path is to keep
Haiku resident and call the
[`classify-queue` skill](.claude/skills/classify-queue/SKILL.md).
Making both the orchestrator (the side driving the conversation) and the
sub-agents (`Agent(model="haiku", ...)`) Haiku cuts token cost
substantially compared with an Opus/Sonnet-driven orchestrator. The
skill ships with this repo, and the queue handling it relies on is the
`e2e next-batch` / `e2e ingest-batch` subcommands.

1. Refresh the sub-agent definition and restart Claude Code inside this
   project so the agent type is reloaded:

   ```bash
   .venv/bin/e2e regenerate-agent
   ```

2. Generate the queue:

   ```bash
   .venv/bin/e2e classify-prepare
   ```

3. Launch a Haiku-only session **from this project root** (skill
   discovery and helper paths are CWD-dependent; wrong directory =
   broken run):

   ```bash
   cd <this-package-root>
   claude \
     --model haiku \
     --effort low \
     --permission-mode bypassPermissions
   ```

   Flag rationale:

   - `--effort low` — minimises Haiku's extended-thinking. Classification
     is deterministic, so high-effort reasoning is overkill (and adds
     several minutes of latency per batch). Success looks like a startup
     banner that names a Haiku model with low effort.
   - `--permission-mode bypassPermissions` (alias
     `--dangerously-skip-permissions`) — skips the approval dialog that
     would otherwise fire on every shell pipe / subshell `( ... )`. The
     skill only touches project-local files, so no real blast radius.
     Claude Code still shows a trust prompt at startup — answer "Yes".
   - Use this session for this project only. Do not mix tasks that
     require external network access or system changes into the same
     session.

4. Invoke the skill inside that session:

   ```
   /classify-queue
   ```

   What the skill does:

   - Probe once on a single DOI and halt if the reply is not a JSON
     object
   - Split the remaining un-classified DOIs into batches of 15 with
     `e2e next-batch 15` (prompts land in `corpus/work/pending/<slug>.txt`)
   - Fire 15 `Agent(subagent_type="procedure-classifier",
     model="haiku", ...)` calls in parallel in a single message
   - `Write`-tool the 15 result lines into `corpus/work/batch-results.jsonl`,
     then `.venv/bin/e2e ingest-batch corpus/work/batch-results.jsonl`
     appends them to `corpus/work/classify-results.jsonl` (single command,
     no shell pipe — so allowing `Bash(.venv/bin/e2e:*)` in your local
     `.claude/settings.local.json` avoids per-batch approval dialogs)
   - Loop until `next-batch` reports `remaining=0`, then auto-run
     `classify-ingest` and `report` at the end

5. Resume / re-run behaviour

   - `e2e next-batch` excludes DOIs already present in
     `corpus/work/classify-results.jsonl`, so a crashed / restarted
     session resumes from the diff
   - Running `/classify-queue` again after full completion exits
     immediately with `remaining=0` (no-op)
   - Empty `procedures: []` lines count as "done" and are not
     re-classified automatically. To redo one, delete its row from
     `corpus/work/classify-results.jsonl` and re-invoke the skill

6. Caveat on parallelism

   Running two Haiku sessions against the same queue will double-pick
   the same 15 DOIs and classify them twice (no locking). Run a single
   session, or pre-split the queue before launch.

## State management

Per-DOI round-trip results are persisted as JSON in `corpus/state.json`
(tracked). Reports can be regenerated from state without re-running the
pipeline.
