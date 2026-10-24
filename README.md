# contingency-dsl-e2e-roundtrip

:jp: [日本語版 README](README.ja.md)

contingency-dsl-e2e-roundtrip checks, paper by paper, whether the procedure in a published Method section survives a round trip: Method text → schedule expression → generated Method text → schedule expression. It is for people who develop or evaluate the OperantKit tools that read Method sections ([contingency-procedure2dsl](https://github.com/OperantKit/contingency-procedure2dsl)) and write them ([contingency-dsl2procedure](https://github.com/OperantKit/contingency-dsl2procedure)), and who want to know which kinds of procedure they handle. Within [OperantKit](https://github.com/OperantKit), it is the measurement harness around those two packages.

- **One verdict per paper,** broken down by procedure type, so a change to the reader, the writer, or the language shows which papers moved between PASS and FAIL.
- **The intermediates are kept** (the expression, the generated text, the re-read expression), so a failure can be inspected directly.
- **The round trip needs no language model;** only sorting papers into procedure types does.

## What is compared

```
Method text T ──▶ contingency-procedure2dsl ──▶ AST₁
                                               │
                                               ▼
                                     contingency-dsl2procedure
                                               │
                                               ▼
                                      generated text P
                                               │
                                               ▼
                               contingency-procedure2dsl ──▶ AST₂
```

An AST (abstract syntax tree) is the parsed form of a schedule expression. Four judgements are recorded per paper; PASS is decided by (a) alone.

| Key | Judgement | Condition |
|---|---|---|
| a | The two ASTs mean the same procedure | `normalize(AST₁) == normalize(AST₂)` (annotations the writer does not put back into text are dropped first) |
| b | The generated text can be read again | `AST₂` is not empty |
| c | Word overlap between T and P | Jaccard similarity of lower-cased words; reported only |
| d | The two ASTs are written identically | `canonical_json(AST₁) == canonical_json(AST₂)` |

## Installation

Python 3.11 or newer. The OperantKit packages are not on PyPI yet, and pip cannot resolve this package's dependency on contingency-dsl-py from GitHub, so install the OperantKit packages without dependency resolution and add the third-party libraries:

```bash
G=git+https://github.com/OperantKit
pip install --no-deps $G/contingency-dsl-e2e-roundtrip $G/contingency-dsl-py \
  $G/contingency-procedure2dsl@v0.1.0 $G/contingency-dsl2procedure@v0.1.0
pip install pyyaml pypdf pymupdf
```

pip (and `pip check`) reports a conflict: the contingency-dsl-py development build does not satisfy the declared version. It does not affect the commands below.

The procedure types are read from the conformance tests of [contingency-dsl](https://github.com/OperantKit/contingency-dsl), so clone it too and point `E2E_CONFORMANCE_ROOT` at its `conformance/` directory:

```bash
git clone https://github.com/OperantKit/contingency-dsl
export E2E_CONFORMANCE_ROOT="$PWD/contingency-dsl/conformance"
```

## Example

Round-trip one Method passage. Put the text in the extraction cache of a scratch corpus under a placeholder DOI, then run it:

```bash
mkdir -p demo/corpus/extracted
cat > demo/corpus/extracted/10.0000_demo.txt <<'EOF'
Procedure
Lever presses were reinforced under a fixed-ratio 5 schedule: every fifth response produced a food pellet. Sessions were conducted daily and ended after 60 reinforcers or 60 min, whichever came first. Training continued until response rates were stable across five consecutive sessions.
EOF
e2e --corpus demo/corpus run --doi 10.0000/demo
# [PASS] 10.0000/demo: a=True b=True c=0.2 d=True
cat demo/corpus/generated/dsl/10.0000_demo.dsl        # FR5
cat demo/corpus/generated/compiled/10.0000_demo.txt   # Responses were reinforced under a fixed-ratio (FR) 5 schedule.
```

A cached text needs at least 200 characters of prose; shorter files are treated as empty templates and discarded.

## Commands

| Command | What it does |
|---|---|
| `e2e run --doi <doi>` / `--all` | Round-trip one paper, or every classified paper |
| `e2e report` | Rebuild `corpus/doi-lists/*.md` from the stored results |
| `e2e list-procedures` | Print the procedure types read from contingency-dsl |
| `e2e extract --doi <doi>` / `--all` | Fill the extraction cache `corpus/extracted/<slug>.txt` |
| `e2e classify --doi <doi>` / `--all` | Sort a paper into procedure types with a language model |
| `e2e classify-prepare`, `next-batch`, `ingest-batch`, `classify-ingest`, `regenerate-agent` | Classify through Claude Code subagents, without an API key |
| `e2e second-rate`, `agreement` | Classify a sample with a second rater and compute Cohen's κ per procedure type |

`--corpus <dir>` (before the command) works on another corpus than `corpus/`. Classification, its backends, and its reliability are described in [docs/en/classification.md](docs/en/classification.md).

## Files

| Path | Tracked | Contents |
|---|---|---|
| `corpus/state.json` | yes | Procedure types and round-trip results per DOI |
| `corpus/doi-lists/*.md` | yes | One list per procedure type, one line per DOI with its verdict; [`index.md`](corpus/doi-lists/index.md) gives the counts |
| `corpus/extracted/<slug>.txt` | no | Method text per DOI (`<slug>` is the DOI with `/` replaced by `_`); extraction is skipped when the file exists |
| `corpus/generated/{dsl,compiled,dsl2}/` | no | AST₁ as an expression, the generated text P, AST₂ as an expression. An AST that cannot be written as an expression is saved as commented JSON |

The tracked corpus lists 580 DOIs, 39 of them classified as out of scope (counted in `corpus/state.json`). The paper texts behind it are not distributed, so `corpus/extracted/` is empty in a fresh clone; supply Method text yourself as in the example.

| Variable | Required | Meaning |
|---|---|---|
| `E2E_CONFORMANCE_ROOT` | yes | The `conformance/` directory of contingency-dsl. When unset, `../contingency-dsl/conformance` next to this checkout is used |
| `E2E_PAPER_SOURCES_ROOT` | no | A directory of your own copies of the papers, read when the cache is missing ([layout](docs/en/classification.md#reading-method-sections-from-your-own-files)) |
| `E2E_CLASSIFIER_BACKEND` | no | `anthropic` or `claude-cli`, to force the classification backend |

## Limitations

- A PASS means the reader and the writer agree with each other, not that the expression matches what the authors did. Both directions can drop the same detail.
- Similarity (c) is a word-overlap measure and is not used for PASS. The generated text states only the schedule, so values are low: the median over the 419 papers with a value in `corpus/state.json` is 0.017.
- The pinned contingency-procedure2dsl and contingency-dsl2procedure tags (`v0.1.0`) are what is measured; newer versions of those packages are not tested here unless you install them.
- Procedure types are assigned by language models, and their reliability was measured between two models, not against a human rater.

## For AI coding agents

Guidance for AI coding agents is in [AGENTS.md](AGENTS.md).

## Development

```bash
python -m venv .venv
G=git+https://github.com/OperantKit
.venv/bin/python -m pip install --no-deps -e . $G/contingency-dsl-py \
  $G/contingency-procedure2dsl@v0.1.0 $G/contingency-dsl2procedure@v0.1.0
.venv/bin/python -m pip install pyyaml pypdf pymupdf pytest
E2E_CONFORMANCE_ROOT=<path to contingency-dsl/conformance> .venv/bin/python -m pytest -q
```

## License

MIT. See [LICENSE](LICENSE).
