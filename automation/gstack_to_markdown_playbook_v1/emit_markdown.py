"""Stage 4: deterministic markdown_playbook_v1 emitter.

Python owns this stage absolutely. The LLM never writes markdown table cells.

The column order here matches plan-orchestrator/examples/launch_demo_playbook/playbook.md
for maximum parser compatibility. Order is technically not load-bearing for the parser, but
matching the example reduces review friction.
"""

from __future__ import annotations

from .ir_models import GstackPlanIR
from .provenance import render_header
from .row_models import CandidateRow, CandidateRowsBundle


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
    """Collapse cells to one row.

    plan-orchestrator's current markdown parser splits on raw pipe characters
    and does not understand escaped pipes. Validation rejects pipes before this
    point; the replacement below is a final defensive guard.
    """
    return value.replace("|", "/").replace("\n", " ").replace("\r", " ").strip()


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

    if bundle.support_sections.phase_details:
        parts.append("## 3. Phase Details")
        parts.append("")
        for idx, pd in enumerate(bundle.support_sections.phase_details, start=1):
            parts.append(f"### 3.{idx} {pd.title}")
            parts.append("")
            parts.append(pd.body.strip())
            parts.append("")

    if bundle.support_sections.shared_guidance:
        parts.append("## 4. Shared Guidance")
        parts.append("")
        for idx, g in enumerate(bundle.support_sections.shared_guidance, start=1):
            parts.append(f"### 4.{idx} {g.title}")
            parts.append("")
            parts.append(g.body.strip())
            parts.append("")

    if bundle.support_sections.risks_and_contingencies.strip():
        parts.append("## 5. Risks And Contingencies")
        parts.append("")
        parts.append(bundle.support_sections.risks_and_contingencies.strip())
        parts.append("")

    if bundle.support_sections.immediate_next_actions.strip():
        parts.append("## 6. Immediate Next Actions")
        parts.append("")
        parts.append(bundle.support_sections.immediate_next_actions.strip())
        parts.append("")

    return "\n".join(parts).rstrip() + "\n"
