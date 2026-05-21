"""Model-client abstractions for row authoring."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Protocol


class JsonModelClient(Protocol):
    def complete_json(
        self,
        *,
        prompt: str,
        timeout_sec: int,
    ) -> str:
        ...


class ModelClientError(RuntimeError):
    pass


# Environment passed to model-backed row-author commands.
#
# This is an ALLOWLIST, not a denylist: only variables a model CLI provably
# needs are forwarded. Every other variable — including the product repo's
# ambient secrets (database URLs, device credentials, cloud tokens, generic
# *_TOKEN / *_SECRET / *_KEY values) — is dropped, so a row-author subprocess
# never sees them. A denylist cannot enumerate every secret name; an allowlist
# is closed by construction.
#
# Provider credentials (ANTHROPIC_*, OPENAI_*) are forwarded deliberately: the
# row-author CLI cannot authenticate to its model without them. That is the one
# secret class the row author legitimately requires. A custom row-author
# command that needs additional variables can opt into full inheritance with
# --row-author-inherit-env.
ENV_ALLOWLIST_NAMES = frozenset(
    {
        "PATH",
        "HOME",
        "USER",
        "LOGNAME",
        "SHELL",
        "TERM",
        "TMPDIR",
        "TZ",
        "LANG",
        "NO_COLOR",
        # TLS trust + proxy: a network CLI needs these to reach its provider;
        # they are paths/URLs, not application secrets.
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "REQUESTS_CA_BUNDLE",
        "CURL_CA_BUNDLE",
        "NODE_EXTRA_CA_CERTS",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "no_proxy",
    }
)
ENV_ALLOWLIST_PREFIXES = (
    "LC_",         # locale
    "XDG_",        # config/cache directory resolution
    "ANTHROPIC_",  # claude provider configuration and credentials
    "OPENAI_",     # codex / openai provider configuration and credentials
    "CLAUDE_",     # claude code CLI configuration
    "CODEX_",      # codex CLI configuration
)


def _sanitized_env() -> dict[str, str]:
    """Return an allowlisted environment for model-backed row-author commands.

    Only variables a model CLI provably needs are forwarded. Every other
    variable — including the product repo's ambient secrets — is dropped.
    """
    env: dict[str, str] = {}
    for key, value in os.environ.items():
        if key in ENV_ALLOWLIST_NAMES or key.startswith(ENV_ALLOWLIST_PREFIXES):
            env[key] = value
    return env


class ExternalCommandJsonClient:
    """Run a configured command, prompt on stdin, JSON text on stdout."""

    def __init__(
        self,
        command: str,
        *,
        cwd: Path | None = None,
        inherit_env: bool = False,
    ) -> None:
        self.command = command.strip()
        if not self.command:
            raise ModelClientError("row author command is empty")
        parts = shlex.split(self.command)
        if not parts:
            raise ModelClientError("row author command is empty")
        if shutil.which(parts[0]) is None:
            raise ModelClientError(f"row author executable not found on PATH: {parts[0]}")
        self._parts = parts
        self.cwd = cwd
        self.inherit_env = inherit_env
        self.last_stderr = ""

    def complete_json(
        self,
        *,
        prompt: str,
        timeout_sec: int,
    ) -> str:
        env = os.environ.copy() if self.inherit_env else _sanitized_env()

        def _run(proc_cwd: Path) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                self._parts,
                input=prompt,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout_sec,
                check=False,
                cwd=proc_cwd,
                env=env,
            )

        try:
            if self.cwd is not None:
                proc = _run(self.cwd)
            else:
                with tempfile.TemporaryDirectory(prefix="keel-row-author-") as tmp:
                    proc = _run(Path(tmp))
        except subprocess.TimeoutExpired as exc:
            raise ModelClientError(
                f"row author command timed out after {timeout_sec}s"
            ) from exc
        except OSError as exc:
            raise ModelClientError(f"row author command failed to start: {exc}") from exc
        self.last_stderr = proc.stderr
        if proc.returncode != 0:
            raise ModelClientError(
                f"row author command exited {proc.returncode}: {proc.stderr.strip()}"
            )
        return proc.stdout


def parse_json_object_strict(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        raise ValueError("Model returned Markdown fence; expected raw JSON only.")
    decoder = json.JSONDecoder()
    obj, idx = decoder.raw_decode(text)
    remainder = text[idx:].strip()
    if remainder:
        raise ValueError("Model returned trailing content after JSON object.")
    if not isinstance(obj, dict):
        raise ValueError("Model JSON root must be an object.")
    return obj


def load_prompt_template(name: str) -> str:
    prompt_path = Path(__file__).resolve().parent / "prompts" / name
    return prompt_path.read_text(encoding="utf-8")


def render_prompt(template_name: str, variables: dict[str, str]) -> str:
    text = load_prompt_template(template_name)
    for key, value in variables.items():
        text = text.replace("{{" + key + "}}", value)
    return text
