from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from automation.gstack_to_markdown_playbook_v1.ir_models import StackProfile
from automation.gstack_to_markdown_playbook_v1.verification_policy import (
    infer_verification_commands,
    is_behavioral_path,
    is_test_path,
    task_text_looks_behavioral,
)


class VerificationPolicyTest(unittest.TestCase):
    def test_explicit_verification_wins(self) -> None:
        with TemporaryDirectory() as tmp:
            commands = infer_verification_commands(
                task_files=["src/api/mood.py"],
                task_verify=["python -m pytest tests/test_mood_api.py"],
                stack_profile=StackProfile(languages=["python"], test_runners=["pytest"]),
                repo_root=Path(tmp),
            )

        self.assertEqual(commands, ["python -m pytest tests/test_mood_api.py"])

    def test_infers_targeted_python_test_when_stack_supports_pytest(self) -> None:
        with TemporaryDirectory() as tmp:
            commands = infer_verification_commands(
                task_files=["src/api/mood.py", "tests/test_mood_api.py"],
                task_verify=[],
                stack_profile=StackProfile(languages=["python"], test_runners=["pytest"]),
                repo_root=Path(tmp),
            )

        self.assertEqual(commands, ["python -m pytest tests/test_mood_api.py"])

    def test_fails_closed_when_no_command_can_be_inferred(self) -> None:
        with TemporaryDirectory() as tmp:
            commands = infer_verification_commands(
                task_files=["src/api/mood.py"],
                task_verify=[],
                stack_profile=None,
                repo_root=Path(tmp),
            )

        self.assertEqual(commands, [])

    def test_behavioral_classification(self) -> None:
        self.assertTrue(is_behavioral_path("src/api/mood.py"))
        self.assertTrue(is_test_path("tests/test_mood_api.py"))
        self.assertTrue(task_text_looks_behavioral("Add the mood API endpoint", "Backend"))
        self.assertFalse(is_behavioral_path("docs/gstack/design.md"))


if __name__ == "__main__":
    unittest.main()
