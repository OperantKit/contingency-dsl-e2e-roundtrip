from contingency_dsl_e2e_roundtrip.procedures import discover_procedures


def test_discover_procedures_is_nonempty():
    procs = discover_procedures()
    assert procs, "conformance root produced no procedure types"


def test_procedure_keys_are_posix_style():
    for proc in discover_procedures():
        assert "\\" not in proc.key
        assert not proc.key.endswith(".json")
        assert proc.doi_list_filename.endswith(".md")
        assert "/" not in proc.doi_list_filename


def test_expected_keys_present():
    keys = {p.key for p in discover_procedures()}
    # Spot-check that at least these canonical keys show up.
    assert "operant/atomic" in keys
    assert "respondent/elementary" in keys
