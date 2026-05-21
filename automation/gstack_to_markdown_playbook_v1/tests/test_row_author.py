from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from automation.gstack_to_markdown_playbook_v1.ir_models import (
    GstackPlanIR,
    ImplementationTask,
    SourceArtifact,
    StackProfile,
)
from automation.gstack_to_markdown_playbook_v1.row_author import (
    LLMJsonRowAuthor,
    RowAuthorError,
    RowAuthorOptions,
)


class FakeClient:
    def __init__(self, responses: list[dict]) -> None:
        self.responses = [json.dumps(item) for item in responses]
        self.prompts: list[str] = []
        self.last_stderr = "fake stderr note"

    def complete_json(self, *, prompt: str, timeout_sec: int) -> str:
        self.prompts.append(prompt)
        if not self.responses:
            raise AssertionError("no fake responses left")
        return self.responses.pop(0)


def _bundle_payload() -> dict:
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
                    "docs/gstack/design.md",
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


def _ir(root: Path) -> GstackPlanIR:
    return GstackPlanIR(
        compiled_at="2026-05-21T00:00:00+00:00",
        source_artifacts=[
            SourceArtifact(
                kind="design",
                path=str(root / "docs" / "gstack" / "design.md"),
                sha256="0" * 64,
                byte_size=8,
            )
        ],
        product_goal="Build a mood API.",
        implementation_tasks=[
            ImplementationTask(
                task="Add the mood API endpoint",
                phase="Backend",
                files=["src/api/mood.py", "tests/test_mood_api.py"],
                verify=["python -m pytest tests/test_mood_api.py"],
            )
        ],
        candidate_repo_paths=["src/api/mood.py", "tests/test_mood_api.py"],
        stack_profile=StackProfile(languages=["python"], test_runners=["pytest"]),
    )


class RowAuthorTest(unittest.TestCase):
    def test_llm_json_author_builds_context_and_candidate_bundle(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            for rel in ["docs/gstack/design.md", "src/api/mood.py", "tests/test_mood_api.py"]:
                path = root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("# file\n", encoding="utf-8")

            client = FakeClient([_bundle_payload()])
            result = LLMJsonRowAuthor(name="fake", model_client=client).author(
                ir=_ir(root),
                repo_root=root,
                options=RowAuthorOptions(),
            )

        self.assertEqual(result.bundle.rows[0].step_id, "01")
        self.assertEqual(result.author_input["schema_version"], "row_author_context_v1")
        self.assertEqual(result.trace["source_task_to_rows"], {"task_001": ["01"]})
        self.assertEqual(result.trace["invented_paths"], [])
        self.assertTrue(result.trace["raw_model_output_sha256"])
        self.assertTrue(result.trace["model_stderr_sha256"])
        self.assertEqual(result.trace["model_stderr_excerpt"], "fake stderr note")
        self.assertIn("row_author_context_v1", client.prompts[0])

    def test_author_fails_closed_when_no_implementation_tasks_exist(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            ir = GstackPlanIR(compiled_at="2026-05-21T00:00:00+00:00")

            with self.assertRaises(RowAuthorError) as cm:
                LLMJsonRowAuthor(name="fake", model_client=FakeClient([])).author(
                    ir=ir,
                    repo_root=root,
                    options=RowAuthorOptions(),
                )

        self.assertEqual(cm.exception.code, "AUTHOR_NO_IMPLEMENTATION_TASKS")

    def test_author_rejects_raw_payload_before_dataclass_normalization(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            for rel in ["docs/gstack/design.md", "src/api/mood.py", "tests/test_mood_api.py"]:
                path = root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("# file\n", encoding="utf-8")
            payload = _bundle_payload()
            payload["schema_version"] = "wrong_schema"

            with self.assertRaises(RowAuthorError) as cm:
                LLMJsonRowAuthor(name="fake", model_client=FakeClient([payload])).author(
                    ir=_ir(root),
                    repo_root=root,
                    options=RowAuthorOptions(),
                )

        self.assertEqual(cm.exception.code, "AUTHOR_MODEL_OUTPUT_INVALID")

    def test_author_fails_before_model_on_context_conflict(self) -> None:
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
            client = FakeClient([_bundle_payload()])

            with self.assertRaises(RowAuthorError) as cm:
                LLMJsonRowAuthor(name="fake", model_client=client).author(
                    ir=ir,
                    repo_root=root,
                    options=RowAuthorOptions(),
                )

        self.assertEqual(cm.exception.code, "AUTHOR_CONTEXT_CONFLICT")
        self.assertEqual(client.prompts, [])

    def test_behavioral_tasks_without_paths_fail_or_emit_planning_gap_rows(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            ir = GstackPlanIR(
                compiled_at="2026-05-21T00:00:00+00:00",
                implementation_tasks=[
                    ImplementationTask(task="Add the mood API endpoint", phase="Backend")
                ],
            )
            author = LLMJsonRowAuthor(name="fake", model_client=FakeClient([]))

            with self.assertRaises(RowAuthorError) as cm:
                author.author(ir=ir, repo_root=root, options=RowAuthorOptions())
            self.assertEqual(cm.exception.code, "AUTHOR_TASK_MISSING_PATHS")

            result = author.author(
                ir=ir,
                repo_root=root,
                options=RowAuthorOptions(allow_planning_gap_rows=True),
            )

        self.assertEqual(result.bundle.rows[0].phase, "planning gap")
        self.assertFalse(result.bundle.rows[0].requires_red_green)
        self.assertIn("docs/gstack/task_001-planning-gap.md", result.author_input["known_paths"])

    def test_docs_task_without_files_fails_or_emits_planning_gap_rows(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            ir = GstackPlanIR(
                compiled_at="2026-05-21T00:00:00+00:00",
                implementation_tasks=[
                    ImplementationTask(task="Write the release note", phase="Docs")
                ],
            )
            author = LLMJsonRowAuthor(name="fake", model_client=FakeClient([]))

            with self.assertRaises(RowAuthorError) as cm:
                author.author(ir=ir, repo_root=root, options=RowAuthorOptions())
            self.assertEqual(cm.exception.code, "AUTHOR_TASK_MISSING_PATHS")

            result = author.author(
                ir=ir,
                repo_root=root,
                options=RowAuthorOptions(allow_planning_gap_rows=True),
            )

        self.assertEqual(result.bundle.rows[0].phase, "planning gap")
        self.assertEqual(result.bundle.rows[0].deliverable, ["docs/gstack/task_001-planning-gap.md"])


if __name__ == "__main__":
    unittest.main()
