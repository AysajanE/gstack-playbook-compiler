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

    def _warning_codes(self, row: CandidateRow) -> set[str]:
        report = validate(CandidateRowsBundle(rows=[row]))
        return {warning["code"] for warning in report["warnings"]}

    def test_dot_prefixed_forbidden_roots_are_errors(self) -> None:
        codes = self._codes(_row(allowed_write_roots=[".local"]))
        self.assertIn("FORBIDDEN_WRITE_ROOT", codes)

    def test_forbidden_deliverables_are_errors(self) -> None:
        codes = self._codes(_row(
            deliverable=[".env.local"],
            allowed_write_roots=["docs/releases"],
        ))
        self.assertIn("FORBIDDEN_PATH", codes)

    def test_parent_escape_paths_are_errors(self) -> None:
        codes = self._codes(_row(deliverable=["../secrets.txt"]))
        self.assertIn("FORBIDDEN_PATH", codes)

    def test_parent_escape_write_roots_are_errors(self) -> None:
        codes = self._codes(_row(
            deliverable=["docs/releases/release.md"],
            allowed_write_roots=["../docs"],
        ))
        self.assertIn("FORBIDDEN_WRITE_ROOT", codes)

    def test_bare_test_root_is_rejected(self) -> None:
        codes = self._codes(_row(
            phase="backend",
            deliverable=["test/test_api.py"],
            allowed_write_roots=["test"],
            requires_red_green=True,
            required_verification_commands=["python -m pytest test/test_api.py"],
            required_verification_artifacts=[],
        ))
        self.assertIn("SUSPICIOUS_BROAD_WRITE_ROOT", codes)

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

    def test_destructive_verification_commands_are_errors(self) -> None:
        codes = self._codes(_row(
            phase="backend",
            deliverable=["src/api/mood.py"],
            allowed_write_roots=["src/api"],
            requires_red_green=True,
            required_verification_commands=["rm -rf ."],
            required_verification_artifacts=[],
        ))
        self.assertIn("UNSAFE_VERIFICATION_COMMAND", codes)

    def test_docs_only_destructive_verification_command_is_error(self) -> None:
        codes = self._codes(_row(
            requires_red_green=False,
            required_verification_commands=["rm -rf ."],
        ))
        self.assertIn("UNSAFE_VERIFICATION_COMMAND", codes)

    def test_shell_chaining_in_verification_commands_is_error(self) -> None:
        codes = self._codes(_row(
            phase="backend",
            deliverable=["src/api/mood.py"],
            allowed_write_roots=["src/api"],
            requires_red_green=True,
            required_verification_commands=["python -m pytest tests/test_api.py && rm -rf ."],
            required_verification_artifacts=[],
        ))
        self.assertIn("UNSAFE_VERIFICATION_COMMAND", codes)

    def test_unknown_verification_command_is_warning(self) -> None:
        warnings = self._warning_codes(_row(
            phase="backend",
            deliverable=["src/api/mood.py"],
            allowed_write_roots=["src/api"],
            requires_red_green=True,
            required_verification_commands=["custom-check src/api/mood.py"],
            required_verification_artifacts=[],
        ))
        self.assertIn("UNKNOWN_VERIFICATION_COMMAND", warnings)

    def test_manual_gate_requires_reason_and_evidence(self) -> None:
        codes = self._codes(_row(manual_gate="security_review"))
        self.assertIn("MANUAL_GATE_WITHOUT_REASON", codes)
        self.assertIn("MANUAL_GATE_WITHOUT_EVIDENCE", codes)

    def test_external_check_requires_dependencies(self) -> None:
        codes = self._codes(_row(external_check="human_supplied_evidence_required"))
        self.assertIn("EXTERNAL_CHECK_WITHOUT_DEPENDENCIES", codes)

    def test_external_dependencies_without_check_are_warnings(self) -> None:
        warnings = self._warning_codes(_row(external_dependencies=["Stripe dashboard"]))
        self.assertIn("EXTERNAL_DEPENDENCIES_WITHOUT_CHECK", warnings)

    def test_prereq_range_requires_every_intermediate_step(self) -> None:
        rows = [
            _row(step_id="01"),
            _row(step_id="02", prerequisites="01"),
            _row(step_id="04", prerequisites="02-04"),
        ]

        report = validate(CandidateRowsBundle(rows=rows))

        codes = {err["code"] for err in report["errors"]}
        self.assertIn("PREREQ_LIST_UNDEFINED", codes)

    def test_prereq_range_must_be_increasing(self) -> None:
        codes = self._codes(_row(step_id="02", prerequisites="03-01"))
        self.assertIn("PREREQ_RANGE_ORDER", codes)

    def test_validation_report_matches_bundled_schema(self) -> None:
        report = validate(CandidateRowsBundle(rows=[_row()]))

        self.assertEqual(report["repair_attempts"], 0)
        self.assertEqual(validate_report_payload(report), [])


if __name__ == "__main__":
    unittest.main()
