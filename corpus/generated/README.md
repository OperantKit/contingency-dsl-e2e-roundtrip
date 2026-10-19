# corpus/generated/

Per-DOI round-trip intermediates, written by `e2e run`. Gitignored (cache).

```
generated/
├── dsl/<slug>.json       # AST_1 — contingency-procedure2dsl(T)
├── compiled/<slug>.txt   # P     — contingency-dsl2procedure(AST_1)
└── dsl2/<slug>.json      # AST_2 — contingency-procedure2dsl(P)
```

`<slug> = doi.replace("/", "_")`.

Judgements derived in [`../../src/contingency_dsl_e2e_roundtrip/roundtrip.py`](../../src/contingency_dsl_e2e_roundtrip/roundtrip.py):

| Key | Compares                            | PASS condition |
|-----|-------------------------------------|----------------|
| a   | `normalize(AST_1) == normalize(AST_2)` | semantic DSL equivalence |
| b   | `AST_2 is not None`                 | P re-parseable |
| c   | `jaccard(T, P)`                     | text similarity (report-only) |
| d   | `canonical_json(AST_1) == canonical_json(AST_2)` | surface DSL equivalence |

Regenerate everything by deleting this directory and running
`.venv/bin/e2e run` (the pipeline skips nothing — artifacts overwrite).
