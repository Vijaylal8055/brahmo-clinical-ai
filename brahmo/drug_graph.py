"""Synthetic drug identity graph (demo only).

Maps a small set of fictional brand strings to ingredients / product dimensions.
Never use as a real formulary. Ambiguous inputs stay unresolved.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from brahmo.contracts import DrugResolutionResult, ResolutionState

# Synthetic catalogue — fictional products only
DRUG_CATALOGUE: Dict[str, Dict[str, Any]] = {
    "demo-product-a": {
        "product_id": "SYN-PROD-001",
        "brand": "Demo Product A",
        "manufacturer": "Synthetic Labs",
        "ingredients": [
            {"ingredient_id": "SYN-ING-X", "name": "TEST_INGREDIENT_X", "strength": "500", "unit": "mg"}
        ],
        "dosage_form": "tablet",
        "route": "oral",
        "release_type": "immediate",
        "aliases": ["demo product a", "demoproducta", "dpa"],
    },
    "demo-product-b": {
        "product_id": "SYN-PROD-002",
        "brand": "Demo Product B",
        "manufacturer": "Synthetic Labs",
        "ingredients": [
            {"ingredient_id": "SYN-ING-X", "name": "TEST_INGREDIENT_X", "strength": "250", "unit": "mg"},
            {"ingredient_id": "SYN-ING-Y", "name": "TEST_INGREDIENT_Y", "strength": "100", "unit": "mg"},
        ],
        "dosage_form": "tablet",
        "route": "oral",
        "release_type": "immediate",
        "aliases": ["demo product b", "demoproductb", "dpb"],
    },
    "demo-product-c-250": {
        "product_id": "SYN-PROD-003A",
        "brand": "Demo Product C",
        "manufacturer": "Synthetic Pharma",
        "ingredients": [
            {"ingredient_id": "SYN-ING-Z", "name": "TEST_INGREDIENT_Z", "strength": "250", "unit": "mg"}
        ],
        "dosage_form": "tablet",
        "route": "oral",
        "release_type": "immediate",
        "aliases": ["demo product c 250", "dpc 250"],
    },
    "demo-product-c-500": {
        "product_id": "SYN-PROD-003B",
        "brand": "Demo Product C",
        "manufacturer": "Synthetic Pharma",
        "ingredients": [
            {"ingredient_id": "SYN-ING-Z", "name": "TEST_INGREDIENT_Z", "strength": "500", "unit": "mg"}
        ],
        "dosage_form": "tablet",
        "route": "oral",
        "release_type": "immediate",
        "aliases": ["demo product c 500", "dpc 500"],
    },
}

MAPPING_VERSION = "synthetic-drug-map-v0.2"


def _normalize(text: str) -> str:
    return " ".join(text.casefold().split())


def resolve_drug(query: str) -> DrugResolutionResult:
    """Resolve a brand / product string against the synthetic catalogue.

    Exact alias match → RESOLVED.
    Multiple products share brand without strength → CANDIDATES / UNVERIFIED_INPUT.
    No match → NOT_FOUND.
    """
    q = _normalize(query)
    if not q:
        return DrugResolutionResult(
            query=query,
            state=ResolutionState.UNVERIFIED_INPUT.value,
            product_ids=[],
            ingredients=[],
            match_method="empty",
            mapping_version=MAPPING_VERSION,
            provenance=[],
            message="Empty product string cannot be resolved.",
        )

    exact: List[Dict[str, Any]] = []
    fuzzy: List[Dict[str, Any]] = []

    for key, prod in DRUG_CATALOGUE.items():
        aliases = [_normalize(a) for a in prod["aliases"]] + [_normalize(prod["brand"])]
        if q in aliases or q == _normalize(prod["brand"]):
            exact.append(prod)
        elif any(q in a or a in q for a in aliases):
            fuzzy.append(prod)

    if len(exact) == 1:
        p = exact[0]
        return DrugResolutionResult(
            query=query,
            state=ResolutionState.RESOLVED.value,
            product_ids=[p["product_id"]],
            ingredients=list(p["ingredients"]),
            match_method="exact_alias",
            mapping_version=MAPPING_VERSION,
            provenance=[f"catalogue:{p['product_id']}"],
            message=f"Resolved to {p['brand']} ({p['product_id']}).",
        )

    if len(exact) > 1:
        return DrugResolutionResult(
            query=query,
            state=ResolutionState.UNVERIFIED_INPUT.value,
            product_ids=[p["product_id"] for p in exact],
            ingredients=[],
            match_method="ambiguous_exact",
            mapping_version=MAPPING_VERSION,
            provenance=[f"catalogue:{p['product_id']}" for p in exact],
            candidates=[
                {
                    "product_id": p["product_id"],
                    "brand": p["brand"],
                    "strength": p["ingredients"][0].get("strength") if p["ingredients"] else None,
                    "unit": p["ingredients"][0].get("unit") if p["ingredients"] else None,
                    "ingredients": [i["name"] for i in p["ingredients"]],
                }
                for p in exact
            ],
            message=(
                "Multiple products match this brand string with different strengths/ingredients. "
                "Clinician selection required; no automatic resolution."
            ),
        )

    if fuzzy:
        return DrugResolutionResult(
            query=query,
            state=ResolutionState.CANDIDATES.value,
            product_ids=[p["product_id"] for p in fuzzy],
            ingredients=[],
            match_method="fuzzy_alias",
            mapping_version=MAPPING_VERSION,
            provenance=[f"catalogue:{p['product_id']}" for p in fuzzy],
            candidates=[
                {
                    "product_id": p["product_id"],
                    "brand": p["brand"],
                    "ingredients": [i["name"] for i in p["ingredients"]],
                }
                for p in fuzzy
            ],
            message="Fuzzy candidates only; not treated as resolved identity.",
        )

    return DrugResolutionResult(
        query=query,
        state=ResolutionState.NOT_FOUND.value,
        product_ids=[],
        ingredients=[],
        match_method="none",
        mapping_version=MAPPING_VERSION,
        provenance=[],
        message="No synthetic catalogue match. Identity remains unresolved.",
    )


def decompose_fdc(resolved: List[DrugResolutionResult]) -> List[Dict[str, Any]]:
    """Expand resolved products to ingredient tokens for downstream checks."""
    ingredients: List[Dict[str, Any]] = []
    for r in resolved:
        if r.state != ResolutionState.RESOLVED.value:
            continue
        for ing in r.ingredients:
            ingredients.append(
                {
                    "product_id": r.product_ids[0] if r.product_ids else None,
                    "ingredient_id": ing.get("ingredient_id"),
                    "name": ing.get("name"),
                    "strength": ing.get("strength"),
                    "unit": ing.get("unit"),
                    "source_query": r.query,
                }
            )
    return ingredients
