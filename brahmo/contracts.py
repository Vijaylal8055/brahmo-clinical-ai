"""Versioned integration contracts (demo schemas).

These mirror the architecture document's Scribe, Patient-context, Drug-resolution,
and Safety-check contracts. All fields are synthetic / illustrative.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional
from enum import Enum


class FieldStatus(str, Enum):
    PRESENT = "present"
    MISSING = "missing"
    UNCERTAIN = "uncertain"
    CONFLICTING = "conflicting"
    KNOWN = "known"
    UNKNOWN = "unknown"
    NOT_COLLECTED = "not_collected"
    STALE = "stale"


class ResolutionState(str, Enum):
    RESOLVED = "RESOLVED"
    CANDIDATES = "CANDIDATES"
    UNVERIFIED_INPUT = "UNVERIFIED_INPUT"
    NOT_FOUND = "NOT_FOUND"


@dataclass
class MedicationEntity:
    raw_string: str
    brand: Optional[str] = None
    manufacturer: Optional[str] = None
    strength: Optional[str] = None
    unit: Optional[str] = None
    dosage_form: Optional[str] = None
    route: Optional[str] = None
    ingredients: List[str] = field(default_factory=list)
    field_status: str = FieldStatus.PRESENT.value
    source_span: Optional[str] = None
    confidence: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ScribePayload:
    schema_version: str
    source_system: str
    encounter_ref: str
    captured_at: str
    tenant_id: str
    entities: List[MedicationEntity]
    transcript_refs: List[str] = field(default_factory=list)
    provenance: str = "demo"

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["entities"] = [e.to_dict() if hasattr(e, "to_dict") else e for e in self.entities]
        return d


@dataclass
class PatientField:
    value: Any
    unit: Optional[str] = None
    observed_at: Optional[str] = None
    source: Optional[str] = None
    status: str = FieldStatus.UNKNOWN.value

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PatientContextSnapshot:
    snapshot_id: str
    schema_version: str
    tenant_id: str
    encounter_ref: str
    as_of: str
    fields: Dict[str, PatientField]
    authorization_ref: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "schema_version": self.schema_version,
            "tenant_id": self.tenant_id,
            "encounter_ref": self.encounter_ref,
            "as_of": self.as_of,
            "authorization_ref": self.authorization_ref,
            "fields": {k: v.to_dict() for k, v in self.fields.items()},
        }


@dataclass
class DrugResolutionResult:
    query: str
    state: str
    product_ids: List[str]
    ingredients: List[Dict[str, Any]]
    match_method: str
    mapping_version: str
    provenance: List[str]
    candidates: List[Dict[str, Any]] = field(default_factory=list)
    message: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SafetyCheckResult:
    check: str
    status: str
    message: str
    rule_ids: List[str] = field(default_factory=list)
    rule_version: str = "demo-rules-v0"
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
