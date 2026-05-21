from __future__ import annotations

import json
import sys
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

    def _autoplan(self, root: Path) -> Path:
        autoplan = root / "docs" / "gstack" / "demo-autoplan.md"
        autoplan.write_text(
            """
# Autoplan

## Implementation Tasks

### Backend

- [ ] Add the mood API endpoint
  Files: `src/api/mood.py`; `tests/test_mood_api.py`
  Verify: `python -m pytest tests/test_mood_api.py`
""",
            encoding="utf-8",
        )
        return autoplan

    def _fake_author_script(self, root: Path, payload: dict) -> Path:
        script = root / "fake_author.py"
        script.write_text(
            "import sys\n"
            "sys.stdin.read()\n"
            f"print({json.dumps(json.dumps(payload))})\n",
            encoding="utf-8",
        )
        return script

    def _repairing_author_script(self, root: Path, first_payload: dict, repaired_payload: dict) -> Path:
        script = root / "repairing_author.py"
        state = root / "repairing_author.state"
        script.write_text(
            "from pathlib import Path\n"
            "import sys\n"
            "sys.stdin.read()\n"
            f"state = Path({json.dumps(str(state))})\n"
            "if state.exists():\n"
            f"    print({json.dumps(json.dumps(repaired_payload))})\n"
            "else:\n"
            "    state.write_text('1', encoding='utf-8')\n"
            f"    print({json.dumps(json.dumps(first_payload))})\n",
            encoding="utf-8",
        )
        return script

    def _valid_model_payload(self) -> dict:
        return {
            "schema_version": "po_candidate_rows_v1",
            "rows": [
                {
                    "step_id": "01",
                    "phase": "Backend",
                    "action": "Implement the mood API endpoint and targeted regression test.",
                    "why_now": "This is the approved backend implementation task.",
                    "owner_type": "agent",
                    "prerequisites": "none",
                    "repo_surfaces": [
                        "docs/gstack/demo-office-hours.md",
                        "src/api/mood.py",
                        "tests/test_mood_api.py",
                    ],
                    "deliverable": ["src/api/mood.py", "tests/test_mood_api.py"],
                    "exit_criteria": "python -m pytest tests/test_mood_api.py passes and src/api/mood.py exposes the endpoint.",
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
                "phase_details": [
                    {
                        "phase_slug": "backend",
                        "title": "Backend",
                        "body": "Implement the backend endpoint and regression coverage.",
                    }
                ],
                "shared_guidance": [],
                "risks_and_contingencies": "No special risks.",
                "immediate_next_actions": "Run the required verification command.",
            },
            "compiler_warnings": [],
        }

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

    def test_design_must_be_under_repo_root(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            outside = Path(tmp) / "outside"
            root.mkdir()
            outside.mkdir()
            design = self._design(outside)
            out = root / "docs" / "playbooks" / "demo.playbook.md"

            rc = main([
                "compile",
                "--repo-root", str(root),
                "--design", str(design),
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

    def test_external_json_author_emits_playbook_and_author_sidecars(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            for rel in ["src/api/mood.py", "tests/test_mood_api.py"]:
                path = root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("# file\n", encoding="utf-8")
            out = root / "docs" / "playbooks" / "demo.playbook.md"
            script = self._fake_author_script(root, self._valid_model_payload())

            rc = main([
                "compile",
                "--repo-root", str(root),
                "--design", str(self._design(root)),
                "--autoplan", str(self._autoplan(root)),
                "--out", str(out),
                "--row-author", "external-json",
                "--row-author-command", f"{sys.executable} {script}",
                "--skip-po-verify", "unit test",
            ])

            self.assertEqual(rc, 0)
            self.assertTrue(out.exists())
            validation = json.loads(out.with_name("demo.validation.json").read_text(encoding="utf-8"))
            self.assertEqual(validation["status"], "pass")
            self.assertTrue(out.with_name("demo.rows.json").exists())
            self.assertTrue(out.with_name("demo.author_input.json").exists())
            trace = json.loads(out.with_name("demo.author_trace.json").read_text(encoding="utf-8"))
            self.assertEqual(trace["source_task_to_rows"], {"task_001": ["01"]})

    def test_external_json_author_fails_closed_without_implementation_tasks(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = root / "docs" / "playbooks" / "demo.playbook.md"
            script = self._fake_author_script(root, self._valid_model_payload())

            rc = main([
                "compile",
                "--repo-root", str(root),
                "--design", str(self._design(root)),
                "--out", str(out),
                "--row-author", "external-json",
                "--row-author-command", f"{sys.executable} {script}",
                "--skip-po-verify", "unit test",
            ])

            self.assertEqual(rc, 3)
            self.assertFalse(out.exists())
            validation = json.loads(out.with_name("demo.validation.json").read_text(encoding="utf-8"))
            self.assertEqual(validation["errors"][0]["code"], "AUTHOR_NO_IMPLEMENTATION_TASKS")
            author_input = json.loads(out.with_name("demo.author_input.json").read_text(encoding="utf-8"))
            self.assertEqual(author_input["schema_version"], "row_author_context_v1")

    def test_external_json_author_uses_one_bounded_repair_attempt(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            for rel in ["src/api/mood.py", "tests/test_mood_api.py"]:
                path = root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("# file\n", encoding="utf-8")
            out = root / "docs" / "playbooks" / "demo.playbook.md"
            first_payload = self._valid_model_payload()
            first_payload["rows"][0]["allowed_write_roots"] = ["src"]
            script = self._repairing_author_script(root, first_payload, self._valid_model_payload())

            rc = main([
                "compile",
                "--repo-root", str(root),
                "--design", str(self._design(root)),
                "--autoplan", str(self._autoplan(root)),
                "--out", str(out),
                "--row-author", "external-json",
                "--row-author-command", f"{sys.executable} {script}",
                "--skip-po-verify", "unit test",
            ])

            self.assertEqual(rc, 0)
            validation = json.loads(out.with_name("demo.validation.json").read_text(encoding="utf-8"))
            self.assertEqual(validation["status"], "repaired_pass")
            self.assertEqual(validation["repair_attempts"], 1)
            meta = json.loads(out.with_name("demo.playbook.meta.json").read_text(encoding="utf-8"))
            self.assertTrue(meta["row_repair_attempted"])
            trace = json.loads(out.with_name("demo.author_trace.json").read_text(encoding="utf-8"))
            self.assertTrue(trace["repair_attempted"])
            self.assertIn("repair_trace", trace)

    def test_max_rows_failure_writes_diagnostics(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            for rel in ["src/api/mood.py", "tests/test_mood_api.py"]:
                path = root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("# file\n", encoding="utf-8")
            out = root / "docs" / "playbooks" / "demo.playbook.md"
            payload = self._valid_model_payload()
            second = dict(payload["rows"][0])
            second["step_id"] = "02"
            second["prerequisites"] = "01"
            second["action"] = "Verify the mood API endpoint regression remains targeted."
            payload["rows"].append(second)
            script = self._fake_author_script(root, payload)

            rc = main([
                "compile",
                "--repo-root", str(root),
                "--design", str(self._design(root)),
                "--autoplan", str(self._autoplan(root)),
                "--out", str(out),
                "--row-author", "external-json",
                "--row-author-command", f"{sys.executable} {script}",
                "--max-authored-rows", "1",
                "--no-row-repair",
                "--skip-po-verify", "unit test",
            ])

            self.assertEqual(rc, 3)
            self.assertFalse(out.exists())
            validation = json.loads(out.with_name("demo.validation.json").read_text(encoding="utf-8"))
            self.assertIn("AUTHOR_TOO_MANY_ROWS", {err["code"] for err in validation["errors"]})
            self.assertTrue(out.with_name("demo.rows.json").exists())
            self.assertTrue(out.with_name("demo.author_input.json").exists())

    def test_validation_warnings_require_allow_warnings_in_non_dry_run(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            for rel in ["src/api/mood.py", "tests/test_mood_api.py"]:
                path = root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("# file\n", encoding="utf-8")
            out = root / "docs" / "playbooks" / "demo.playbook.md"
            payload = self._valid_model_payload()
            payload["rows"][0]["required_verification_commands"] = ["custom-check src/api/mood.py"]
            script = self._fake_author_script(root, payload)

            rc = main([
                "compile",
                "--repo-root", str(root),
                "--design", str(self._design(root)),
                "--autoplan", str(self._autoplan(root)),
                "--out", str(out),
                "--row-author", "external-json",
                "--row-author-command", f"{sys.executable} {script}",
                "--no-row-repair",
                "--skip-po-verify", "unit test",
            ])

            self.assertEqual(rc, 3)
            validation = json.loads(out.with_name("demo.validation.json").read_text(encoding="utf-8"))
            self.assertIn("UNKNOWN_VERIFICATION_COMMAND", {w["code"] for w in validation["warnings"]})
            rows = json.loads(out.with_name("demo.rows.json").read_text(encoding="utf-8"))
            self.assertTrue(
                any("UNKNOWN_VERIFICATION_COMMAND" in warning for warning in rows["compiler_warnings"])
            )

    def test_po_verification_failure_does_not_leave_official_playbook(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            bad_po = Path(tmp) / "bad-po"
            root.mkdir()
            bad_po.mkdir()
            out = root / "docs" / "playbooks" / "demo.playbook.md"

            rc = main([
                "compile",
                "--repo-root", str(root),
                "--design", str(self._design(root)),
                "--out", str(out),
                "--dry-run",
                "--plan-orchestrator-root", str(bad_po),
            ])

            self.assertEqual(rc, 4)
            self.assertFalse(out.exists())
            self.assertFalse(out.with_name(out.name + ".tmp").exists())


if __name__ == "__main__":
    unittest.main()
