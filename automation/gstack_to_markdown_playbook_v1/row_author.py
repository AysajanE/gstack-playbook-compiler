"""Stage 2: candidate row authoring.

Pluggable interface. The CLI picks the implementation via `--row-author <name>`:

- `stub` (default in --dry-run): deterministic synthesis from IR. No LLM. Safe for tests.
- `claude` / `codex`: real LLM (not implemented in v0; raises NotImplementedError).

The contract is a callable:

    def author(ir: GstackPlanIR) -> CandidateRowsBundle

The stub author produces N rows where N = number of implementation_tasks (or 1 if none).
Every stub-authored bundle adds a leading `compiler_warnings` entry naming the synthetic
origin, so the human notices before running PO.
"""

from __future__ import annotations

from typing import Callable

from .ir_models import GstackPlanIR
from .row_models import (
    CandidateRow,
    CandidateRowsBundle,
    PhaseDetail,
    SharedGuidanceEntry,
    SupportSections,
)


RowAuthor = Callable[[GstackPlanIR], CandidateRowsBundle]
BEHAVIORAL_SUFFIXES = (
    ".py", ".pyi", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".java", ".kt",
    ".swift", ".dart", ".rb", ".php", ".cs", ".cpp", ".c", ".h", ".hpp", ".sql",
    ".sh", ".yaml", ".yml", ".toml", ".json",
)


def _phase_to_slug(phase: str) -> str:
    return phase.lower().replace(" ", "-").replace("_", "-").strip("-") or "phase"


def _pick_verification_commands(ir: GstackPlanIR, *, behavioral: bool) -> list[str]:
    if not behavioral:
        return []
    if ir.stack_profile is None:
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


def _narrow_roots_for_task(task_files: list[str], fallback: str = "docs/playbooks") -> list[str]:
    """Choose 1-3 narrow allowed_write_roots from task files.

    Strategy: take parent directories of declared files; drop duplicates; cap at 3.
    """
    seen: list[str] = []
    for f in task_files:
        f = f.strip("`").lstrip("./")
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


def _safe_repo_relative_sources(ir: GstackPlanIR) -> list[str]:
    """Return repo-relative paths suitable for use in row repo_surfaces.

    Uses ir.candidate_repo_paths (extracted from authored markdown — already repo-relative
    by construction) and never the source_artifacts.path values (which may be absolute).
    """
    relative = [p for p in ir.candidate_repo_paths if not p.startswith(("/", "~"))]
    return relative or ["docs/gstack/.placeholder"]


def stub_author(ir: GstackPlanIR) -> CandidateRowsBundle:
    """Deterministic stub: one row per implementation_task, plus a baseline scaffold row.

    Marks the first row with manual_gate='signoff' so the human reviews before PO runs.
    """
    rows: list[CandidateRow] = []

    # Always start with a scope-lock row (docs-only) so the playbook has at least one item.
    scope_paths = _safe_repo_relative_sources(ir)
    rows.append(CandidateRow(
        step_id="01",
        phase="scope lock",
        action="Confirm the approved gstack design + brief are committed as repo-tracked playbook inputs and capture the provenance header.",
        why_now="Lock the inputs the compiler used so the playbook is reproducible from tracked sources.",
        owner_type="operator",
        prerequisites="none",
        repo_surfaces=scope_paths,
        deliverable=["docs/playbooks/.scope-lock.md"],
        exit_criteria="Playbook header + scope-lock note are present and committed.",
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
    ))

    step_index = 2
    if not ir.implementation_tasks:
        # No autoplan/eng-review rows; emit a single placeholder row so the table is non-empty.
        rows.append(CandidateRow(
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
            notes=["compiler-stub: needs /autoplan input."],
        ))
        bundle = CandidateRowsBundle(rows=rows)
        bundle.compiler_warnings.append(
            "compiler-stub: ir.implementation_tasks is empty. Provide /autoplan output to author real rows."
        )
        bundle.support_sections = _baseline_support(ir, rows)
        return bundle

    for task in ir.implementation_tasks:
        files = task.files or []
        narrow = _narrow_roots_for_task(files, fallback="docs")
        behavioral = bool(files) and any(
            f.endswith(BEHAVIORAL_SUFFIXES) or f.rsplit("/", 1)[-1] in {"Dockerfile", "docker-compose.yml", "docker-compose.yaml"}
            for f in files
        )
        verify_cmds = task.verify or _pick_verification_commands(ir, behavioral=behavioral)
        repo_surfaces = files or scope_paths
        deliverable = files or [f"{narrow[0]}/.placeholder"]
        rows.append(CandidateRow(
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
        ))
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
        phase_details.append(PhaseDetail(
            phase_slug=_phase_to_slug(r.phase),
            title=r.phase.title(),
            body=f"Phase {r.phase!r}: executes the steps tagged with this phase value in section 2.",
        ))
    shared_guidance = []
    if ir.constraints:
        shared_guidance.append(SharedGuidanceEntry(
            title="Constraints",
            body="\n".join(f"- {c}" for c in ir.constraints[:10]),
        ))
    if ir.non_goals:
        shared_guidance.append(SharedGuidanceEntry(
            title="Non-Goals",
            body="\n".join(f"- {g}" for g in ir.non_goals[:10]),
        ))
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


_AUTHORS: dict[str, RowAuthor] = {"stub": stub_author}


def get_author(name: str) -> RowAuthor:
    if name in _AUTHORS:
        return _AUTHORS[name]
    if name in {"claude", "codex"}:
        raise NotImplementedError(
            f"row_author {name!r} is not implemented in v0. Use --row-author stub for now."
        )
    raise ValueError(f"unknown row_author {name!r}; available: {sorted(_AUTHORS)}")
