"""Safety policy for executable verification commands."""

from __future__ import annotations

import shlex
from dataclasses import dataclass


FORBIDDEN_COMMAND_PREFIXES = (
    "rm",
    "sudo",
    "curl",
    "wget",
    "ssh",
    "scp",
    "rsync",
    "git push",
    "git reset",
    "git clean",
    "gh pr merge",
    "kubectl apply",
    "terraform apply",
    "vercel --prod",
    "netlify deploy",
)

FORBIDDEN_SHELL_TOKENS = (
    ";",
    "&&",
    "||",
    "|",
    ">",
    ">>",
    "<",
    "`",
    "$(",
    "\n",
    "\r",
)

ALLOWED_PREFIXES = (
    "python -m pytest",
    "pytest",
    "python -m compileall",
    "ruff check",
    "mypy",
    "npm run typecheck",
    "npm run test",
    "npm run build",
    "pnpm run typecheck",
    "pnpm run test",
    "pnpm run build",
    "yarn typecheck",
    "yarn test",
    "yarn build",
    "npx playwright test",
    "go test",
    "cargo test",
    "mvn test",
    "./gradlew test",
    "swift test",
    "git diff --check",
    "test -f",
    "keel-run list-items",
    "keel-doctor",
    "python automation/run_plan_orchestrator.py list-items",
    "python automation/run_plan_orchestrator.py doctor",
)


@dataclass(frozen=True)
class CommandFinding:
    code: str
    message: str


def validate_verification_command(command: str) -> list[CommandFinding]:
    cmd = command.strip()
    if not cmd:
        return [
            CommandFinding(
                "EMPTY_VERIFICATION_COMMAND",
                "verification command is empty",
            )
        ]

    findings: list[CommandFinding] = []
    for token in FORBIDDEN_SHELL_TOKENS:
        if token in cmd:
            findings.append(
                CommandFinding(
                    "UNSAFE_VERIFICATION_COMMAND",
                    f"verification command contains forbidden shell token {token!r}",
                )
            )

    try:
        normalized = " ".join(shlex.split(cmd))
    except ValueError as exc:
        findings.append(
            CommandFinding(
                "UNSAFE_VERIFICATION_COMMAND",
                f"verification command cannot be parsed safely: {exc}",
            )
        )
        normalized = cmd

    lower_normalized = normalized.lower()
    for prefix in FORBIDDEN_COMMAND_PREFIXES:
        if lower_normalized.startswith(prefix):
            findings.append(
                CommandFinding(
                    "UNSAFE_VERIFICATION_COMMAND",
                    f"verification command starts with forbidden prefix {prefix!r}",
                )
            )

    if not any(lower_normalized.startswith(prefix) for prefix in ALLOWED_PREFIXES):
        findings.append(
            CommandFinding(
                "UNKNOWN_VERIFICATION_COMMAND",
                f"verification command is not in the compiler allowlist: {cmd!r}",
            )
        )

    return findings
