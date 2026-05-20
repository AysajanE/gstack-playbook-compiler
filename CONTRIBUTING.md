# Contributing

This is the gstack → `markdown_playbook_v1` compiler — the fast lane of
[Keel](https://github.com/AysajanE/keel). Contributions are welcome. The rules
below exist because this tool emits a contract that another tool
(plan-orchestrator) executes against a real repository.

## The contract is the product

The compiler's only job is to produce a valid `markdown_playbook_v1`. That
contract is more important than any single implementation detail. A change that
makes the compiler faster or cleaner but weakens the contract is not an
improvement.

Hard rules — a PR that breaks any of these will not be merged:

- **Python owns the final Markdown.** A future LLM row author may emit
  candidate JSON rows only. It must never author the Markdown table itself —
  that would invite parser drift.
- **Python owns validation verdicts.** Validation fails closed. If a row is
  unsafe, ambiguous, or unparseable, the compiler stops and writes a diagnostic
  sidecar; it does not "best-effort" its way to an emitted playbook.
- **Narrow write roots.** The compiler must never widen `allowed_write_roots` or
  emit broad roots like `.`, `src`, or `tests`.
- **No reserved columns.** The compiler must never populate `change_profile`,
  `execution_mode`, or `host_commands`. plan-orchestrator derives those.
- **No path invention.** The compiler must only emit repo paths it actually
  observed in the authored gstack inputs.
- **No execution, no gates.** The compiler never launches plan-orchestrator and
  never calls `mark-manual-gate`.

## Local checks

```bash
python -m pip install -e .[dev]
python -m unittest discover -s automation/gstack_to_markdown_playbook_v1/tests -p 'test_*.py'
```

The round-trip test compiles a playbook and validates it against a sibling
`plan-orchestrator` checkout. CI clones plan-orchestrator automatically; for a
local run, keep `plan-orchestrator` checked out next to this repo or rely on
the Keel install layout (`$KEEL_ROOT/tools/`).

## Adding a row author

Stage 2 is the extension point. New authors (`claude`, `codex`, future models)
must:

1. Emit only `po_candidate_rows_v1` JSON — never Markdown.
2. Pass every row through the existing Stage 3 validators unchanged.
3. Add fixtures and tests under
   `automation/gstack_to_markdown_playbook_v1/tests/`.

Do not relax a validator to make a new author pass. If a validator is wrong,
fix the validator deliberately, with a test that proves the new behavior is
correct.

## Pull requests

- Keep PRs focused on one change.
- Include tests for behavioral changes.
- Do not commit generated local files (`.local/`, `.venv/`, build output).
- Explain *why* in the PR description, not just *what*.
