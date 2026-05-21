"""Stage 2: candidate row authoring.

Real authoring is a bounded LLM JSON call surrounded by deterministic Python
context building, validation, and optional one-shot repair. The legacy stub
author remains available for dry-run/scaffold workflows.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .author_context import build_author_context
from .ir_models import GstackPlanIR
from .llm_clients import (
    ExternalCommandJsonClient,
    JsonModelClient,
    ModelClientError,
    parse_json_object_strict,
    render_prompt,
)
from .path_policy import normalize_repo_path
from .row_models import (
    CandidateRow,
    CandidateRowsBundle,
    PhaseDetail,
    SharedGuidanceEntry,
    SupportSections,
)
from .validators import validate_rows_payload
from .verification_policy import task_requires_red_green


@dataclass
class RowAuthorOptions:
    timeout_sec: int = 180
    repair_enabled: bool = True
    max_rows: int = 25
    allow_planning_gap_rows: bool = False
    temperature: float = 0.0


@dataclass
class RowAuthorResult:
    bundle: CandidateRowsBundle
    trace: dict[str, Any]
    author_input: dict[str, Any]
    repair_attempted: bool = False
    raw_model_output: str = ""


class RowAuthorError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        author_input: dict[str, Any] | None = None,
        trace: dict[str, Any] | None = None,
        bundle: CandidateRowsBundle | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.author_input = author_input or {}
        self.trace = trace or {
            "schema_version": "row_author_trace_v1",
            "row_author": "unknown",
            "repair_attempted": False,
            "source_task_to_rows": {},
            "row_to_source_tasks": {},
            "invented_paths": [],
            "warnings": [],
        }
        self.bundle = bundle


class RowAuthor(Protocol):
    def author(
        self,
        *,
        ir: GstackPlanIR,
        repo_root: Path,
        options: RowAuthorOptions,
    ) -> RowAuthorResult:
        ...


DEFAULT_AUTHOR_COMMANDS = {
    "claude": os.environ.get("KEEL_ROW_AUTHOR_CLAUDE_CMD", "claude -p"),
    "codex": os.environ.get("KEEL_ROW_AUTHOR_CODEX_CMD", "codex exec -"),
}


def _phase_to_slug(phase: str) -> str:
    return phase.lower().replace(" ", "-").replace("_", "-").strip("-") or "phase"


def _safe_repo_relative_sources(ir: GstackPlanIR) -> list[str]:
    relative = [p for p in ir.candidate_repo_paths if not p.startswith(("/", "~"))]
    return relative or ["docs/gstack/.placeholder"]


def _narrow_roots_for_task(task_files: list[str], fallback: str = "docs/playbooks") -> list[str]:
    seen: list[str] = []
    for f in task_files:
        f = normalize_repo_path(f)
        if not f:
            continue
        if "/" in f:
            parent = f.rsplit("/", 1)[0]
        else:
            continue
        if parent in {"src", "tests", "test"}:
            parent = f
        if parent and parent not in seen:
            seen.append(parent)
        if len(seen) >= 3:
            break
    return seen or [fallback]


def _pick_verification_commands(ir: GstackPlanIR, *, behavioral: bool) -> list[str]:
    if not behavioral or ir.stack_profile is None:
        return []
    cmds: list[str] = []
    if "python" in ir.stack_profile.languages:
        cmds.append("python -m pytest")
    if "javascript" in ir.stack_profile.languages or "typescript" in ir.stack_profile.languages:
        if "typecheck" in ir.stack_profile.test_runners:
            cmds.append("npm run typecheck")
        if "npm-test" in ir.stack_profile.test_runners:
            cmds.append("npm run test")
    if "go" in ir.stack_profile.languages:
        cmds.append("go test ./...")
    if "rust" in ir.stack_profile.languages:
        cmds.append("cargo test")
    if "java" in ir.stack_profile.languages:
        if "maven-test" in ir.stack_profile.test_runners:
            cmds.append("mvn test")
        elif "gradle-test" in ir.stack_profile.test_runners:
            cmds.append("./gradlew test")
    if "swift" in ir.stack_profile.languages:
        cmds.append("swift test")
    return cmds


def stub_author(ir: GstackPlanIR) -> CandidateRowsBundle:
    """Deterministic scaffold author retained for dry-run tests."""
    rows: list[CandidateRow] = []
    scope_paths = _safe_repo_relative_sources(ir)
    rows.append(
        CandidateRow(
            step_id="01",
            phase="scope lock",
            action="Confirm the approved gstack design and brief are committed as repo-tracked playbook inputs and capture the provenance header.",
            why_now="Lock the inputs the compiler used so the playbook is reproducible from tracked sources.",
            owner_type="operator",
            prerequisites="none",
            repo_surfaces=scope_paths,
            deliverable=["docs/playbooks/.scope-lock.md"],
            exit_criteria="Playbook header and scope-lock note are present and committed.",
            allowed_write_roots=["docs/playbooks"],
            requires_red_green=False,
            manual_gate="signoff",
            manual_gate_reason="Human confirms the compiled playbook is the approved execution source before any item runs.",
            manual_gate_evidence=["signed scope-lock note"],
            required_verification_artifacts=["docs/playbooks/.scope-lock.md"],
            notes=[
                "compiler-stub: replace with LLM-authored rows before any real PO run.",
                "this row is intentionally docs-only and gated.",
            ],
        )
    )

    step_index = 2
    if not ir.implementation_tasks:
        rows.append(
            CandidateRow(
                step_id=f"{step_index:02d}",
                phase="placeholder",
                action="Provide /autoplan and /plan-eng-review output so the compiler can synthesize real PO rows.",
                why_now="The compiler cannot generate behavioral rows without reviewed implementation tasks.",
                owner_type="operator",
                prerequisites="01",
                repo_surfaces=scope_paths,
                deliverable=["docs/gstack/.autoplan-required.md"],
                exit_criteria="Reviewed implementation task list is committed and re-fed to the compiler.",
                allowed_write_roots=["docs/gstack"],
                requires_red_green=False,
                manual_gate="signoff",
                manual_gate_reason="Cannot proceed without a reviewed task list.",
                manual_gate_evidence=["reviewed implementation task list"],
                notes=["compiler-stub: needs /autoplan input."],
            )
        )
        bundle = CandidateRowsBundle(rows=rows)
        bundle.compiler_warnings.append(
            "compiler-stub: ir.implementation_tasks is empty. Provide /autoplan output to author real rows."
        )
        bundle.support_sections = _baseline_support(ir, rows)
        return bundle

    for task in ir.implementation_tasks:
        files = task.files or []
        narrow = _narrow_roots_for_task(files, fallback="docs")
        behavioral = task_requires_red_green(files)
        verify_cmds = task.verify or _pick_verification_commands(ir, behavioral=behavioral)
        repo_surfaces = files or scope_paths
        deliverable = files or [f"{narrow[0]}/.placeholder"]
        rows.append(
            CandidateRow(
                step_id=f"{step_index:02d}",
                phase=task.phase or "implementation",
                action=task.task,
                why_now=f"Required by recommended approach: {ir.recommended_approach[:120] + '...' if len(ir.recommended_approach) > 120 else ir.recommended_approach or 'unspecified'}",
                owner_type="operator",
                prerequisites="01" if step_index == 2 else f"{step_index - 1:02d}",
                repo_surfaces=repo_surfaces,
                deliverable=deliverable,
                exit_criteria=(task.notes or task.task)[:240],
                allowed_write_roots=narrow,
                requires_red_green=behavioral,
                manual_gate="none",
                required_verification_commands=verify_cmds,
                required_verification_artifacts=deliverable if not behavioral else [],
                notes=["compiler-stub: synthesized from implementation_tasks; verify before running PO."],
            )
        )
        step_index += 1

    bundle = CandidateRowsBundle(rows=rows)
    bundle.compiler_warnings.append(
        "compiler-stub: rows were synthesized deterministically from IR. Replace with LLM-authored rows for real runs."
    )
    bundle.support_sections = _baseline_support(ir, rows)
    return bundle


def _baseline_support(ir: GstackPlanIR, rows: list[CandidateRow]) -> SupportSections:
    plan_context = ir.product_goal or "Plan context not provided by parser."
    phase_details: list[PhaseDetail] = []
    seen_phases: set[str] = set()
    for r in rows:
        if r.phase in seen_phases:
            continue
        seen_phases.add(r.phase)
        phase_details.append(
            PhaseDetail(
                phase_slug=_phase_to_slug(r.phase),
                title=r.phase.title(),
                body=f"Phase {r.phase!r}: executes the steps tagged with this phase value in section 2.",
            )
        )
    shared_guidance = []
    if ir.constraints:
        shared_guidance.append(
            SharedGuidanceEntry(
                title="Constraints",
                body="\n".join(f"- {c}" for c in ir.constraints[:10]),
            )
        )
    if ir.non_goals:
        shared_guidance.append(
            SharedGuidanceEntry(
                title="Non-Goals",
                body="\n".join(f"- {g}" for g in ir.non_goals[:10]),
            )
        )
    risks = "\n".join(f"- {r}" for r in ir.risk_hints[:10]) if ir.risk_hints else "No risk hints extracted."
    return SupportSections(
        plan_context=plan_context,
        phase_details=phase_details,
        shared_guidance=shared_guidance,
        risks_and_contingencies=risks,
        immediate_next_actions=(
            "Validate via `plan-orchestrator list-items --playbook ...` and "
            "`plan-orchestrator doctor --playbook ... --format json` before running."
        ),
    )


class StubRowAuthor:
    name = "stub"
    model_client: JsonModelClient | None = None

    def author(
        self,
        *,
        ir: GstackPlanIR,
        repo_root: Path,
        options: RowAuthorOptions,
    ) -> RowAuthorResult:
        bundle = stub_author(ir)
        author_context = build_author_context(
            ir=ir,
            repo_root=repo_root,
            max_rows=options.max_rows,
        )
        return RowAuthorResult(
            bundle=bundle,
            trace={
                "schema_version": "row_author_trace_v1",
                "row_author": "stub",
                "repair_attempted": False,
                "source_task_to_rows": {},
                "row_to_source_tasks": {},
                "invented_paths": [],
                "warnings": list(bundle.compiler_warnings),
            },
            author_input=author_context,
        )

    def __call__(self, ir: GstackPlanIR) -> CandidateRowsBundle:
        return stub_author(ir)


def _source_task_ids(row: CandidateRow) -> list[str]:
    text = " ".join(row.notes)
    return sorted(set(re.findall(r"source_task:\s*(task_[0-9]{3})", text)))


def _trace_for_bundle(
    *,
    row_author: str,
    prompt: str,
    bundle: CandidateRowsBundle,
    author_context: dict[str, Any],
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    source_task_to_rows: dict[str, list[str]] = {}
    row_to_source_tasks: dict[str, list[str]] = {}
    for row in bundle.rows:
        ids = _source_task_ids(row)
        if ids:
            row_to_source_tasks[row.step_id] = ids
        for task_id in ids:
            source_task_to_rows.setdefault(task_id, []).append(row.step_id)
    known_paths = set(author_context.get("known_paths", []))
    authored_paths = []
    for row in bundle.rows:
        authored_paths.extend(row.repo_surfaces)
        authored_paths.extend(row.deliverable)
        authored_paths.extend(row.consult_paths)
        authored_paths.extend(row.required_verification_artifacts)
    invented = sorted({normalize_repo_path(path) for path in authored_paths if normalize_repo_path(path) not in known_paths})
    return {
        "schema_version": "row_author_trace_v1",
        "row_author": row_author,
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "repair_attempted": False,
        "source_task_to_rows": source_task_to_rows,
        "row_to_source_tasks": row_to_source_tasks,
        "invented_paths": invented,
        "warnings": warnings or [],
    }


def _add_model_trace_hashes(
    *,
    trace: dict[str, Any],
    model_client: JsonModelClient,
    raw_model_output: str,
) -> None:
    client_stderr = getattr(model_client, "last_stderr", "")
    trace["raw_model_output_sha256"] = hashlib.sha256(
        raw_model_output.encode("utf-8")
    ).hexdigest()
    trace["model_stderr_sha256"] = (
        hashlib.sha256(client_stderr.encode("utf-8")).hexdigest()
        if client_stderr else ""
    )
    trace["model_stderr_excerpt"] = client_stderr[-1000:] if client_stderr else ""


def build_author_trace(
    *,
    row_author: str,
    prompt: str,
    bundle: CandidateRowsBundle,
    author_context: dict[str, Any],
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    return _trace_for_bundle(
        row_author=row_author,
        prompt=prompt,
        bundle=bundle,
        author_context=author_context,
        warnings=warnings,
    )


def _planning_gap_bundle(ir: GstackPlanIR, author_context: dict[str, Any]) -> CandidateRowsBundle:
    rows: list[CandidateRow] = []
    source_paths = author_context.get("source_artifact_paths", []) or ["docs/gstack"]
    for idx, card in enumerate(author_context.get("task_cards", []), start=1):
        task_id = str(card["task_id"])
        deliverable = f"docs/gstack/{task_id}-planning-gap.md"
        rows.append(
            CandidateRow(
                step_id=f"{idx:02d}",
                phase="planning gap",
                action=f"Write a revised autoplan request for {task_id} with concrete file paths and verification.",
                why_now="The compiler cannot safely author behavioral PO rows without declared files and tests.",
                owner_type="operator",
                prerequisites="none" if idx == 1 else f"{idx - 1:02d}",
                repo_surfaces=list(source_paths),
                deliverable=[deliverable],
                exit_criteria=f"{deliverable} exists and names the missing concrete files and verification commands.",
                allowed_write_roots=["docs/gstack"],
                requires_red_green=False,
                required_verification_artifacts=[deliverable],
                notes=[f"source_task: {task_id}", "planning-gap-row"],
            )
        )
    bundle = CandidateRowsBundle(rows=rows)
    for card in author_context.get("task_cards", []):
        bundle.compiler_warnings.append(
            f"AUTHOR_TASK_MISSING_PATHS: {card['task_id']} lacks concrete file paths; emitted planning-gap row only."
        )
    bundle.support_sections = _baseline_support(ir, rows)
    return bundle


def _allow_planning_gap_paths(author_context: dict[str, Any], bundle: CandidateRowsBundle) -> None:
    known_paths = author_context.setdefault("known_paths", [])
    known_roots = author_context.setdefault("known_write_roots", [])
    ledger = author_context.setdefault("path_ledger", [])
    if "docs/gstack" not in known_roots:
        known_roots.append("docs/gstack")
    for row in bundle.rows:
        for path in row.deliverable:
            p = normalize_repo_path(path)
            if p not in known_paths:
                known_paths.append(p)
            if not any(entry.get("path") == p for entry in ledger):
                ledger.append(
                    {
                        "path": p,
                        "status": "generated_planning_gap",
                        "kind": "doc",
                        "mentioned_by": ["planning_gap"],
                        "safe_as_deliverable": True,
                        "safe_as_repo_surface": False,
                    }
                )


class LLMJsonRowAuthor:
    def __init__(self, *, name: str, model_client: JsonModelClient) -> None:
        self.name = name
        self.model_client = model_client

    def author(
        self,
        *,
        ir: GstackPlanIR,
        repo_root: Path,
        options: RowAuthorOptions,
    ) -> RowAuthorResult:
        author_context = build_author_context(
            ir=ir,
            repo_root=repo_root,
            max_rows=options.max_rows,
        )
        fatal_context_findings = [
            finding for finding in author_context.get("context_findings", [])
            if finding.get("severity") == "error"
        ]
        if fatal_context_findings:
            message = "; ".join(
                str(finding.get("message", "context finding"))
                for finding in fatal_context_findings
            )
            raise RowAuthorError(
                "AUTHOR_CONTEXT_CONFLICT",
                "Step 2 cannot author rows because source constraints conflict with "
                f"implementation tasks: {message}",
                author_input=author_context,
            )
        if not ir.implementation_tasks:
            raise RowAuthorError(
                "AUTHOR_NO_IMPLEMENTATION_TASKS",
                "Step 2 cannot author executable rows because the IR contains no implementation_tasks.",
                author_input=author_context,
            )
        missing_path_cards = [
            card for card in author_context.get("task_cards", []) if card.get("missing_declared_files")
        ]
        if missing_path_cards:
            if options.allow_planning_gap_rows:
                bundle = _planning_gap_bundle(ir, author_context)
                _allow_planning_gap_paths(author_context, bundle)
                trace = _trace_for_bundle(
                    row_author=f"{self.name}:planning-gap",
                    prompt="",
                    bundle=bundle,
                    author_context=author_context,
                    warnings=list(bundle.compiler_warnings),
                )
                return RowAuthorResult(bundle=bundle, trace=trace, author_input=author_context)
            missing = ", ".join(str(card["task_id"]) for card in missing_path_cards)
            raise RowAuthorError(
                "AUTHOR_TASK_MISSING_PATHS",
                f"Step 2 cannot author executable rows because these tasks lack concrete file paths: {missing}.",
                author_input=author_context,
            )

        prompt = render_prompt(
            "row_author_v2.md",
            {
                "IR_JSON": json.dumps(ir.to_dict(), indent=2, sort_keys=True),
                "AUTHOR_CONTEXT_JSON": json.dumps(author_context, indent=2, sort_keys=True),
            },
        )
        try:
            raw = self.model_client.complete_json(
                prompt=prompt,
                timeout_sec=options.timeout_sec,
            )
            payload = parse_json_object_strict(raw)
            schema_errors = validate_rows_payload(payload)
            if schema_errors:
                details = "; ".join(err["message"] for err in schema_errors[:3])
                raise ValueError(f"po_candidate_rows_v1 schema validation failed: {details}")
            bundle = CandidateRowsBundle.from_dict(payload)
        except (ModelClientError, ValueError, TypeError) as exc:
            raise RowAuthorError(
                "AUTHOR_MODEL_OUTPUT_INVALID",
                f"row author model output was invalid: {exc}",
                author_input=author_context,
            ) from exc

        trace = _trace_for_bundle(
            row_author=self.name,
            prompt=prompt,
            bundle=bundle,
            author_context=author_context,
        )
        _add_model_trace_hashes(
            trace=trace,
            model_client=self.model_client,
            raw_model_output=raw,
        )
        return RowAuthorResult(
            bundle=bundle,
            trace=trace,
            author_input=author_context,
            raw_model_output=raw,
        )


def get_author(
    name: str,
    *,
    command: str = "",
    cwd: Path | None = None,
    inherit_env: bool = False,
) -> RowAuthor:
    if name == "stub":
        return StubRowAuthor()
    if name == "external-json":
        if not command:
            raise NotImplementedError("--row-author external-json requires --row-author-command")
        return LLMJsonRowAuthor(
            name=name,
            model_client=ExternalCommandJsonClient(command, cwd=cwd, inherit_env=inherit_env),
        )
    if name in {"claude", "codex"}:
        resolved = command or DEFAULT_AUTHOR_COMMANDS[name]
        return LLMJsonRowAuthor(
            name=name,
            model_client=ExternalCommandJsonClient(resolved, cwd=cwd, inherit_env=inherit_env),
        )
    raise ValueError("unknown row_author {!r}; available: {}".format(
        name,
        ["stub", "claude", "codex", "external-json"],
    ))
