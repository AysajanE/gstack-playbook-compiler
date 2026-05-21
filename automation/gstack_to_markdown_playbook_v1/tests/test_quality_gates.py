from __future__ import annotations

import copy
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


def _second_good_row() -> CandidateRow:
    row = copy.deepcopy(_good_row())
    row.step_id = "02"
    row.prerequisites = "01"
    row.action = "Verify the mood API endpoint regression coverage remains targeted."
    row.exit_criteria = "python -m pytest tests/test_mood_api.py passes after the implementation row."
    return row


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
        self.assertIn("AUTHOR_ACTION_TOO_VAGUE", codes)
        self.assertIn("AUTHOR_INVENTED_PATH", codes)
        self.assertIn("AUTHOR_UNCOVERED_TASK", codes)

    def test_rejects_source_doc_as_deliverable_even_when_known(self) -> None:
        row = _good_row()
        row.deliverable = ["docs/gstack/design.md"]
        row.allowed_write_roots = ["docs/gstack"]
        row.requires_red_green = False
        row.required_verification_commands = []
        row.required_verification_artifacts = ["docs/gstack/design.md"]

        quality = validate_author_quality(
            bundle=CandidateRowsBundle(rows=[row]),
            ir=_ir(),
            author_context=_context(),
        )

        codes = {finding["code"] for finding in quality["errors"]}
        self.assertIn("AUTHOR_UNSAFE_DELIVERABLE_PATH", codes)
        self.assertIn("AUTHOR_INVENTED_PATH", codes)

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

    def test_rejects_more_than_max_authored_rows(self) -> None:
        context = _context()
        context["global_rules"] = {"max_rows": 1}

        quality = validate_author_quality(
            bundle=CandidateRowsBundle(rows=[_good_row(), _second_good_row()]),
            ir=_ir(),
            author_context=context,
        )

        self.assertIn("AUTHOR_TOO_MANY_ROWS", {finding["code"] for finding in quality["errors"]})

    def test_approved_brief_only_allowed_write_root_is_enforced(self) -> None:
        context = _context()
        context["global_rules"] = {
            "max_rows": 25,
            "constrained_allowed_write_roots": ["docs/playbooks"],
        }
        row = _good_row()
        row.allowed_write_roots = ["src/api"]

        quality = validate_author_quality(
            bundle=CandidateRowsBundle(rows=[row]),
            ir=_ir(),
            author_context=context,
        )

        self.assertIn(
            "AUTHOR_WRITE_ROOT_OUTSIDE_APPROVED_CONSTRAINT",
            {finding["code"] for finding in quality["errors"]},
        )

    def test_prereq_range_expands_for_forward_prerequisite_checks(self) -> None:
        row = _good_row()
        row.step_id = "04"
        row.prerequisites = "02-04"

        quality = validate_author_quality(
            bundle=CandidateRowsBundle(rows=[row]),
            ir=_ir(),
            author_context=_context(),
        )

        self.assertIn(
            "AUTHOR_FORWARD_PREREQUISITE",
            {finding["code"] for finding in quality["errors"]},
        )

    def test_action_verb_calibration_accepts_turn_and_scaffold_word(self) -> None:
        row = _good_row()
        row.action = "Turn the release-note scaffold into a reviewed playbook artifact."
        row.exit_criteria = "docs/gstack/design.md exists and the scaffold wording remains scoped."

        quality = validate_author_quality(
            bundle=CandidateRowsBundle(rows=[row]),
            ir=_ir(),
            author_context=_context(),
        )

        self.assertNotIn(
            "AUTHOR_ACTION_TOO_VAGUE",
            {finding["code"] for finding in quality["errors"]},
        )
        self.assertNotIn(
            "AUTHOR_PLACEHOLDER_TEXT",
            {finding["code"] for finding in quality["errors"]},
        )

    def test_database_and_infra_rows_emit_risk_warnings(self) -> None:
        context = _context()
        context["known_paths"].extend(["migrations/001_add_mood.sql", ".github/workflows/ci.yml"])
        context["known_write_roots"].extend(["migrations", ".github/workflows"])
        context["path_ledger"].extend([
            {
                "path": "migrations/001_add_mood.sql",
                "safe_as_repo_surface": False,
                "safe_as_deliverable": True,
            },
            {
                "path": ".github/workflows/ci.yml",
                "safe_as_repo_surface": False,
                "safe_as_deliverable": True,
            },
        ])
        db_row = _good_row()
        db_row.deliverable = ["migrations/001_add_mood.sql"]
        db_row.allowed_write_roots = ["migrations"]
        db_row.required_verification_commands = ["python -m pytest tests/test_mood_api.py"]
        infra_row = _second_good_row()
        infra_row.deliverable = [".github/workflows/ci.yml"]
        infra_row.allowed_write_roots = [".github/workflows"]

        quality = validate_author_quality(
            bundle=CandidateRowsBundle(rows=[db_row, infra_row]),
            ir=_ir(),
            author_context=context,
        )

        warning_codes = {finding["code"] for finding in quality["warnings"]}
        self.assertIn("AUTHOR_DB_WITHOUT_MIGRATION_VERIFICATION", warning_codes)
        self.assertIn("AUTHOR_DB_WITHOUT_MANUAL_GATE", warning_codes)
        self.assertIn("AUTHOR_INFRA_WITHOUT_MANUAL_GATE", warning_codes)


if __name__ == "__main__":
    unittest.main()
