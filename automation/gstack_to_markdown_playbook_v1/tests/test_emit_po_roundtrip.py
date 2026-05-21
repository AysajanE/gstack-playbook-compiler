from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from automation.gstack_to_markdown_playbook_v1.cli import main
from automation.gstack_to_markdown_playbook_v1.emit_markdown import emit_playbook_markdown
from automation.gstack_to_markdown_playbook_v1.ir_models import GstackPlanIR
from automation.gstack_to_markdown_playbook_v1.row_models import CandidateRow, CandidateRowsBundle


KEEL_TOOLS_ROOT = Path(__file__).resolve().parents[4]
PLAN_ORCHESTRATOR_ROOT = KEEL_TOOLS_ROOT / "plan-orchestrator"


class EmitPoRoundTripTest(unittest.TestCase):
    def _external_json_payload(self) -> dict:
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
                "phase_details": [],
                "shared_guidance": [],
                "risks_and_contingencies": "",
                "immediate_next_actions": "",
            },
            "compiler_warnings": [],
        }

    def test_emitter_refuses_pipe_cells(self) -> None:
        row = CandidateRow(
            step_id="01",
            phase="docs",
            action="Write alpha | beta note",
            why_now="Needed before launch.",
            owner_type="operator",
            prerequisites="none",
            repo_surfaces=["docs/gstack/source.md"],
            deliverable=["docs/releases/release.md"],
            exit_criteria="Release note exists.",
            allowed_write_roots=["docs/releases"],
            requires_red_green=False,
            required_verification_artifacts=["docs/releases/release.md"],
        )

        with self.assertRaises(ValueError):
            emit_playbook_markdown(
                ir=GstackPlanIR(compiled_at="2026-05-21T00:00:00+00:00"),
                bundle=CandidateRowsBundle(rows=[row]),
            )

    @unittest.skipUnless(
        (PLAN_ORCHESTRATOR_ROOT / "automation" / "run_plan_orchestrator.py").is_file(),
        "plan-orchestrator sibling checkout is required for PO round-trip tests",
    )
    def test_compile_fixture_round_trips_through_po(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "docs" / "gstack").mkdir(parents=True)
            (root / "docs" / "playbooks").mkdir(parents=True)
            (root / "src" / "api").mkdir(parents=True)
            (root / "tests").mkdir(parents=True)
            (root / "src" / "api" / "mood.py").write_text("# target\n", encoding="utf-8")
            (root / "tests" / "test_mood_api.py").write_text("def test_placeholder():\n    assert True\n", encoding="utf-8")
            design = root / "docs" / "gstack" / "demo-office-hours.md"
            autoplan = root / "docs" / "gstack" / "demo-autoplan.md"
            out = root / "docs" / "playbooks" / "demo.playbook.md"
            design.write_text(
                """
# Design

## Problem Statement

Build a small mood API.

## Constraints

- Keep the change narrow.
""",
                encoding="utf-8",
            )
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

            rc = main([
                "compile",
                "--repo-root", str(root),
                "--design", str(design),
                "--autoplan", str(autoplan),
                "--out", str(out),
                "--dry-run",
                "--plan-orchestrator-root", str(PLAN_ORCHESTRATOR_ROOT),
            ])

            self.assertEqual(rc, 0)
            meta = json.loads(out.with_name("demo.playbook.meta.json").read_text(encoding="utf-8"))
            self.assertEqual(meta["po_contract_verification"]["status"], "pass")
            self.assertTrue(meta["emitted_playbook_sha256"])

    @unittest.skipUnless(
        (PLAN_ORCHESTRATOR_ROOT / "automation" / "run_plan_orchestrator.py").is_file(),
        "plan-orchestrator sibling checkout is required for PO round-trip tests",
    )
    def test_external_json_author_round_trips_through_po(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "docs" / "gstack").mkdir(parents=True)
            (root / "docs" / "playbooks").mkdir(parents=True)
            (root / "src" / "api").mkdir(parents=True)
            (root / "tests").mkdir(parents=True)
            (root / "src" / "api" / "mood.py").write_text("# target\n", encoding="utf-8")
            (root / "tests" / "test_mood_api.py").write_text("def test_placeholder():\n    assert True\n", encoding="utf-8")
            design = root / "docs" / "gstack" / "demo-office-hours.md"
            autoplan = root / "docs" / "gstack" / "demo-autoplan.md"
            out = root / "docs" / "playbooks" / "demo.playbook.md"
            script = root / "fake_author.py"
            script.write_text(
                "import json, sys\n"
                "sys.stdin.read()\n"
                f"print({json.dumps(json.dumps(self._external_json_payload()))})\n",
                encoding="utf-8",
            )
            design.write_text(
                "# Design\n\n## Goal\n\nBuild a small mood API.\n",
                encoding="utf-8",
            )
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

            rc = main([
                "compile",
                "--repo-root", str(root),
                "--design", str(design),
                "--autoplan", str(autoplan),
                "--out", str(out),
                "--row-author", "external-json",
                "--row-author-command", f"{sys.executable} {script}",
                "--plan-orchestrator-root", str(PLAN_ORCHESTRATOR_ROOT),
            ])

            self.assertEqual(rc, 0)
            meta = json.loads(out.with_name("demo.playbook.meta.json").read_text(encoding="utf-8"))
            self.assertEqual(meta["po_contract_verification"]["status"], "pass")
            self.assertEqual(meta["row_author"], "external-json")


if __name__ == "__main__":
    unittest.main()
