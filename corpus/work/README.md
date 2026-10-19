# corpus/work/

Classification work files for the sub-agent path. Gitignored (only this
README is tracked).

```
work/
├── classify-queue.jsonl    # e2e classify-prepare — {doi, allowed_keys, method_text, truncated}
├── pending/<slug>.txt      # e2e next-batch N   — one sub-agent prompt per DOI
├── batch-results.jsonl     # written by the driver, consumed (and deleted) by e2e ingest-batch
└── classify-results.jsonl  # e2e ingest-batch   — append-only {doi, procedures, model}
```

`<slug> = doi.replace("/", "_")`.

A DOI counts as done once it appears in `classify-results.jsonl`, so
`e2e next-batch` resumes from the difference after a crash. Fold the
results into `../state.json` with `e2e classify-ingest`.
