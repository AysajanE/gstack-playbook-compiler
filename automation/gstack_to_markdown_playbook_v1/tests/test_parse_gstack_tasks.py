from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from automation.gstack_to_markdown_playbook_v1.parse_gstack import parse


class ParseGstackTasksTest(unittest.TestCase):
    def test_extracts_files_verify_and_notes_from_implementation_tasks(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            design = root / "docs" / "gstack" / "design.md"
            autoplan = root / "docs" / "gstack" / "autoplan.md"
            design.parent.mkdir(parents=True)
            design.write_text(
                """
# Design

## Problem Statement

Build a small mood API.
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
  Priority: P0
  Effort: S
""",
                encoding="utf-8",
            )

            ir = parse(design_path=design, autoplan_path=autoplan)

            self.assertEqual(len(ir.implementation_tasks), 1)
            task = ir.implementation_tasks[0]
            self.assertEqual(task.task, "Add the mood API endpoint")
            self.assertEqual(task.phase, "Backend")
            self.assertEqual(task.files, ["src/api/mood.py", "tests/test_mood_api.py"])
            self.assertEqual(task.verify, ["python -m pytest tests/test_mood_api.py"])
            self.assertIn("priority: p0", task.notes.lower())
            self.assertIn("effort: S", task.notes)


if __name__ == "__main__":
    unittest.main()
