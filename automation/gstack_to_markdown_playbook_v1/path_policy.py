"""Deterministic repo path policy for Step-2 row authoring."""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Literal

PathKind = Literal[
    "source_doc",
    "code",
    "test",
    "doc",
    "config",
    "db",
    "infra",
    "unknown",
]

FORBIDDEN_WRITE_ROOTS = {
    ".",
    ".local",
    ".git",
    ".codex",
    ".claude",
    ".mcp.json",
    "ops/config",
    "secrets",
    ".env",
}
FORBIDDEN_PREFIXES = {
    ".local",
    ".git",
    ".codex",
    ".claude",
    "ops/config",
    "secrets",
}
BROAD_WRITE_ROOTS = {".", "src", "tests", "test"}
CODE_SUFFIXES = {
    ".py",
    ".pyi",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".kts",
    ".swift",
    ".dart",
    ".rb",
    ".php",
    ".cs",
    ".cpp",
    ".c",
    ".h",
    ".hpp",
}
CONFIG_SUFFIXES = {
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".env",
}
DB_SUFFIXES = {".sql"}
DOC_SUFFIXES = {".md", ".markdown", ".rst", ".txt", ".html"}


def normalize_repo_path(path: str) -> str:
    """Normalize a repo-relative path token without accepting unsafe paths."""
    value = str(path).strip().strip("`").strip().replace("\\", "/")
    while value.startswith("./"):
        value = value[2:]
    if value not in {".", "/"}:
        value = value.rstrip("/")
    if value == "":
        return ""
    parts = []
    for part in PurePosixPath(value).parts:
        if part in {"", "."}:
            continue
        parts.append(part)
    if not parts:
        return "." if value == "." else ""
    return "/".join(parts)


def is_absolute_path(path: str) -> bool:
    value = str(path).strip().strip("`").strip()
    return (
        value.startswith("/")
        or value.startswith("~")
        or re.match(r"^[A-Za-z]:[\\/]", value) is not None
    )


def has_parent_escape(path: str) -> bool:
    return ".." in PurePosixPath(str(path).replace("\\", "/")).parts


def is_forbidden_path(path: str) -> bool:
    if is_absolute_path(path) or has_parent_escape(path):
        return True
    p = normalize_repo_path(path)
    if not p:
        return True
    if p == ".env" or p.startswith(".env.") or "/.env" in p:
        return True
    if p == ".mcp.json":
        return True
    for prefix in FORBIDDEN_PREFIXES:
        if p == prefix or p.startswith(prefix + "/") or f"/{prefix}/" in p:
            return True
    return False


def is_forbidden_write_root(root: str) -> bool:
    p = normalize_repo_path(root)
    if p in FORBIDDEN_WRITE_ROOTS or p in BROAD_WRITE_ROOTS:
        return True
    return is_forbidden_path(p)


def classify_path(path: str) -> PathKind:
    p = normalize_repo_path(path)
    name = PurePosixPath(p).name
    suffix = PurePosixPath(p).suffix.lower()
    if p.startswith("docs/gstack/") or p.startswith("docs/briefs/"):
        return "source_doc"
    if p.startswith(("tests/", "test/")) or name.startswith("test_") or name.endswith("_test.py"):
        return "test"
    if suffix in DB_SUFFIXES or "/migrations/" in p or p.startswith(("migrations/", "db/")):
        return "db"
    if name in {"Dockerfile", "docker-compose.yml", "docker-compose.yaml"}:
        return "infra"
    if p.startswith((".github/", "infra/", "ops/")):
        return "infra"
    if suffix in CODE_SUFFIXES:
        return "code"
    if suffix in DOC_SUFFIXES or p.startswith("docs/"):
        return "doc"
    if suffix in CONFIG_SUFFIXES:
        return "config"
    return "unknown"


def safe_parent_root(path: str) -> str:
    """Return a narrow allowed write root for a concrete path."""
    p = normalize_repo_path(path)
    if "/" not in p:
        return p
    parent = p.rsplit("/", 1)[0]
    if parent in {"src", "tests", "test", "docs"}:
        if parent == "docs" and p.endswith(".md"):
            return parent
        return p
    return parent


def clamp_write_roots(paths: list[str], *, max_roots: int = 3) -> list[str]:
    roots: list[str] = []
    for raw in paths:
        p = normalize_repo_path(raw)
        if not p or is_forbidden_path(p):
            continue
        root = safe_parent_root(p)
        if is_forbidden_write_root(root):
            continue
        if root not in roots:
            roots.append(root)
        if len(roots) >= max_roots:
            break
    return roots


def path_inside_root(path: str, root: str) -> bool:
    p = normalize_repo_path(path)
    r = normalize_repo_path(root)
    return p == r or p.startswith(r + "/")


def path_inside_any_root(path: str, roots: list[str]) -> bool:
    return any(path_inside_root(path, root) for root in roots)


def root_derived_from_known_path(root: str, known_paths: set[str]) -> bool:
    r = normalize_repo_path(root)
    if r in known_paths:
        return True
    return any(path_inside_root(path, r) for path in known_paths)
