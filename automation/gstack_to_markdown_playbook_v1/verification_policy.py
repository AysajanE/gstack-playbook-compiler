"""Verification and behavioral-classification policy for Step-2 authoring."""

from __future__ import annotations

from pathlib import Path

from .ir_models import StackProfile
from .path_policy import classify_path, normalize_repo_path

BEHAVIORAL_SUFFIXES = {
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
    ".swift",
    ".dart",
    ".rb",
    ".php",
    ".cs",
    ".cpp",
    ".c",
    ".h",
    ".hpp",
    ".sql",
    ".sh",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".json",
}


def is_test_path(path: str) -> bool:
    p = normalize_repo_path(path)
    name = Path(p).name
    return (
        p.startswith(("tests/", "test/"))
        or name.startswith("test_")
        or name.endswith("_test.py")
        or name.endswith(".test.ts")
        or name.endswith(".test.tsx")
        or name.endswith(".spec.ts")
        or name.endswith(".spec.tsx")
    )


def is_behavioral_path(path: str) -> bool:
    p = normalize_repo_path(path)
    name = Path(p).name
    if name in {"Dockerfile", "docker-compose.yml", "docker-compose.yaml"}:
        return True
    if classify_path(p) in {"code", "test", "config", "db", "infra"}:
        return True
    return any(p.endswith(suffix) for suffix in BEHAVIORAL_SUFFIXES)


def task_requires_red_green(task_files: list[str]) -> bool:
    return any(is_behavioral_path(path) for path in task_files)


def task_text_looks_behavioral(task: str, phase: str = "") -> bool:
    text = f"{phase} {task}".lower()
    keywords = (
        "api",
        "backend",
        "frontend",
        "endpoint",
        "database",
        "migration",
        "auth",
        "cli",
        "service",
        "worker",
        "function",
        "component",
        "test",
        "implement",
        "wire",
        "refactor",
    )
    return any(keyword in text for keyword in keywords)


def infer_verification_commands(
    *,
    task_files: list[str],
    task_verify: list[str],
    stack_profile: StackProfile | None,
    repo_root: Path,
) -> list[str]:
    explicit = [cmd.strip() for cmd in task_verify if cmd.strip()]
    if explicit:
        return explicit

    test_files = [normalize_repo_path(p) for p in task_files if is_test_path(p)]

    if stack_profile and "python" in stack_profile.languages:
        py_tests = [p for p in test_files if p.endswith(".py")]
        if py_tests:
            return [f"python -m pytest {py_tests[0]}"]
        if "pytest" in stack_profile.test_runners:
            return ["python -m pytest"]

    if stack_profile and (
        "javascript" in stack_profile.languages or "typescript" in stack_profile.languages
    ):
        cmds: list[str] = []
        if "typecheck" in stack_profile.test_runners:
            cmds.append("npm run typecheck")
        if "npm-test" in stack_profile.test_runners:
            cmds.append("npm run test")
        if "npm-build" in stack_profile.build_tools:
            cmds.append("npm run build")
        if cmds:
            return cmds

    if stack_profile and "go" in stack_profile.languages:
        return ["go test ./..."]

    if stack_profile and "rust" in stack_profile.languages:
        return ["cargo test"]

    if stack_profile and "java" in stack_profile.languages:
        if "maven-test" in stack_profile.test_runners:
            return ["mvn test"]
        if "gradle-test" in stack_profile.test_runners:
            return ["./gradlew test"]

    if stack_profile and "swift" in stack_profile.languages:
        return ["swift test"]

    # Last-resort repo inspection is deterministic, but only chooses commands
    # with explicit repo evidence.
    if (repo_root / "pytest.ini").is_file() or (repo_root / "pyproject.toml").is_file():
        py_tests = [p for p in test_files if p.endswith(".py")]
        if py_tests:
            return [f"python -m pytest {py_tests[0]}"]

    return []
