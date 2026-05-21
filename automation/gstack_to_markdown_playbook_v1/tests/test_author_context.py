from __future__ import annotations

import hashlib
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from automation.gstack_to_markdown_playbook_v1.author_context import build_author_context
from automation.gstack_to_markdown_playbook_v1.ir_models import (
    GstackPlanIR,
    ImplementationTask,
    SourceArtifact,
    StackProfile,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class AuthorContextTest(unittest.TestCase):
    def test_builds_path_ledger_from_sources_candidates_and_tasks(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            design = root / "docs" / "gstack" / "demo.md"
            src = root / "src" / "api" / "mood.py"
            design.parent.mkdir(parents=True)
            src.parent.mkdir(parents=True)
            design.write_text("# Design\n", encoding="utf-8")
            src.write_text("def mood(): return 'ok'\n", encoding="utf-8")

            ir = GstackPlanIR(
                compiled_at="2026-05-21T00:00:00+00:00",
                source_artifacts=[
                    SourceArtifact(
                        kind="design",
                        path=str(design),
                        sha256=_sha(design),
                        byte_size=design.stat().st_size,
                    )
                ],
                product_goal="Build a mood API.",
                implementation_tasks=[
                    ImplementationTask(
                        task="Add the mood API endpoint",
                        phase="Backend",
                        files=["src/api/mood.py", "tests/test_mood_api.py"],
                        verify=[],
                    )
                ],
                candidate_repo_paths=["src/api/mood.py"],
                stack_profile=StackProfile(languages=["python"], test_runners=["pytest"]),
            )

            context = build_author_context(ir=ir, repo_root=root)

        self.assertEqual(context["schema_version"], "row_author_context_v1")
        self.assertIn("docs/gstack/demo.md", context["known_paths"])
        self.assertIn("src/api/mood.py", context["known_paths"])
        self.assertIn("tests/test_mood_api.py", context["known_paths"])
        self.assertEqual(context["known_write_roots"], ["src/api", "tests/test_mood_api.py"])
        card = context["task_cards"][0]
        self.assertEqual(card["task_id"], "task_001")
        self.assertTrue(card["behavioral"])
        self.assertIn("src/api/mood.py", card["existing_repo_surfaces"])
        self.assertNotIn("tests/test_mood_api.py", card["existing_repo_surfaces"])
        self.assertEqual(card["verification_candidates"], ["python -m pytest tests/test_mood_api.py"])

    def test_conflicting_docs_only_constraint_is_a_context_error(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            ir = GstackPlanIR(
                compiled_at="2026-05-21T00:00:00+00:00",
                constraints=["Documentation only. Do not modify application code."],
                implementation_tasks=[
                    ImplementationTask(
                        task="Implement the mood API endpoint",
                        phase="Backend",
                        files=["src/api/mood.py"],
                    )
                ],
            )

            context = build_author_context(ir=ir, repo_root=root)

        self.assertEqual(context["context_findings"][0]["code"], "CONSTRAINT_TASK_CONFLICT")


if __name__ == "__main__":
    unittest.main()
