"""Provenance header for emitted markdown_playbook_v1 files."""

from __future__ import annotations

from .ir_models import GstackPlanIR


def render_header(
    *,
    ir: GstackPlanIR,
    compiled_by: str = "gstack_to_markdown_playbook_v1",
    human_approved_by: str = "",
    compiled_at: str | None = None,
) -> str:
    when = compiled_at or ir.compiled_at
    src_lines = []
    for s in ir.source_artifacts:
        src_lines.append(f"  - kind: {s.kind}, path: {s.path}, sha256: {s.sha256}")
    src_block = "\n".join(src_lines) if src_lines else "  - (none)"
    return (
        "<!--\n"
        f"playbook_contract: markdown_playbook_v1\n"
        f"compiled_by: {compiled_by}\n"
        f"compiled_at: {when}\n"
        f"human_approved_by: {human_approved_by}\n"
        f"source_artifacts:\n{src_block}\n"
        "-->\n"
    )
