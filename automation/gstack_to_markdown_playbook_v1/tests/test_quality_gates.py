from __future__ import annotations

import unittest

from automation.gstack_to_markdown_playbook_v1.ir_models import (
    GstackPlanIR,
    ImplementationTask,
)
from automation.gstack_to_markdown_playbook_v1.quality_gates import (
    validate_author_quality,
    warnings_as_compiler_warnings,
)
from automation.gstack_to_markdown_playbook_v1.row_models import (
    CandidateRow,
    CandidateRowsBundle,
)


def _ir() -> GstackPlanIR:
    return GstackPlanIR(
        compiled_at="2026-05-21T00:00:00+00:00",
        implementation_tasks=[
            ImplementationTask(
                task="Add the mood API endpoint",
                phase="Backend",
                files=["src/api/mood.py", "tests/test_mood_api.py"],
            )
        ],
    )


def _context() -> dict:
    return {
        "schema_version": "row_author_context_v1",
        "known_paths": [
            "docs/gstack/design.md",
            "src/api/mood.py",
            "tests/test_mood_api.py",
        ],
        "known_write_roots": ["src/api", "tests/test_mood_api.py"],
        "path_ledger": [
            {
                "path": "docs/gstack/design.md",
                "safe_as_repo_surface": True,
                "safe_as_deliverable": False,
            },
            {
                "path": "src/api/mood.py",
                "safe_as_repo_surface": True,
                "safe_as_deliverable": True,
            },
            {
                "path": "tests/test_mood_api.py",
                "safe_as_repo_surface": True,
                "safe_as_deliverable": True,
            },
        ],
        "task_cards": [{"task_id": "task_001"}],
        "context_findings": [],
    }


def _good_row() -> CandidateRow:
    return CandidateRow(
        step_id="01",
        phase="Backend",
        action="Implement the mood API endpoint and targeted regression test.",
        why_now="This is the approved backend task.",
        owner_type="agent",
        prerequisites="none",
        repo_surfaces=["docs/gstack/design.md", "src/api/mood.py", "tests/test_mood_api.py"],
        deliverable=["src/api/mood.py", "tests/test_mood_api.py"],
        exit_criteria="python -m pytest tests/test_mood_api.py passes and src/api/mood.py exposes the endpoint.",
        allowed_write_roots=["src/api", "tests/test_mood_api.py"],
        requires_red_green=True,
        required_verification_commands=["python -m pytest tests/test_mood_api.py"],
        notes=["source_task: task_001"],
    )


class QualityGatesTest(unittest.TestCase):
    def test_accepts_specific_rows_using_only_ledger_paths(self) -> None:
        quality = validate_author_quality(
            bundle=CandidateRowsBundle(rows=[_good_row()]),
            ir=_ir(),
            author_context=_context(),
        )

        self.assertEqual(quality["status"], "pass")
        self.assertEqual(quality["errors"], [])

    def test_rejects_invented_paths_placeholders_and_uncovered_tasks(self) -> None:
        row = _good_row()
        row.action = "Update code"
        row.deliverable = ["src/api/invented.py"]
        row.allowed_write_roots = ["src/api"]
        row.notes = []

        quality = validate_author_quality(
            bundle=CandidateRowsBundle(rows=[row]),
            ir=_ir(),
            author_context=_context(),
        )

        codes = {finding["code"] for finding in quality["errors"]}
        self.assertIn("AUTHOR_PLACEHOLDER_TEXT", codes)
        self.assertIn("AUTHOR_INVENTED_PATH", codes)
        self.assertIn("AUTHOR_UNCOVERED_TASK", codes)

    def test_turns_quality_warnings_into_compiler_warnings(self) -> None:
        row = _good_row()
        row.required_verification_commands = ["python -m pytest"]

        quality = validate_author_quality(
            bundle=CandidateRowsBundle(rows=[row]),
            ir=_ir(),
            author_context=_context(),
        )

        warnings = warnings_as_compiler_warnings(quality)
        self.assertTrue(any("AUTHOR_TEST_COMMAND_NOT_TARGETED" in item for item in warnings))


if __name__ == "__main__":
    unittest.main()
