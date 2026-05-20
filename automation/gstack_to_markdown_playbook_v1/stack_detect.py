"""Detect repo stack (languages, test runners, build tools, package managers).

Best-effort, deterministic. Used by row_author to emit reasonable verification commands.
Returns None when the repo root does not exist (compiler is run without a real target).
"""

from __future__ import annotations

import json
from pathlib import Path

from .ir_models import StackProfile


def detect(repo_root: Path) -> StackProfile | None:
    if not repo_root.is_dir():
        return None
    languages: set[str] = set()
    test_runners: set[str] = set()
    build_tools: set[str] = set()
    package_managers: set[str] = set()

    if (repo_root / "pyproject.toml").is_file() or (repo_root / "setup.py").is_file() \
            or (repo_root / "requirements.txt").is_file():
        languages.add("python")
        package_managers.add("pip")
        if (repo_root / "poetry.lock").is_file():
            package_managers.add("poetry")
        if (repo_root / "uv.lock").is_file():
            package_managers.add("uv")
    pkg_json = repo_root / "package.json"
    if pkg_json.is_file():
        languages.add("javascript")
        try:
            data = json.loads(pkg_json.read_text(encoding="utf-8"))
            scripts = data.get("scripts", {}) or {}
            if "test" in scripts:
                test_runners.add("npm-test")
            if "build" in scripts:
                build_tools.add("npm-build")
            if "typecheck" in scripts:
                test_runners.add("typecheck")
            deps = {**(data.get("dependencies") or {}), **(data.get("devDependencies") or {})}
            if "typescript" in deps:
                languages.add("typescript")
            if "next" in deps:
                build_tools.add("next")
            if "playwright" in deps:
                test_runners.add("playwright")
            if "vitest" in deps:
                test_runners.add("vitest")
            if "jest" in deps:
                test_runners.add("jest")
        except (json.JSONDecodeError, OSError):
            pass
        if (repo_root / "pnpm-lock.yaml").is_file():
            package_managers.add("pnpm")
        elif (repo_root / "yarn.lock").is_file():
            package_managers.add("yarn")
        else:
            package_managers.add("npm")

    if any((repo_root / p).is_dir() for p in ("tests", "test")):
        if "python" in languages:
            test_runners.add("pytest")

    if (repo_root / "go.mod").is_file():
        languages.add("go")
        build_tools.add("go")
        test_runners.add("go-test")
    if (repo_root / "Cargo.toml").is_file():
        languages.add("rust")
        package_managers.add("cargo")
        test_runners.add("cargo-test")
    if (repo_root / "pom.xml").is_file():
        languages.add("java")
        build_tools.add("maven")
        test_runners.add("maven-test")
    if (repo_root / "build.gradle").is_file() or (repo_root / "build.gradle.kts").is_file():
        languages.add("java")
        build_tools.add("gradle")
        test_runners.add("gradle-test")
    if (repo_root / "Package.swift").is_file():
        languages.add("swift")
        package_managers.add("swiftpm")
        test_runners.add("swift-test")

    return StackProfile(
        languages=sorted(languages),
        test_runners=sorted(test_runners),
        build_tools=sorted(build_tools),
        package_managers=sorted(package_managers),
    )
