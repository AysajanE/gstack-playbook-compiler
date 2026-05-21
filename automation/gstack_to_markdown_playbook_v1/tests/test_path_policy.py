from __future__ import annotations

import unittest

from automation.gstack_to_markdown_playbook_v1.path_policy import (
    clamp_write_roots,
    classify_path,
    has_parent_escape,
    is_forbidden_path,
    normalize_repo_path,
    path_inside_any_root,
)


class PathPolicyTest(unittest.TestCase):
    def test_normalizes_repo_relative_tokens_without_accepting_unsafe_paths(self) -> None:
        self.assertEqual(normalize_repo_path("`./src/api/mood.py`"), "src/api/mood.py")
        self.assertEqual(normalize_repo_path("docs\\gstack\\plan.md"), "docs/gstack/plan.md")
        self.assertTrue(has_parent_escape("../secrets.txt"))
        self.assertTrue(is_forbidden_path("../secrets.txt"))
        self.assertTrue(is_forbidden_path("/tmp/secret"))
        self.assertTrue(is_forbidden_path(".env.local"))
        self.assertTrue(is_forbidden_path(".git/config"))

    def test_classifies_paths_and_clamps_write_roots(self) -> None:
        self.assertEqual(classify_path("src/api/mood.py"), "code")
        self.assertEqual(classify_path("tests/test_mood.py"), "test")
        self.assertEqual(classify_path("docs/gstack/design.md"), "source_doc")
        self.assertEqual(classify_path("migrations/001_add_mood.sql"), "db")

        roots = clamp_write_roots(
            [
                "src/mood.py",
                "tests/test_mood.py",
                "docs/gstack/demo.md",
                ".env.local",
            ]
        )

        self.assertEqual(roots, ["src/mood.py", "tests/test_mood.py", "docs/gstack"])
        self.assertTrue(path_inside_any_root("tests/test_mood.py", roots))


if __name__ == "__main__":
    unittest.main()
