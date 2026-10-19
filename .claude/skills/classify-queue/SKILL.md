---
name: classify-queue
description: Drain corpus/work/classify-queue.jsonl into corpus/work/classify-results.jsonl by dispatching the procedure-classifier subagent in 15-way parallel batches on haiku. Runs until the queue is empty, then ingests and reports.
---

# classify-queue

## Purpose

For each DOI in `corpus/work/classify-queue.jsonl` that is not yet in
`corpus/work/classify-results.jsonl`, call the `procedure-classifier`
subagent on `haiku` with that DOI's Method section, and append the result
to `corpus/work/classify-results.jsonl`. Parallelise 15 DOIs per batch until
the queue is drained, then run the ingest + report CLI.

All file handling goes through two CLI subcommands:

- `e2e next-batch N` — writes the next N prompts to
  `corpus/work/pending/<slug>.txt` and prints one
  `{"doi": ..., "prompt_file": ...}` line per DOI (stderr:
  `# emitted=<K> remaining=<M>`).
- `e2e ingest-batch <file>` — validates `{doi, procedures}` lines, appends
  them to `corpus/work/classify-results.jsonl`, removes the matching prompt
  files and the input file. Prints `appended=<K> skipped=<N>`.

## Preconditions — verify before starting

1. CWD must be the `contingency-dsl-e2e-roundtrip` project root. Confirm with
   `pwd` and that `corpus/work/classify-queue.jsonl` is visible (create it
   with `.venv/bin/e2e classify-prepare`). Abort if wrong.
2. `.venv/bin/e2e` exists. Abort otherwise (set up the venv with
   `mise exec -- python -m venv .venv` and `pip install -e .`).
3. The `procedure-classifier` subagent must be loaded. If in doubt, run a
   single probe first (see "Probe" below) and confirm JSON output before
   scaling to 15-way parallel.

To avoid a permission dialog on every batch, allow `Bash(.venv/bin/e2e:*)`
in your local Claude Code settings (`.claude/settings.local.json`, not
tracked).

## Probe (single-item smoke test)

The probe is **only required on the first invocation** of the skill. If
`corpus/work/classify-results.jsonl` already contains ≥1 line with a
non-empty `procedures` array, the agent definition is known to load
correctly — **skip the probe entirely and go straight to the main loop**.

Otherwise, run once:

1. `.venv/bin/e2e next-batch 1` → one line to stdout with
   `{"doi": ..., "prompt_file": ...}`.
2. `Read` the `prompt_file`.
3. Fire one `Agent` call:
   - `subagent_type="procedure-classifier"`
   - `model="haiku"`
   - `description="probe <doi>"`
   - `prompt=<file contents>`
4. Confirm the agent returned a single JSON object of shape
   `{"procedures": [...]}`.
5. Record the result exactly as in Step 5 below (one line).

### Probe failure handling

- **Malformed text output** (prose, markdown code fence, anything other
  than a plain JSON object when the agent call itself succeeded): **stop
  and tell the user**. The agent definition may not be loaded correctly.
- **API dispatch error** (e.g. `invalid_request_error: Output blocked by
  content filtering policy`, or any other per-call failure): this is
  **not** an agent-loading problem, only a per-DOI trigger. Record the
  probed DOI as `procedures: []` + `reason: "api-error"` via Step 5,
  **skip the rest of the probe step**, and proceed directly to the main
  loop. Do not retry. Do not halt.

## Main loop

Repeat until `next-batch` reports `remaining=0`:

### Step 1. Cut the next batch

Run:

```
.venv/bin/e2e next-batch 15
```

Stdout: up to 15 JSON lines, each `{"doi": ..., "prompt_file": ...}`.
Stderr: `# emitted=<K> remaining=<M>`.

If `K == 0`, break out of the loop.

### Step 2. Read all 15 prompts

For each emitted entry, `Read` its `prompt_file`. Keep the contents in
working memory for Step 3. Do **not** paraphrase, summarise or trim — the
prompt goes verbatim to the agent.

### Step 3. Fire 15 Agent calls in parallel

Emit **exactly 15** `Agent` tool_use blocks in **one message**:

- `subagent_type="procedure-classifier"` (never `general-purpose`)
- `model="haiku"` (never `opus` / `sonnet`)
- `description="classify <short-doi-suffix>"`
- `prompt=<verbatim contents of that DOI's prompt_file>`

Must be a single message with 15 tool_use blocks — splitting across messages
serialises them and defeats the purpose. If fewer than 15 prompts were
emitted (final residual batch), emit as many as were emitted.

