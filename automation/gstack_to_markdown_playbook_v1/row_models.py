"""Python dataclasses for po_candidate_rows_v1.

The dataclasses use canonical Python types. The schema accepts a slightly looser shape
during JSON round-trip; converters normalize empty optional lists/strings.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from . import ROWS_SCHEMA_ID

VALID_MANUAL_GATES = {
    "none", "signoff", "approval", "operator_confirmation",
    "security_review", "presenter_review", "custom",
}
VALID_EXTERNAL_CHECKS = {"none", "human_supplied_evidence_required"}


@dataclass
class CandidateRow:
    step_id: str
    phase: str
    action: str
    why_now: str
    owner_type: str
    prerequisites: str
    repo_surfaces: list[str]
    deliverable: list[str]
    exit_criteria: str
    allowed_write_roots: list[str]
    requires_red_green: bool
    manual_gate: str = "none"
    manual_gate_reason: str = ""
    manual_gate_evidence: list[str] = field(default_factory=list)
    external_check: str = "none"
    external_dependencies: list[str] = field(default_factory=list)
    consult_paths: list[str] = field(default_factory=list)
    required_verification_commands: list[str] = field(default_factory=list)
    required_verification_artifacts: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class PhaseDetail:
    phase_slug: str
    title: str
    body: str


@dataclass
class SharedGuidanceEntry:
    title: str
    body: str


@dataclass
class SupportSections:
    plan_context: str = ""
    phase_details: list[PhaseDetail] = field(default_factory=list)
    shared_guidance: list[SharedGuidanceEntry] = field(default_factory=list)
    risks_and_contingencies: str = ""
    immediate_next_actions: str = ""


@dataclass
class CandidateRowsBundle:
    rows: list[CandidateRow] = field(default_factory=list)
    support_sections: SupportSections = field(default_factory=SupportSections)
    compiler_warnings: list[str] = field(default_factory=list)
    schema_version: str = ROWS_SCHEMA_ID

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "rows": [asdict(r) for r in self.rows],
            "support_sections": asdict(self.support_sections),
            "compiler_warnings": list(self.compiler_warnings),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CandidateRowsBundle":
        rows = [CandidateRow(**r) for r in data.get("rows", [])]
        sup_raw = data.get("support_sections", {})
        support = SupportSections(
            plan_context=sup_raw.get("plan_context", ""),
            phase_details=[PhaseDetail(**p) for p in sup_raw.get("phase_details", [])],
            shared_guidance=[SharedGuidanceEntry(**g) for g in sup_raw.get("shared_guidance", [])],
            risks_and_contingencies=sup_raw.get("risks_and_contingencies", ""),
            immediate_next_actions=sup_raw.get("immediate_next_actions", ""),
        )
        return cls(
            rows=rows,
            support_sections=support,
            compiler_warnings=list(data.get("compiler_warnings", [])),
        )
