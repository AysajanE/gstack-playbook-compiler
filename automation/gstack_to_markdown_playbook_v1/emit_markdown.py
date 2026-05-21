"""Stage 4: deterministic markdown_playbook_v1 emitter.

Python owns this stage absolutely. The LLM never writes markdown table cells.

The column order here matches plan-orchestrator/examples/launch_demo_playbook/playbook.md
for maximum parser compatibility. Order is technically not load-bearing for the parser, but
matching the example reduces review friction.
"""

from __future__ import annotations

from .ir_models import GstackPlanIR
from .provenance import render_header
from .row_models import CandidateRow, CandidateRowsBundle, PhaseDetail


COLUMN_ORDER = [
    "step_id",
    "phase",
    "action",
    "why_now",
    "owner_type",
    "prerequisites",
    "repo_surfaces",
    "deliverable",
    "exit_criteria",
    "allowed_write_roots",
    "requires_red_green",
    "manual_gate",
    "manual_gate_reason",
    "manual_gate_evidence",
    "external_check",
    "external_dependencies",
    "consult_paths",
    "required_verification_commands",
    "required_verification_artifacts",
    "notes",
]

LIST_COLUMNS = {
    "repo_surfaces",
    "deliverable",
    "manual_gate_evidence",
    "external_dependencies",
    "consult_paths",
    "required_verification_commands",
    "required_verification_artifacts",
    "notes",
}
ALLOWED_WRITE_ROOTS_COLUMN = "allowed_write_roots"
PATH_COLUMNS = {"repo_surfaces", "deliverable", "consult_paths", "required_verification_artifacts"}


def _escape_cell(value: str) -> str:
    """Collapse cells to one row and assert validation already rejected pipes."""
    if "|" in value:
        raise ValueError("Pipe characters are forbidden in markdown table cells.")
    return value.replace("\n", " ").replace("\r", " ").strip()


def _render_path_token(p: str) -> str:
    """Path cells wrap each entry in backticks (mirroring the launch demo)."""
    p = p.strip()
    if not p:
        return ""
    if p.startswith("`") and p.endswith("`"):
        return p
    return f"`{p}`"


def _render_cell(row: CandidateRow, column: str) -> str:
    value = getattr(row, column)
    if column == "requires_red_green":
        return "true" if value else "false"
    if column == ALLOWED_WRITE_ROOTS_COLUMN:
        # Contract: semicolon-separated, plain (no backticks) repo-relative roots.
        return _escape_cell("; ".join(value))
    if column in PATH_COLUMNS:
        if not value:
            return ""
        return _escape_cell("; ".join(_render_path_token(p) for p in value))
    if column in LIST_COLUMNS:
        if not value:
            return ""
        return _escape_cell("; ".join(value))
    return _escape_cell(str(value))


def _render_table(rows: list[CandidateRow]) -> str:
    header = "| " + " | ".join(COLUMN_ORDER) + " |"
    sep = "| " + " | ".join("---" for _ in COLUMN_ORDER) + " |"
    body_lines = []
    for row in rows:
        cells = [_render_cell(row, col) for col in COLUMN_ORDER]
        body_lines.append("| " + " | ".join(cells) + " |")
    return "\n".join([header, sep, *body_lines])


def _slugify(text: str) -> str:
    out = []
    prev_dash = False
    for ch in text.lower():
        if ch.isalnum():
            out.append(ch)
            prev_dash = False
        elif not prev_dash:
            out.append("-")
            prev_dash = True
    return "".join(out).strip("-") or "section"


def _default_phase_details(rows: list[CandidateRow]) -> list[PhaseDetail]:
    seen: set[str] = set()
    out: list[PhaseDetail] = []
    for row in rows:
        if row.phase in seen:
            continue
        seen.add(row.phase)
        out.append(
            PhaseDetail(
                phase_slug=_slugify(row.phase),
                title=row.phase.title(),
                body=f"Execute rows tagged `{row.phase}` in the order defined by the execution table.",
            )
        )
    return out or [
        PhaseDetail(
            phase_slug="execution",
            title="Execution",
            body="Execute the ordered rows in section 2.",
        )
    ]


def emit_playbook_markdown(
    *,
    ir: GstackPlanIR,
    bundle: CandidateRowsBundle,
    human_approved_by: str = "",
    compiled_by: str = "gstack_to_markdown_playbook_v1",
) -> str:
    """Render the final markdown_playbook_v1 string."""
    parts: list[str] = []
    parts.append(render_header(
        ir=ir,
        compiled_by=compiled_by,
        human_approved_by=human_approved_by,
    ))
    parts.append("")

    plan_context = bundle.support_sections.plan_context.strip()
    if not plan_context:
        plan_context = ir.product_goal.strip() or "(plan context not authored)"
    parts.append("## 1. Plan Context")
    parts.append("")
    parts.append(plan_context)
    parts.append("")

    parts.append("## 2. Ordered Execution Plan")
    parts.append("")
    parts.append(_render_table(bundle.rows))
    parts.append("")

    parts.append("## 3. Phase Details")
    parts.append("")
    phase_details = bundle.support_sections.phase_details or _default_phase_details(bundle.rows)
    for idx, pd in enumerate(phase_details, start=1):
        parts.append(f"### 3.{idx} {pd.title}")
        parts.append("")
        parts.append(pd.body.strip())
        parts.append("")

    parts.append("## 4. Shared Guidance")
    parts.append("")
    if bundle.support_sections.shared_guidance:
        for idx, g in enumerate(bundle.support_sections.shared_guidance, start=1):
            parts.append(f"### 4.{idx} {g.title}")
            parts.append("")
            parts.append(g.body.strip())
            parts.append("")
    else:
        parts.append("### 4.1 Scope Rules")
        parts.append("")
        parts.append("Respect each row's `allowed_write_roots`, prerequisites, and verification requirements.")
        parts.append("")

    parts.append("## 5. Risks And Contingencies")
    parts.append("")
    parts.append(
        bundle.support_sections.risks_and_contingencies.strip()
        or "No additional risk hints were extracted. Stop at manual gates, external blockers, or failed verification."
    )
    parts.append("")

    parts.append("## 6. Immediate Next Actions")
    parts.append("")
    parts.append(
        bundle.support_sections.immediate_next_actions.strip()
        or "Run PO `list-items` and `doctor --playbook --format json` before supervised execution."
    )
    parts.append("")

    return "\n".join(parts).rstrip() + "\n"
