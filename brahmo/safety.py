"""Deterministic medication-safety rail (demo only).

Implements the eight-state contract. No LLM is used in this path.
Coverage is intentionally narrow and disclosed.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Dict, List

VALID_STATES = (
    "HIT",
    "CHECKED_NO_HIT",
    "PARTIAL_COVERAGE",
    "UNVERIFIED_INPUT",
    "NOT_CHECKED",
    "DATA_EXPIRED",
    "SOURCE_CONFLICT",
    "SERVICE_UNAVAILABLE",
)

RULE_VERSION = "demo-rules-v0.2"
COVERAGE_MANIFEST = {
    "duplicate_ingredient_token": {
        "supported": True,
        "description": "Exact string match on synthetic ingredient tokens only.",
    },
    "drug_interaction": {
        "supported": False,
        "description": "No interaction dataset or reviewed interaction rules installed.",
    },
    "allergy": {
        "supported": False,
        "description": "No allergy data or reviewed allergy rules installed.",
    },
    "pregnancy": {
        "supported": False,
        "description": "No pregnancy/lactation rule set installed.",
    },
}


@dataclass
class Medication:
    name: str
    ingredients: List[str]


def _status_or_raise(status: str) -> str:
    if status not in VALID_STATES:
        raise ValueError(f"Invalid safety status: {status}")
    return status


def run_demo_checks(medications: List[Medication]) -> List[Dict[str, Any]]:
    """Legacy entry used by tests and simple UI path."""
    return run_safety_checks(medications)


def run_safety_checks(
    medications: List[Medication],
    *,
    unresolved_product_count: int = 0,
    service_available: bool = True,
) -> List[Dict[str, Any]]:
    """Deterministic checks over synthetic ingredient tokens."""
    if not service_available:
        return [
            {
                "check": check_name,
                "status": _status_or_raise("SERVICE_UNAVAILABLE"),
                "message": "Safety service dependency unavailable.",
                "rule_ids": [],
                "rule_version": RULE_VERSION,
                "details": {},
            }
            for check_name in (
                "Exact duplicate ingredient token (demo only)",
                "Drug interaction",
                "Allergy",
                "Coverage completeness",
            )
        ]

    missing = [m.name for m in medications if not m.ingredients]
    seen: Dict[str, List[str]] = defaultdict(list)
    for med in medications:
        for ingredient in med.ingredients:
            seen[ingredient.casefold()].append(med.name)

    duplicates = [
        {"ingredient_token": ingredient, "items": names}
        for ingredient, names in sorted(seen.items())
        if len(names) > 1
    ]

    if missing:
        duplicate_status = "UNVERIFIED_INPUT"
        duplicate_message = (
            "At least one item has no ingredient token. This check cannot establish "
            "complete ingredient coverage."
        )
    elif duplicates:
        duplicate_status = "HIT"
        duplicate_message = (
            "Exact duplicate synthetic ingredient token(s) detected. This is a test-fixture "
            "signal only, not a clinical conclusion."
        )
    else:
        duplicate_status = "CHECKED_NO_HIT"
        duplicate_message = (
            "No exact duplicate tokens were found among the supplied synthetic ingredient lists. "
            "This does not mean the medicines are safe."
        )

    if unresolved_product_count > 0 or missing:
        coverage_status = "PARTIAL_COVERAGE"
        coverage_message = (
            f"{unresolved_product_count} product(s) unresolved and/or missing ingredients. "
            "Duplicate-ingredient review is incomplete. No all-clear has been issued."
        )
    else:
        coverage_status = "CHECKED_NO_HIT"
        coverage_message = (
            "All supplied products had ingredient tokens for the narrow demo check. "
            "This is not a comprehensive safety assessment."
        )

    return [
        {
            "check": "Exact duplicate ingredient token (demo only)",
            "status": _status_or_raise(duplicate_status),
            "message": duplicate_message,
            "rule_ids": ["DEMO-DUP-001"] if duplicates else [],
            "rule_version": RULE_VERSION,
            "details": {"duplicates": duplicates, "items_missing_ingredients": missing},
        },
        {
            "check": "Drug interaction",
            "status": _status_or_raise("NOT_CHECKED"),
            "message": COVERAGE_MANIFEST["drug_interaction"]["description"],
            "rule_ids": [],
            "rule_version": RULE_VERSION,
            "details": {"coverage": COVERAGE_MANIFEST["drug_interaction"]},
        },
        {
            "check": "Allergy",
            "status": _status_or_raise("NOT_CHECKED"),
            "message": COVERAGE_MANIFEST["allergy"]["description"],
            "rule_ids": [],
            "rule_version": RULE_VERSION,
            "details": {"coverage": COVERAGE_MANIFEST["allergy"]},
        },
        {
            "check": "Coverage completeness",
            "status": _status_or_raise(coverage_status),
            "message": coverage_message,
            "rule_ids": [],
            "rule_version": RULE_VERSION,
            "details": {
                "unresolved_product_count": unresolved_product_count,
                "coverage_manifest": COVERAGE_MANIFEST,
            },
        },
    ]


def all_states_reachable_demo() -> Dict[str, str]:
    return {
        "HIT": "Duplicate token present",
        "CHECKED_NO_HIT": "No duplicate among complete inputs",
        "PARTIAL_COVERAGE": "Unresolved product present",
        "UNVERIFIED_INPUT": "Missing ingredient list",
        "NOT_CHECKED": "Interaction dataset absent",
        "DATA_EXPIRED": "Rule set past validity (simulated)",
        "SOURCE_CONFLICT": "Two concurrent sources disagree (simulated)",
        "SERVICE_UNAVAILABLE": "Dependency down",
    }
