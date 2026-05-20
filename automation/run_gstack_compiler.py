"""Top-level CLI entrypoint for gstack-to-markdown-playbook-v1.

Mirrors plan-orchestrator/automation/run_plan_orchestrator.py: a thin shim that imports the
package CLI. Allows invocation as:

    python automation/run_gstack_compiler.py compile \\
      --repo-root . \\
      --design docs/gstack/<slug>-office-hours.md \\
      --out docs/playbooks/<slug>.playbook.md

You can also invoke the CLI directly as a module:

    python -m automation.gstack_to_markdown_playbook_v1.cli compile ...
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure the repo root is on sys.path when invoked as a top-level script.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from automation.gstack_to_markdown_playbook_v1.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
