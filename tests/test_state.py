import json

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


def test_load_merges_case_variant_dois_into_one_lowercase_entry(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "entries": {
                    "10.3758/BF00000001": {
                        "procedures": ["operant/atomic"],
                        "classified_with": "haiku",
                    },
                    "10.3758/bf00000001": {
                        "procedures": [],
                        "classified_with": "haiku",
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    entries = state_mod.load(path)["entries"]
    assert list(entries) == ["10.3758/bf00000001"]
    assert entries["10.3758/bf00000001"]["procedures"] == ["operant/atomic"]


def test_merge_prefers_in_scope_then_more_procedures():
    in_scope = {"procedures": ["operant/atomic"], "classified_with": "haiku"}
    oos = {"procedures": [], "classified_with": "haiku", "out_of_scope_reason": "r"}
    assert state_mod.merge_entries(oos, in_scope) is in_scope
    assert state_mod.merge_entries(in_scope, oos) is in_scope
    more = {"procedures": ["a", "b"], "classified_with": "haiku"}
    assert state_mod.merge_entries(in_scope, more) is more
    assert state_mod.merge_entries(more, in_scope) is more


def test_upsert_writes_lowercase_key_onto_existing_entry():
    state = {"version": 1, "entries": {}}
    state_mod.upsert_classification(state, "10.1/ABC", procedures=["x"], model="m")
    state_mod.upsert_roundtrip(state, "10.1/abc", {"ok": True, "ast1": {}})
    assert list(state["entries"]) == ["10.1/abc"]
    assert state["entries"]["10.1/abc"]["roundtrip"] == {"ok": True}


def test_save_merges_case_variants(tmp_path):
    path = tmp_path / "state.json"
    state_mod.save(
        {"version": 1, "entries": {"10.1/A": {"procedures": []}, "10.1/a": {"procedures": []}}},
        path,
    )
    assert list(json.loads(path.read_text(encoding="utf-8"))["entries"]) == ["10.1/a"]
