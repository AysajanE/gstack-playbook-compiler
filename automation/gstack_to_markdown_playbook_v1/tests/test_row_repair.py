from __future__ import annotations

import json
import unittest

from automation.gstack_to_markdown_playbook_v1.ir_models import (
    GstackPlanIR,
    ImplementationTask,
)
from automation.gstack_to_markdown_playbook_v1.row_models import (
    CandidateRow,
    CandidateRowsBundle,
)
from automation.gstack_to_markdown_playbook_v1.row_repair import repair_rows


class FakeClient:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.prompts: list[str] = []

    def complete_json(self, *, prompt: str, timeout_sec: int) -> str:
        self.prompts.append(prompt)
        return json.dumps(self.payload)


def _payload() -> dict:
    return {
        "schema_version": "po_candidate_rows_v1",
        "rows": [
            {
                "step_id": "01",
                "phase": "Backend",
                "action": "Implement the mood API endpoint and targeted regression test.",
                "why_now": "This is the approved backend task.",
                "owner_type": "agent",
                "prerequisites": "none",
                "repo_surfaces": ["docs/gstack/design.md", "src/api/mood.py"],
                "deliverable": ["src/api/mood.py", "tests/test_mood_api.py"],
                "exit_criteria": "python -m pytest tests/test_mood_api.py passes.",
                "allowed_write_roots": ["src/api", "tests/test_mood_api.py"],
                "requires_red_green": True,
                "manual_gate": "none",
                "manual_gate_reason": "",
                "manual_gate_evidence": [],
                "external_check": "none",
                "external_dependencies": [],
                "consult_paths": [],
                "required_verification_commands": ["python -m pytest tests/test_mood_api.py"],
                "required_verification_artifacts": [],
                "notes": ["source_task: task_001"],
            }
        ],
        "support_sections": {
            "plan_context": "Build a mood API.",
            "phase_details": [],
            "shared_guidance": [],
            "risks_and_contingencies": "No special risks.",
            "immediate_next_actions": "Run verification.",
        },
        "compiler_warnings": [],
    }


class RowRepairTest(unittest.TestCase):
    def test_repair_prompt_returns_full_replacement_bundle(self) -> None:
        failed = CandidateRowsBundle(
            rows=[
                CandidateRow(
                    step_id="01",
                    phase="Backend",
                    action="Update code",
                    why_now="Task.",
                    owner_type="agent",
                    prerequisites="none",
                    repo_surfaces=["docs/gstack/design.md"],
                    deliverable=["src/api/mood.py"],
                    exit_criteria="Works.",
                    allowed_write_roots=["src"],
                    requires_red_green=False,
                    notes=[],
                )
            ]
        )
        ir = GstackPlanIR(
            compiled_at="2026-05-21T00:00:00+00:00",
            implementation_tasks=[
                ImplementationTask(
                    task="Add the mood API endpoint",
                    phase="Backend",
                    files=["src/api/mood.py", "tests/test_mood_api.py"],
                )
            ],
        )
        client = FakeClient(_payload())

        result = repair_rows(
            ir=ir,
            author_context={"schema_version": "row_author_context_v1"},
            failed_bundle=failed,
            validation_report={"status": "fail", "errors": []},
            quality_findings={"status": "fail", "errors": []},
            model_client=client,
            timeout_sec=10,
        )

        self.assertEqual(result.bundle.rows[0].action, _payload()["rows"][0]["action"])
        self.assertEqual(result.trace["schema_version"], "row_repair_trace_v1")
        self.assertIn("Failed candidate po_candidate_rows_v1", client.prompts[0])


if __name__ == "__main__":
    unittest.main()
