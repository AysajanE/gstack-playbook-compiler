from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from automation.gstack_to_markdown_playbook_v1.cli import main


KEEL_TOOLS_ROOT = Path(__file__).resolve().parents[4]
PLAN_ORCHESTRATOR_ROOT = KEEL_TOOLS_ROOT / "plan-orchestrator"


class EmitPoRoundTripTest(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
