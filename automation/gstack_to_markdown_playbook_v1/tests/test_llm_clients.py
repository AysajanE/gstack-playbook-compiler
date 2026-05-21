from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from automation.gstack_to_markdown_playbook_v1.llm_clients import (
    ExternalCommandJsonClient,
    parse_json_object_strict,
    render_prompt,
)


class LlmClientsTest(unittest.TestCase):
    def test_strict_json_parser_rejects_markdown_or_trailing_text(self) -> None:
        self.assertEqual(parse_json_object_strict('{"ok": true}'), {"ok": True})

        with self.assertRaises(ValueError):
            parse_json_object_strict('```json\n{"ok": true}\n```')

        with self.assertRaises(ValueError):
            parse_json_object_strict('{"ok": true}\nextra')

    def test_external_command_receives_prompt_and_returns_json_stdout(self) -> None:
        with TemporaryDirectory() as tmp:
            script = Path(tmp) / "echo_json.py"
            script.write_text(
                "import json, sys\n"
                "prompt = sys.stdin.read()\n"
                "print(json.dumps({'prompt_has_marker': 'MARKER' in prompt}))\n",
                encoding="utf-8",
            )
            client = ExternalCommandJsonClient(f"{sys.executable} {script}")

            raw = client.complete_json(prompt="hello MARKER", timeout_sec=10)

        self.assertEqual(parse_json_object_strict(raw), {"prompt_has_marker": True})

    def test_external_command_runs_outside_product_repo_by_default(self) -> None:
        with TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            script = Path(tmp) / "cwd_json.py"
            script.write_text(
                "import json, os\n"
                f"print(json.dumps({{'cwd_is_repo': os.path.realpath(os.getcwd()) == os.path.realpath({json.dumps(str(repo))})}}))\n",
                encoding="utf-8",
            )
            client = ExternalCommandJsonClient(f"{sys.executable} {script}")

            raw = client.complete_json(prompt="{}", timeout_sec=10)

        self.assertEqual(parse_json_object_strict(raw), {"cwd_is_repo": False})

    def test_external_command_can_use_explicit_cwd_for_debugging(self) -> None:
        with TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            script = Path(tmp) / "cwd_json.py"
            script.write_text(
                "import json, os\n"
                f"print(json.dumps({{'cwd_is_repo': os.path.realpath(os.getcwd()) == os.path.realpath({json.dumps(str(repo))})}}))\n",
                encoding="utf-8",
            )
            client = ExternalCommandJsonClient(f"{sys.executable} {script}", cwd=repo)

            raw = client.complete_json(prompt="{}", timeout_sec=10)

        self.assertEqual(parse_json_object_strict(raw), {"cwd_is_repo": True})

    def test_external_command_sanitizes_repo_and_secret_environment_by_default(self) -> None:
        # The environment is allowlisted: arbitrary secrets must be dropped even
        # when their names match no known denylist pattern, and the variables a
        # model CLI needs (PATH, HOME, provider credentials) must survive.
        with TemporaryDirectory() as tmp:
            script = Path(tmp) / "env_json.py"
            script.write_text(
                "import json, os\n"
                "print(json.dumps({\n"
                "  'PRODUCT_REPO': 'PRODUCT_REPO' in os.environ,\n"
                "  'DATABASE_URL': 'DATABASE_URL' in os.environ,\n"
                "  'GITHUB_TOKEN': 'GITHUB_TOKEN' in os.environ,\n"
                "  'PWD': 'PWD' in os.environ,\n"
                "  'OURA_CLIENT_SECRET': 'OURA_CLIENT_SECRET' in os.environ,\n"
                "  'MOOD_TOKEN': 'MOOD_TOKEN' in os.environ,\n"
                "  'ACME_API_KEY': 'ACME_API_KEY' in os.environ,\n"
                "  'PATH': 'PATH' in os.environ,\n"
                "  'HOME': 'HOME' in os.environ,\n"
                "  'ANTHROPIC_API_KEY': os.environ.get('ANTHROPIC_API_KEY'),\n"
                "}))\n",
                encoding="utf-8",
            )
            client = ExternalCommandJsonClient(f"{sys.executable} {script}")

            with patch.dict(
                os.environ,
                {
                    "PRODUCT_REPO": "/tmp/repo",
                    "DATABASE_URL": "postgres://example",
                    "GITHUB_TOKEN": "secret",
                    "PWD": "/tmp/repo",
                    # Secrets a name-pattern denylist would miss entirely:
                    "OURA_CLIENT_SECRET": "secret",
                    "MOOD_TOKEN": "secret",
                    "ACME_API_KEY": "secret",
                    # A provider credential the row-author CLI legitimately needs:
                    "ANTHROPIC_API_KEY": "provider-key",
                },
                clear=False,
            ):
                raw = client.complete_json(prompt="{}", timeout_sec=10)

        self.assertEqual(
            parse_json_object_strict(raw),
            {
                # Repo/ambient secrets are dropped, including the generic ones.
                "PRODUCT_REPO": False,
                "DATABASE_URL": False,
                "GITHUB_TOKEN": False,
                "PWD": False,
                "OURA_CLIENT_SECRET": False,
                "MOOD_TOKEN": False,
                "ACME_API_KEY": False,
                # What a model CLI provably needs survives.
                "PATH": True,
                "HOME": True,
                "ANTHROPIC_API_KEY": "provider-key",
            },
        )

    def test_external_command_can_inherit_environment_with_explicit_escape_hatch(self) -> None:
        with TemporaryDirectory() as tmp:
            script = Path(tmp) / "env_json.py"
            script.write_text(
                "import json, os\n"
                "print(json.dumps({'PRODUCT_REPO': os.environ.get('PRODUCT_REPO')}))\n",
                encoding="utf-8",
            )
            client = ExternalCommandJsonClient(f"{sys.executable} {script}", inherit_env=True)

            with patch.dict(os.environ, {"PRODUCT_REPO": "/tmp/repo"}, clear=False):
                raw = client.complete_json(prompt="{}", timeout_sec=10)

        self.assertEqual(parse_json_object_strict(raw), {"PRODUCT_REPO": "/tmp/repo"})

    def test_render_prompt_replaces_all_placeholders(self) -> None:
        prompt = render_prompt("row_author_v2.md", {"IR_JSON": "IR", "AUTHOR_CONTEXT_JSON": "CTX"})

        self.assertIn("IR", prompt)
        self.assertIn("CTX", prompt)
        self.assertNotIn("{{IR_JSON}}", prompt)
        self.assertNotIn("{{AUTHOR_CONTEXT_JSON}}", prompt)


if __name__ == "__main__":
    unittest.main()
