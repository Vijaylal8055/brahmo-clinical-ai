"""End-to-end pipeline orchestrator."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from brahmo.drug_graph import resolve_drug, MAPPING_VERSION
from brahmo.safety import run_safety_checks, Medication, RULE_VERSION, COVERAGE_MANIFEST
from brahmo.retrieval import search_evidence, evidence_sufficiency_gate, compose_grounded_answer
from brahmo.audit import write_audit_event


def classify_intent(text: str) -> str:
    t = text.casefold()
    drug_signals = (
        "drug", "medicine", "medication", "brand", "ingredient", "fdc",
        "duplicate", "interaction", "prescription", "rx", "tablet", "dose",
    )
    ref_signals = (
        "guideline", "workflow", "assessment", "section", "protocol",
        "what does", "according to", "recommend", "guidance", "stw",
    )
    drug_score = sum(1 for s in drug_signals if s in t)
    ref_score = sum(1 for s in ref_signals if s in t)
    if drug_score > ref_score and drug_score > 0:
        return "medication_review"
    if ref_score > 0:
        return "clinical_reference"
    if re.search(r"\b(product|brand|ingredient)\b", t):
        return "medication_review"
    return "clinical_reference"


def run_medication_review_pipeline(
    product_lines: List[str],
    *,
    tenant_id: str = "demo-tenant",
    encounter_ref: str = "enc-demo",
) -> Dict[str, Any]:
    resolutions = []
    resolved_meds: List[Medication] = []
    unresolved = 0

    for line in product_lines:
        line = line.strip()
        if not line:
            continue
        if "|" in line:
            name, rest = line.split("|", 1)
            name = name.strip()
            ingredients = [x.strip() for x in rest.split(",") if x.strip()]
            res = resolve_drug(name)
            if ingredients:
                resolved_meds.append(Medication(name=name, ingredients=ingredients))
                resolutions.append(
                    {
                        **res.to_dict(),
                        "override_ingredients": ingredients,
                        "note": "Caller supplied ingredient tokens; identity still shown for transparency.",
                    }
                )
            else:
                if res.state == "RESOLVED":
                    ings = [i["name"] for i in res.ingredients]
                    resolved_meds.append(Medication(name=name, ingredients=ings))
                else:
                    unresolved += 1
                    resolved_meds.append(Medication(name=name, ingredients=[]))
                resolutions.append(res.to_dict())
        else:
            res = resolve_drug(line)
            if res.state == "RESOLVED":
                ings = [i["name"] for i in res.ingredients]
                resolved_meds.append(Medication(name=line, ingredients=ings))
            else:
                unresolved += 1
                resolved_meds.append(Medication(name=line, ingredients=[]))
            resolutions.append(res.to_dict())

    checks = run_safety_checks(resolved_meds, unresolved_product_count=unresolved)

    statuses = {c["status"] for c in checks}
    if "HIT" in statuses:
        event_status = "HIT"
    elif "UNVERIFIED_INPUT" in statuses or "PARTIAL_COVERAGE" in statuses:
        event_status = "PARTIAL"
    elif "SERVICE_UNAVAILABLE" in statuses:
        event_status = "ERROR"
    else:
        event_status = "OK"

    result = {
        "pipeline": "medication_review",
        "tenant_id": tenant_id,
        "encounter_ref": encounter_ref,
        "mapping_version": MAPPING_VERSION,
        "rule_version": RULE_VERSION,
        "coverage_manifest": COVERAGE_MANIFEST,
        "resolutions": resolutions,
        "checks": checks,
        "notice": (
            "Synthetic demo only. Not a clinical assessment. "
            "No all-clear implies universal safety."
        ),
    }
    write_audit_event(
        "medication_review_pipeline",
        {
            "tenant_id": tenant_id,
            "encounter_ref": encounter_ref,
            "input_count": len([ln for ln in product_lines if ln.strip()]),
            "unresolved": unresolved,
            "check_statuses": [c["status"] for c in checks],
        },
        event_status=event_status,
    )
    return result


def run_reference_pipeline(
    question: str,
    *,
    population: Optional[str] = None,
    tenant_id: str = "demo-tenant",
) -> Dict[str, Any]:
    evidence = search_evidence(question, top_k=5)
    gate = evidence_sufficiency_gate(question, evidence, require_population=population)
    composed = compose_grounded_answer(question, evidence, gate)
    event_status = "ABSTAINED" if composed["abstained"] else "GROUNDED"

    result = {
        "pipeline": "clinical_reference",
        "tenant_id": tenant_id,
        "question": question,
        "population_filter": population,
        "evidence_count": len(evidence),
        "gate": gate,
        "answer": composed["answer"],
        "claims": composed["claims"],
        "citations": composed["citations"],
        "abstained": composed["abstained"],
        "coverage_state": composed["coverage_state"],
        "notice": "Demo corpus only. Not clinical guidance.",
    }
    write_audit_event(
        "clinical_reference_pipeline",
        {
            "tenant_id": tenant_id,
            "question": question[:200],
            "evidence_count": len(evidence),
            "sufficient": gate.get("sufficient"),
            "abstained": composed["abstained"],
        },
        event_status=event_status,
    )
    return result


def run_end_to_end(
    user_text: str,
    *,
    product_lines: Optional[List[str]] = None,
    population: Optional[str] = None,
    tenant_id: str = "demo-tenant",
) -> Dict[str, Any]:
    intent = classify_intent(user_text if not product_lines else "medication prescription review")
    if product_lines is not None or intent == "medication_review":
        lines = product_lines if product_lines is not None else [user_text]
        return run_medication_review_pipeline(lines, tenant_id=tenant_id)
    return run_reference_pipeline(user_text, population=population, tenant_id=tenant_id)
