# Classifying papers by procedure type

:jp: [日本語版](../ja/classification.md)

The round trip itself (`e2e run`) needs no language model. Classification, which decides which procedure types a paper's Method section uses, does. This page describes the procedure types, how classification is run, and how reliable it is.

## Procedure types

Procedure types are read from the conformance tree of [contingency-dsl](https://github.com/OperantKit/contingency-dsl): every `conformance/**/*.json` file becomes one key (for example `operant/atomic`, `operant/stateful/adjusting`, `respondent/elementary`). When files are added or renamed there, the keys here follow; there is no hard-coded list. `e2e list-procedures` prints the current keys.

`e2e report` writes one Markdown file per key under `corpus/doi-lists/`, with one line per DOI:

```
- [x] 10.1901/jeab.2005.33-03 — PASS (a:✓ b:✓ c:0.82 d:✓)
- [ ] 10.1002/jaba.226        — FAIL (a:✗ b:✓ c:0.41 d:✗)
```

`corpus/doi-lists/index.md` lists every key with its passing count.

## Classifying with a backend

`e2e classify --doi <doi>` (or `--all`) classifies papers directly. The backend is chosen automatically:

| Backend | Needs | When it is used |
|---|---|---|
| `anthropic` | `ANTHROPIC_API_KEY` and the `anthropic` package | When `ANTHROPIC_API_KEY` is set |
| `claude-cli` | The `claude` command (Claude Code) | Otherwise, if `claude` is on the PATH |

`E2E_CLASSIFIER_BACKEND=anthropic` or `=claude-cli` forces one. The `claude-cli` backend starts `claude -p` once per paper, with `/tmp` as the working directory and `--no-session-persistence`; it needs no API key but is slower and uses more tokens than the SDK.

## Classifying with Claude Code subagents

Inside an interactive Claude Code session, classification can be handed to subagents, with no API key and no `claude -p` subprocess.

1. Write the subagent definition from the current procedure types, then restart Claude Code so that it is loaded (agent definitions are read only at session start):

   ```bash
   .venv/bin/e2e regenerate-agent     # writes .claude/agents/procedure-classifier.md
   ```

2. Build the queue of papers to classify:

   ```bash
   .venv/bin/e2e classify-prepare     # writes corpus/work/classify-queue.jsonl
   ```

3. Ask the session to classify the queue. It takes the next prompts with `e2e next-batch 15`, runs `Agent(subagent_type="procedure-classifier", ...)` on them in parallel, and appends one line `{"doi": "...", "procedures": [...]}` per paper to `corpus/work/classify-results.jsonl` with `e2e ingest-batch`.

4. Fold the results into the state and rebuild the lists:

   ```bash
   .venv/bin/e2e classify-ingest      # reads corpus/work/classify-results.jsonl
   .venv/bin/e2e report
   ```

Until the restarted session has loaded `procedure-classifier`, `subagent_type="general-purpose"` with the list of keys pasted into the prompt works as well.

### Long queues: the `classify-queue` skill

For queues of hundreds of papers, the repository includes the [`classify-queue` skill](../../.claude/skills/classify-queue/SKILL.md). Running both the session and its subagents on Haiku (`claude --model haiku`, then `/classify-queue`) costs far fewer tokens than a session on a larger model. Start the session from the root of this repository: the skill and its helper paths are found relative to the working directory.

The skill:

- probes one paper first and stops if the reply is not a JSON object;
- takes the remaining papers 15 at a time with `e2e next-batch 15` (prompts go to `corpus/work/pending/<slug>.txt`);
- runs 15 `Agent(subagent_type="procedure-classifier", model="haiku", ...)` calls in parallel;
- writes the 15 result lines to `corpus/work/batch-results.jsonl` and appends them to `corpus/work/classify-results.jsonl` with `e2e ingest-batch` (one command, no shell pipe, so a single permission rule for `.venv/bin/e2e` covers every batch);
- repeats until `next-batch` reports `remaining=0`, then runs `classify-ingest` and `report`.

Restarting and re-running:

- `e2e next-batch` skips papers already in `corpus/work/classify-results.jsonl`, so a crashed session resumes where it stopped.
- Running `/classify-queue` again after the queue is finished exits at once with `remaining=0`.
- A line with `procedures: []` counts as done. To classify that paper again, delete its line from `corpus/work/classify-results.jsonl` and run the skill again.
- There is no locking. Two sessions on the same queue take the same 15 papers and classify them twice; run one session, or split the queue first.

## Reliability

`e2e second-rate <file>` classifies the DOIs listed in a file (one per line) with a second rater and appends the results to a JSONL file without touching `state.json` (`--backend claude-cli` or `codex-cli`). `e2e agreement <second.jsonl>` then reports Cohen's κ per key (assigned / not assigned) between the classifications in `state.json` and the second rater; `--first <first.jsonl>` compares two JSONL files instead.

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

The agreement is between two language models, not between a model and a human rater.

## Reading Method sections from your own files

When `corpus/extracted/<slug>.txt` is missing, `e2e extract` can take the Method section from your own copies of the papers if `E2E_PAPER_SOURCES_ROOT` points at a directory laid out like this, tried in this order (`<slug>` is the DOI with `/` replaced by `_`):

```
$E2E_PAPER_SOURCES_ROOT/reference/papers/extracted/<slug>.md   # whole paper as Markdown; the Method section is cut out
$E2E_PAPER_SOURCES_ROOT/reference/papers/pdf/<slug>.pdf        # PDF; the Method section is cut out
$E2E_PAPER_SOURCES_ROOT/notes/papers/*.md                      # notes with a doi: field in the front matter
```
