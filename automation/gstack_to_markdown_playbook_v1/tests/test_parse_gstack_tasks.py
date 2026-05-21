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

    def test_source_artifact_paths_are_repo_relative_when_repo_root_is_supplied(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            design = root / "docs" / "gstack" / "design.md"
            autoplan = root / "docs" / "gstack" / "autoplan.md"
            design.parent.mkdir(parents=True)
            design.write_text("# Design\n\n## Problem Statement\n\nBuild a thing.\n", encoding="utf-8")
            autoplan.write_text("# Autoplan\n", encoding="utf-8")

            ir = parse(design_path=design, autoplan_path=autoplan, repo_root=root)

            paths = [artifact.path for artifact in ir.source_artifacts]
            self.assertEqual(paths, ["docs/gstack/design.md", "docs/gstack/autoplan.md"])
            self.assertFalse(any(path.startswith("/") for path in paths))

    def test_extracts_goal_heading_and_approved_brief_write_root_constraint(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            design = root / "docs" / "gstack" / "design.md"
            brief = root / "docs" / "briefs" / "demo.approved-brief.md"
            design.parent.mkdir(parents=True)
            brief.parent.mkdir(parents=True)
            design.write_text(
                "# Design\n\n## Goal\n\nCreate a minimal repository health note.\n",
                encoding="utf-8",
            )
            brief.write_text(
                "Status: approved for local dry-run testing.\n\n"
                "The only allowed write root is `docs/playbooks/`.\n",
                encoding="utf-8",
            )

            ir = parse(design_path=design, approved_brief_path=brief, repo_root=root)

        self.assertEqual(ir.product_goal, "Create a minimal repository health note.")
        self.assertIn("The only allowed write root is `docs/playbooks/`.", ir.constraints)

    def test_non_goals_heading_does_not_win_goal_extraction(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            design = root / "docs" / "gstack" / "design.md"
            design.parent.mkdir(parents=True)
            design.write_text(
                """
# Design

## Non-Goals

Do not modify application code.

## Goal

Build the docs playbook.
""",
                encoding="utf-8",
            )

            ir = parse(design_path=design, repo_root=root)

        self.assertEqual(ir.product_goal, "Build the docs playbook.")

    def test_approved_brief_status_does_not_create_manual_gate_hint(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            design = root / "docs" / "gstack" / "design.md"
            brief = root / "docs" / "briefs" / "demo.approved-brief.md"
            design.parent.mkdir(parents=True)
            brief.parent.mkdir(parents=True)
            design.write_text("# Design\n\n## Goal\n\nBuild docs.\n", encoding="utf-8")
            brief.write_text("Status: approved for local dry-run testing.\n", encoding="utf-8")

            ir = parse(design_path=design, approved_brief_path=brief, repo_root=root)

        self.assertNotIn("approved", [hint.lower() for hint in ir.manual_gate_hints])

    def test_extracts_implementation_tasks_from_markdown_table(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            design = root / "docs" / "gstack" / "design.md"
            autoplan = root / "docs" / "gstack" / "autoplan.md"
            design.parent.mkdir(parents=True)
            design.write_text("# Design\n\n## Goal\n\nBuild a small mood API.\n", encoding="utf-8")
            autoplan.write_text(
                """
# Autoplan

## Implementation Tasks

| phase | task | files | verify |
| --- | --- | --- | --- |
| Backend | Add mood endpoint | `src/api/mood.py`; `tests/test_mood_api.py` | `python -m pytest tests/test_mood_api.py` |
""",
                encoding="utf-8",
            )

            ir = parse(design_path=design, autoplan_path=autoplan, repo_root=root)

        self.assertEqual(len(ir.implementation_tasks), 1)
        task = ir.implementation_tasks[0]
        self.assertEqual(task.phase, "Backend")
        self.assertEqual(task.task, "Add mood endpoint")
        self.assertEqual(task.files, ["src/api/mood.py", "tests/test_mood_api.py"])
        self.assertEqual(task.verify, ["python -m pytest tests/test_mood_api.py"])

    def test_extracts_root_level_backticked_repo_files(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            design = root / "docs" / "gstack" / "design.md"
            design.parent.mkdir(parents=True)
            design.write_text(
                "Update `README.md` and `pyproject.toml`.\n",
                encoding="utf-8",
            )

            ir = parse(design_path=design, repo_root=root)

        self.assertIn("README.md", ir.candidate_repo_paths)
        self.assertIn("pyproject.toml", ir.candidate_repo_paths)

    def test_fastapi_and_duckdb_do_not_create_external_dependency_hints(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            design = root / "docs" / "gstack" / "design.md"
            design.parent.mkdir(parents=True)
            design.write_text(
                "# Design\n\n## Goal\n\nUse FastAPI and DuckDB for local processing.\n",
                encoding="utf-8",
            )

            ir = parse(design_path=design, repo_root=root)

        hints = [hint.lower() for hint in ir.external_dependency_hints]
        self.assertNotIn("fastapi", hints)
        self.assertNotIn("duckdb", hints)


if __name__ == "__main__":
    unittest.main()
