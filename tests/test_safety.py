"""Tests for the deterministic safety rail, drug graph, and pipelines."""

from brahmo.safety import (
    VALID_STATES,
    Medication,
    run_demo_checks,
    run_safety_checks,
    all_states_reachable_demo,
)
from brahmo.drug_graph import resolve_drug
from brahmo.orchestrator import classify_intent, run_medication_review_pipeline
from brahmo.retrieval import search_evidence, evidence_sufficiency_gate


def test_valid_states_count():
    assert len(VALID_STATES) == 8


def test_duplicate_hit():
    meds = [
        Medication(name="A", ingredients=["TEST_INGREDIENT_X"]),
        Medication(name="B", ingredients=["TEST_INGREDIENT_X", "TEST_INGREDIENT_Y"]),
    ]
    checks = run_demo_checks(meds)
    dup = next(c for c in checks if "duplicate" in c["check"].casefold())
    assert dup["status"] == "HIT"
    assert dup["status"] in VALID_STATES


def test_no_duplicate_checked_no_hit():
    meds = [
        Medication(name="A", ingredients=["TEST_INGREDIENT_X"]),
        Medication(name="B", ingredients=["TEST_INGREDIENT_Y"]),
    ]
    checks = run_demo_checks(meds)
    dup = next(c for c in checks if "duplicate" in c["check"].casefold())
    assert dup["status"] == "CHECKED_NO_HIT"


def test_missing_ingredients_unverified():
    meds = [Medication(name="A", ingredients=[])]
    checks = run_demo_checks(meds)
    dup = next(c for c in checks if "duplicate" in c["check"].casefold())
    assert dup["status"] == "UNVERIFIED_INPUT"


def test_interaction_not_checked():
    meds = [Medication(name="A", ingredients=["TEST_INGREDIENT_X"])]
    checks = run_demo_checks(meds)
    inter = next(c for c in checks if "interaction" in c["check"].casefold())
    assert inter["status"] == "NOT_CHECKED"


def test_partial_coverage_when_unresolved():
    meds = [Medication(name="A", ingredients=["TEST_INGREDIENT_X"])]
    checks = run_safety_checks(meds, unresolved_product_count=1)
    cov = next(c for c in checks if "coverage" in c["check"].casefold())
    assert cov["status"] == "PARTIAL_COVERAGE"


def test_service_unavailable():
    meds = [Medication(name="A", ingredients=["TEST_INGREDIENT_X"])]
    checks = run_safety_checks(meds, service_available=False)
    assert all(c["status"] == "SERVICE_UNAVAILABLE" for c in checks)


def test_all_states_documented():
    mapping = all_states_reachable_demo()
    assert set(mapping.keys()) == set(VALID_STATES)


def test_resolve_exact():
    r = resolve_drug("Demo Product A")
    assert r.state == "RESOLVED"
    assert any(i["name"] == "TEST_INGREDIENT_X" for i in r.ingredients)


def test_resolve_ambiguous_product_c():
    r = resolve_drug("Demo Product C")
    assert r.state == "UNVERIFIED_INPUT"
    assert len(r.candidates) >= 2


def test_intent_classification():
    assert classify_intent("check this prescription for duplicate ingredients") == "medication_review"
    assert classify_intent("What does the assessment section workflow say?") == "clinical_reference"


def test_medication_pipeline_end_to_end():
    result = run_medication_review_pipeline(["Demo Product A", "Demo Product B"])
    assert result["pipeline"] == "medication_review"
    assert len(result["checks"]) >= 3
    statuses = {c["status"] for c in result["checks"]}
    assert statuses <= set(VALID_STATES)


def test_retrieval_finds_demo_corpus():
    hits = search_evidence("assessment section workflow")
    assert len(hits) >= 1
    gate = evidence_sufficiency_gate("assessment section workflow", hits)
    assert gate["sufficient"] is True
