"""gstack-to-markdown-playbook-v1: conservative compiler scaffold for PO playbooks.

Stages:
    1. parse_gstack       → gstack_plan_ir_v1
    2. row_author         → po_candidate_rows_v1
    3. validators         → compiler_validation_report_v1
    4. emit_markdown      → markdown_playbook_v1

Model-backed row authoring is available through bounded JSON-only external
commands. Python still owns validation, repair limits, and final markdown
emission.
"""

__version__ = "0.1.0"

IR_SCHEMA_ID = "gstack_plan_ir_v1"
ROWS_SCHEMA_ID = "po_candidate_rows_v1"
VALIDATION_REPORT_SCHEMA_ID = "compiler_validation_report_v1"
PLAYBOOK_CONTRACT_ID = "markdown_playbook_v1"
