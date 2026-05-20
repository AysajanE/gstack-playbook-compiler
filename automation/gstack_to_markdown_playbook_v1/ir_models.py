"""Python dataclasses for gstack_plan_ir_v1.

Mirror schemas/gstack_plan_ir_v1.schema.json. Use to_dict/from_dict for JSON round-trip.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from . import IR_SCHEMA_ID


@dataclass
class SourceArtifact:
    kind: str
    path: str
    sha256: str
    byte_size: int


@dataclass
class ImplementationTask:
    task: str
    phase: str
    files: list[str] = field(default_factory=list)
    verify: list[str] = field(default_factory=list)
    notes: str = ""


@dataclass
class StackProfile:
    languages: list[str] = field(default_factory=list)
    test_runners: list[str] = field(default_factory=list)
    build_tools: list[str] = field(default_factory=list)
    package_managers: list[str] = field(default_factory=list)


@dataclass
class GstackPlanIR:
    compiled_at: str
    source_artifacts: list[SourceArtifact] = field(default_factory=list)
    product_goal: str = ""
    non_goals: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    recommended_approach: str = ""
    implementation_tasks: list[ImplementationTask] = field(default_factory=list)
    candidate_repo_paths: list[str] = field(default_factory=list)
    verification_hints: list[str] = field(default_factory=list)
    manual_gate_hints: list[str] = field(default_factory=list)
    external_dependency_hints: list[str] = field(default_factory=list)
    risk_hints: list[str] = field(default_factory=list)
    stack_profile: StackProfile | None = None
    schema_version: str = IR_SCHEMA_ID

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if self.stack_profile is None:
            data.pop("stack_profile", None)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GstackPlanIR":
        src = [SourceArtifact(**s) for s in data.get("source_artifacts", [])]
        tasks = [ImplementationTask(**t) for t in data.get("implementation_tasks", [])]
        stack_raw = data.get("stack_profile")
        stack = StackProfile(**stack_raw) if stack_raw else None
        return cls(
            compiled_at=data["compiled_at"],
            source_artifacts=src,
            product_goal=data.get("product_goal", ""),
            non_goals=list(data.get("non_goals", [])),
            constraints=list(data.get("constraints", [])),
            recommended_approach=data.get("recommended_approach", ""),
            implementation_tasks=tasks,
            candidate_repo_paths=list(data.get("candidate_repo_paths", [])),
            verification_hints=list(data.get("verification_hints", [])),
            manual_gate_hints=list(data.get("manual_gate_hints", [])),
            external_dependency_hints=list(data.get("external_dependency_hints", [])),
            risk_hints=list(data.get("risk_hints", [])),
            stack_profile=stack,
        )
