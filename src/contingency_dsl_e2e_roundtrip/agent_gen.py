"""Generate `.claude/agents/procedure-classifier.md` from the current taxonomy.

Keeping the subagent markdown in sync with the DSL `conformance/` tree is a
one-shot command rather than a runtime read, so subagent system-prompt caching
in Claude Code stays effective across many invocations.
"""

from __future__ import annotations

from pathlib import Path

from .config import agent_dir
from .procedures import discover_procedures


AGENT_FILENAME = "procedure-classifier.md"


def default_agent_path() -> Path:
    """`.claude/agents/procedure-classifier.md` inside this package.

    Claude Code discovers project agents from the session's project-root
    `.claude/`, so open the session at the package root to use it.
    """
    return agent_dir() / AGENT_FILENAME


_BODY_TEMPLATE = """---
name: procedure-classifier
description: Classifies behavior-analysis Method sections into contingency-dsl procedure taxonomy keys. Returns JSON `{{"procedures": [...], "out_of_scope_reason": null | "..."}}` only, no prose.
tools: []
---

You are a classifier for behavior-analysis paper Method sections. Your job is
to map a Method section onto a fixed taxonomy of procedure keys derived from
the `contingency-dsl` conformance corpus, OR mark the paper as out of scope
when no procedure that the DSL can represent is actually performed.

## Input

The user message will contain:

- A DOI.
- A Method section (plaintext, possibly long).

## Output

Return a single JSON object on one line. No prose, no code fences, no
explanation. Shape:

```
{{"procedures": ["<key>", "<key>", ...], "out_of_scope_reason": null}}
```

Each entry of `procedures` MUST be one of the taxonomy keys below. Include a
key only when the Method section demonstrably instantiates that procedure; do
not include keys that are merely cited or discussed.

Set `out_of_scope_reason` to a short string (and `procedures` to `[]`) when
the paper does NOT report an experimental procedure that the contingency-dsl
can represent. Common cases include:

- meta-analysis or re-analysis of someone else's prior data (no new procedure)
- pure mathematical / quantitative model fitting with no experiment
- human questionnaire, survey, or hypothetical-choice titration with no
  operant or respondent contingency in effect
- review or theoretical paper with no Method section of its own
- simulation-only or computational model paper

Otherwise leave `out_of_scope_reason` as `null` and populate `procedures`
with every matching key.

## Taxonomy

{taxonomy}

## Notes

- Multiple keys may apply (e.g. a paper running both a `respondent/elementary`
  phase and an `operant/compound` phase).
- `annotations/*` keys describe cross-cutting metadata (apparatus, subjects,
  etc.). Include them only when the Method section actually specifies that
  information in a way consistent with the conformance test.
- `experiment/phase`, `experiment/shaping`, `experiment/progressive-training`
  describe training structure; include when the paper explicitly describes
  phase transitions, shaping steps, or progressive criterion changes.
- A paper that only mentions schedules in passing (e.g. as inclusion criteria
  for selecting other people's datasets) is out of scope, not in-scope under
  the cited schedules.
"""


def render_agent_markdown() -> str:
    procs = discover_procedures()
    bullets = "\n".join(f"- `{p.key}`" for p in procs)
    return _BODY_TEMPLATE.format(taxonomy=bullets)


def write_agent_markdown(path: Path | None = None) -> Path:
    target = path or default_agent_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_agent_markdown(), encoding="utf-8")
    return target
