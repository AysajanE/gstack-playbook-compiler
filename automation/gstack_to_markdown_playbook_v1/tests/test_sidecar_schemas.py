from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from automation.gstack_to_markdown_playbook_v1.author_context import build_author_context
from automation.gstack_to_markdown_playbook_v1.ir_models import GstackPlanIR, ImplementationTask
from automation.gstack_to_markdown_playbook_v1.row_author import build_author_trace
from automation.gstack_to_markdown_playbook_v1.row_models import CandidateRow, CandidateRowsBundle
from automation.gstack_to_markdown_playbook_v1.validators import (
    validate_author_context_payload,
    validate_author_trace_payload,
    validate_repair_trace_payload,
)


class SidecarSchemasTest(unittest.TestCase):
    def test_author_context_trace_and_repair_trace_match_schemas(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            ir = GstackPlanIR(
                compiled_at="2026-05-21T00:00:00+00:00",
                implementation_tasks=[
                    ImplementationTask(
                        task="Add the mood API endpoint",
                        phase="Backend",
                        files=["src/api/mood.py"],
                    )
                ],
            )
            context = build_author_context(ir=ir, repo_root=root)
            row = CandidateRow(
                step_id="01",
                phase="Backend",
                action="Implement the mood API endpoint.",
                why_now="This is the approved backend task.",
                owner_type="agent",
                prerequisites="none",
                repo_surfaces=[],
                deliverable=["src/api/mood.py"],
                exit_criteria="src/api/mood.py exists.",
                allowed_write_roots=["src/api"],
                requires_red_green=True,
                required_verification_commands=["python -m pytest"],
                notes=["source_task: task_001"],
            )
            trace = build_author_trace(
                row_author="fake",
                prompt="prompt",
                bundle=CandidateRowsBundle(rows=[row]),
                author_context=context,
            )
            repair_trace = {
                "schema_version": "row_repair_trace_v1",
                "prompt_sha256": "0" * 64,
                "raw_model_output_sha256": "1" * 64,
                "model_stderr_sha256": "",
                "model_stderr_excerpt": "",
            }

        self.assertEqual(validate_author_context_payload(context), [])
        self.assertEqual(validate_author_trace_payload(trace), [])
        self.assertEqual(validate_repair_trace_payload(repair_trace), [])


if __name__ == "__main__":
    unittest.main()
