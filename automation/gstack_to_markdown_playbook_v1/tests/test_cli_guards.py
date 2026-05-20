from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from automation.gstack_to_markdown_playbook_v1.cli import main


class CliGuardsTest(unittest.TestCase):
    def _design(self, root: Path) -> Path:
        design = root / "docs" / "gstack" / "demo-office-hours.md"
        design.parent.mkdir(parents=True)
        design.write_text(
            """
# Design

## Problem Statement

Build a small reviewed artifact.
""",
            encoding="utf-8",
        )
        return design

    def test_non_dry_run_stub_fails_without_explicit_allow(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = root / "docs" / "playbooks" / "demo.playbook.md"

            rc = main([
                "compile",
                "--repo-root", str(root),
                "--design", str(self._design(root)),
                "--out", str(out),
                "--skip-po-verify", "unit test",
            ])

            self.assertEqual(rc, 2)
            self.assertFalse(out.exists())

    def test_non_dry_run_warnings_fail_without_explicit_allow(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = root / "docs" / "playbooks" / "demo.playbook.md"

            rc = main([
                "compile",
                "--repo-root", str(root),
                "--design", str(self._design(root)),
                "--out", str(out),
                "--allow-stub-output",
                "--skip-po-verify", "unit test",
            ])

            self.assertEqual(rc, 3)
            self.assertFalse(out.exists())

    def test_non_dry_run_stub_can_emit_only_with_explicit_overrides(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = root / "docs" / "playbooks" / "demo.playbook.md"

            rc = main([
                "compile",
                "--repo-root", str(root),
                "--design", str(self._design(root)),
                "--out", str(out),
                "--allow-stub-output",
                "--allow-warnings", "unit test scaffold",
                "--skip-po-verify", "unit test",
            ])

            self.assertEqual(rc, 0)
            self.assertTrue(out.exists())
            meta = json.loads(out.with_name("demo.playbook.meta.json").read_text(encoding="utf-8"))
            self.assertEqual(meta["row_author"], "stub")
            self.assertEqual(meta["warning_override_reason"], "unit test scaffold")
            self.assertEqual(meta["po_contract_verification"]["status"], "skipped")

    def test_output_path_must_be_under_docs_playbooks(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = root / "plans" / "demo.playbook.md"

            rc = main([
                "compile",
                "--repo-root", str(root),
                "--design", str(self._design(root)),
                "--out", str(out),
                "--dry-run",
            ])

            self.assertEqual(rc, 2)
            self.assertFalse(out.exists())

    def test_verify_with_po_requires_plan_orchestrator_root_before_emit(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = root / "docs" / "playbooks" / "demo.playbook.md"

            rc = main([
                "compile",
                "--repo-root", str(root),
                "--design", str(self._design(root)),
                "--out", str(out),
                "--dry-run",
                "--verify-with-po",
            ])

            self.assertEqual(rc, 2)
            self.assertFalse(out.exists())

    def test_verify_with_po_and_skip_po_verify_are_mutually_exclusive(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = root / "docs" / "playbooks" / "demo.playbook.md"

            rc = main([
                "compile",
                "--repo-root", str(root),
                "--design", str(self._design(root)),
                "--out", str(out),
                "--dry-run",
                "--verify-with-po",
                "--skip-po-verify", "unit test",
            ])

            self.assertEqual(rc, 2)
            self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