### Step 4. Parse each agent response

Each `procedure-classifier` response is contracted to be a single JSON
object of shape `{"procedures": ["<key>", ...]}` with no surrounding prose.

For each response:

1. **If the agent dispatch itself errored** (e.g. Anthropic API returned
   `invalid_request_error: Output blocked by content filtering policy`,
   or any other per-agent dispatch failure), **do not stop the loop and
   do not retry**. Treat the DOI as `procedures: []` with an extra
   `"reason": "api-error"` field and continue with the remaining agents
   in the batch. The user can re-run the skill later on `reason: "api-error"`
   entries with a preprocessing fix.
2. Locate the JSON object: find the first `{` and the last `}` in the text.
3. Parse the slice. If parsing fails, or if the top-level object has no
   `procedures` key, or if `procedures` is not a list of strings, treat it
   as `procedures: []` and continue (do **not** retry, do **not** drop the
   DOI).
4. Build the result object:
   ```
   {"doi": "<doi>", "procedures": [...], "model": "procedure-classifier-haiku"}
   ```
   On API error, add `"reason": "api-error"` to the object.

### Step 5. Append the whole batch in one shot

1. Use the `Write` tool (not Bash) to write all result JSON objects, one
   per line, to `corpus/work/batch-results.jsonl`. One line per DOI. No
   wrapping array, no trailing comma. Each line must be a compact JSON
   object of shape:
   ```
   {"doi": "<doi>", "procedures": [...], "model": "procedure-classifier-haiku"}
   ```
2. Run a single Bash command (no pipes, no subshells):
   ```
   .venv/bin/e2e ingest-batch corpus/work/batch-results.jsonl
   ```
   It validates each line, appends valid ones to
   `corpus/work/classify-results.jsonl`, cleans up the matching
   `corpus/work/pending/<slug>.txt` files, and deletes the batch file
   itself. It prints `appended=<K> skipped=<N>`.

Never open `corpus/work/classify-results.jsonl` in write mode from anywhere
else — only `e2e ingest-batch` may touch it, and only in append mode. Do
not pipe results into `e2e ingest-batch -` inside the loop: shell pipes
trigger a per-batch approval dialog.

### Step 6. Progress line

After the batch completes, report one line:

```
batch done: <M-K> remaining / <done-so-far> done
```

Then loop back to Step 1.

## Finalisation — after `remaining=0`

1. `.venv/bin/e2e classify-ingest` (defaults to
   `corpus/work/classify-results.jsonl`)
2. `.venv/bin/e2e report`
3. Report the number of procedures now populated (e.g. "ingested N DOIs
   across K procedure buckets") and point the user at `corpus/doi-lists/`.

## Guardrails — do not violate

- **Run the full loop unattended.** Once invoked, keep draining the queue
  until `next-batch` reports `remaining=0`. Do **not** pause to ask
  the user "shall I continue?", "should I background this?", "would you
  like a checkpoint?", or any similar confirmation prompt mid-run. The
  only acceptable mid-run stops are: (i) probe returning **malformed
  text** (prose / code fence / non-JSON) — signals agent definition is
  not loaded correctly, (ii) the user explicitly interrupts. Progress
  reporting is allowed and encouraged, but must not block on user input.
  Per-agent API errors (e.g. content filter blocks) are **not** a
  stopping condition — this applies to **both** the probe and the main
  loop. Record the DOI as `procedures: []` with `reason: "api-error"`
  per Step 4 / Probe failure handling, and keep going.
- **15 parallel, one message.** Never split into sequential Agent calls.
  Never change the batch size without the user explicitly telling you to.
- **model="haiku" always.** Never fall back to opus/sonnet for speed
  reasons.
- **Append only.** Never truncate, rewrite, or reorder
  `corpus/work/classify-results.jsonl`.
- **No retries on malformed agent output or API errors.** Record
  `procedures: []` (with `reason: "api-error"` for dispatch failures)
  and move on; the user can re-run the skill later on the empty ones.
- **No prompt condensation.** Pass each DOI's prompt verbatim to the
  subagent. Do not "condense prompts to manage tokens" — the classifier
  needs the full Method text to decide correctly.
- **No API key fallback.** If the subagent path is broken, stop and tell
  the user rather than shelling out to `claude -p` or the Anthropic SDK.
- **No touching `corpus/state.json` directly.** Only the `e2e
  classify-ingest` CLI writes to it.
