from contingency_dsl_e2e_roundtrip import state as state_mod


def test_upsert_classification_persists_in_scope():
    state = {"version": 1, "entries": {}}
    state_mod.upsert_classification(
        state, "10.1/x", procedures=["operant/atomic"], model="haiku"
    )
    entry = state["entries"]["10.1/x"]
    assert entry["procedures"] == ["operant/atomic"]
    assert entry["classified_with"] == "haiku"
    # No reason key appears for in-scope entries (default absent).
    assert entry.get("out_of_scope_reason") in (None, "")


def test_upsert_classification_persists_out_of_scope_reason():
    state = {"version": 1, "entries": {}}
    state_mod.upsert_classification(
        state,
        "10.2/y",
        procedures=[],
        model="haiku",
        out_of_scope_reason="meta-analysis: model fitting only",
    )
    entry = state["entries"]["10.2/y"]
    assert entry["procedures"] == []
    assert entry["out_of_scope_reason"] == "meta-analysis: model fitting only"


def test_upsert_classification_clears_stale_reason_when_reclassified_in_scope():
    state = {
        "version": 1,
        "entries": {
            "10.3/z": {
                "procedures": [],
                "classified_with": "haiku",
                "out_of_scope_reason": "old reason",
            }
        },
    }
    state_mod.upsert_classification(
        state, "10.3/z", procedures=["operant/atomic"], model="haiku"
    )
    entry = state["entries"]["10.3/z"]
    assert entry["procedures"] == ["operant/atomic"]
    assert entry.get("out_of_scope_reason") in (None, "")
