from __future__ import annotations

import unittest

from automation.gstack_to_markdown_playbook_v1.row_models import CandidateRow, CandidateRowsBundle
from automation.gstack_to_markdown_playbook_v1.validators import validate, validate_report_payload


def _row(**overrides) -> CandidateRow:
    data = {
        "step_id": "01",
        "phase": "docs",
        "action": "Write a release note",
        "why_now": "Needed before launch.",
        "owner_type": "operator",
        "prerequisites": "none",
        "repo_surfaces": ["docs/gstack/source.md"],
        "deliverable": ["docs/releases/release.md"],
        "exit_criteria": "Release note exists.",
        "allowed_write_roots": ["docs/releases"],
        "requires_red_green": False,
        "required_verification_artifacts": ["docs/releases/release.md"],
    }
    data.update(overrides)
    return CandidateRow(**data)


class ValidatePathsTest(unittest.TestCase):
    def _codes(self, row: CandidateRow) -> set[str]:
        report = validate(CandidateRowsBundle(rows=[row]))
        return {err["code"] for err in report["errors"]}

    def test_dot_prefixed_forbidden_roots_are_errors(self) -> None:
        codes = self._codes(_row(allowed_write_roots=[".local"]))
        self.assertIn("FORBIDDEN_WRITE_ROOT", codes)

    def test_forbidden_deliverables_are_errors(self) -> None:
        codes = self._codes(_row(
            deliverable=[".env.local"],
            allowed_write_roots=["docs/releases"],
        ))
        self.assertIn("FORBIDDEN_PATH", codes)

    def test_pipe_characters_are_errors(self) -> None:
        codes = self._codes(_row(action="Write alpha | beta note"))
        self.assertIn("PIPE_IN_CELL", codes)

    def test_bare_docs_root_is_allowed_for_docs_only_rows(self) -> None:
        report = validate(CandidateRowsBundle(rows=[_row(allowed_write_roots=["docs"])]))
        self.assertEqual(report["status"], "pass")

    def test_bare_docs_root_is_rejected_for_behavioral_rows(self) -> None:
        codes = self._codes(_row(
            phase="backend",
            action="Add API implementation",
            deliverable=["docs/generated/api.py"],
            allowed_write_roots=["docs"],
            requires_red_green=True,
            required_verification_commands=["python -m pytest tests/test_api.py"],
            required_verification_artifacts=[],
        ))
        self.assertIn("BARE_DOCS_ROOT_FOR_NON_DOCS_ROW", codes)

    def test_validation_report_matches_bundled_schema(self) -> None:
        report = validate(CandidateRowsBundle(rows=[_row()]))

        self.assertEqual(report["repair_attempts"], 0)
        self.assertEqual(validate_report_payload(report), [])


if __name__ == "__main__":
    unittest.main()
