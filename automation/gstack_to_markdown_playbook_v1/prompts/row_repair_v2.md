# Role

You are repairing `po_candidate_rows_v1` JSON for `gstack_to_markdown_playbook_v1`.

Your previous candidate failed deterministic validation.

Return a complete replacement JSON object. Do not return a patch. Do not include prose.

# Rules

1. Fix every error in the validation report.
2. Preserve rows that have no issue unless a prerequisite or step renumbering fix requires changing them.
3. Do not invent paths.
4. Do not widen write roots to make validation pass.
5. Do not remove required verification from behavioral rows.
6. Do not solve missing facts by adding fake manual gates.
7. If a row cannot be made executable from the supplied context, remove that row and add a `compiler_warnings` entry explaining the missing fact.
8. Output valid JSON only.

# Original gstack_plan_ir_v1

{{IR_JSON}}

# Original row_author_context_v1

{{AUTHOR_CONTEXT_JSON}}

# Failed candidate po_candidate_rows_v1

{{FAILED_ROWS_JSON}}

# Deterministic validation report

{{VALIDATION_REPORT_JSON}}

# Additional quality-gate findings

{{QUALITY_FINDINGS_JSON}}

# Return complete po_candidate_rows_v1 JSON only
