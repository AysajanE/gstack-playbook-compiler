from __future__ import annotations

import unittest

from automation.gstack_to_markdown_playbook_v1.verification_command_policy import (
    validate_verification_command,
)


class VerificationCommandPolicyTest(unittest.TestCase):
    def test_allowed_prefix_requires_command_boundary(self) -> None:
        findings = validate_verification_command("pytestevil tests/test_api.py")

        self.assertIn("UNKNOWN_VERIFICATION_COMMAND", {finding.code for finding in findings})

    def test_python_module_prefix_requires_command_boundary(self) -> None:
        findings = validate_verification_command("python -m pytestx tests/test_api.py")

        self.assertIn("UNKNOWN_VERIFICATION_COMMAND", {finding.code for finding in findings})

    def test_single_ampersand_is_unsafe(self) -> None:
        findings = validate_verification_command(
            "python -m pytest tests/test_api.py & rm -rf ."
        )

        self.assertIn("UNSAFE_VERIFICATION_COMMAND", {finding.code for finding in findings})


if __name__ == "__main__":
    unittest.main()
