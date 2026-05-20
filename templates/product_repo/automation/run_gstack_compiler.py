#!/usr/bin/env python3
"""Pinned product-repo shim for the shared Keel gstack compiler.

Copy this file to a product repo as `automation/run_gstack_compiler.py`, then
set `GSTACK_COMPILER_ROOT` to the reviewed local checkout of Keel's
`tools/compiler`. Product repos should pin the compiler checkout by git
commit or release tag instead of vendoring a copy of the compiler.

For daily use most readers should prefer `keel-compile` from `~/keel/bin/`.
This shim exists for product repos that want a tracked, version-pinned
invocation independent of whatever's currently on PATH.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


PINNED_COMPILER_ROOT = os.environ.get(
    "GSTACK_COMPILER_ROOT",
    str(Path.home() / "keel" / "tools" / "compiler"),
)


def main() -> int:
    compiler_root = Path(PINNED_COMPILER_ROOT).expanduser().resolve()
    package_root = compiler_root / "automation"
    cli_path = package_root / "gstack_to_markdown_playbook_v1" / "cli.py"
    if not cli_path.is_file():
        print(
            f"error: pinned gstack compiler checkout not found at {compiler_root}",
            file=sys.stderr,
        )
        print(
            "Set GSTACK_COMPILER_ROOT to the reviewed Keel compiler checkout (~/keel/tools/compiler).",
            file=sys.stderr,
        )
        return 2

    sys.path.insert(0, str(compiler_root))
    from automation.gstack_to_markdown_playbook_v1.cli import main as compiler_main

    return int(compiler_main(sys.argv[1:]))


if __name__ == "__main__":
    raise SystemExit(main())
