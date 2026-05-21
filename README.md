# compiler (gstack → markdown_playbook_v1)

The fast-lane translator of [**Keel**](https://github.com/AysajanE/keel), the
local-first toolchain that ships AI-written code you can trust. This repo is
installed automatically by Keel's `install.sh`; most users never clone it
directly.

Local canonical path once installed: `$KEEL_ROOT/tools/compiler`

Daily invocation: the `keel-compile` wrapper at `~/keel/bin/keel-compile`.

Package and console-script name: `gstack-to-markdown-playbook-v1` (the package
name describes the output schema, which is the stable contract; the directory
name is just `compiler` because that's what it is).

Compile approved gstack design artifacts into a `markdown_playbook_v1` scaffold for [plan-orchestrator](https://github.com/AysajanE/plan-orchestrator) to validate and execute after human review.

This is the **fast lane** of the Keel toolchain:

```text
gstack /office-hours, /autoplan
  → docs/gstack/<slug>-office-hours.md
  → docs/gstack/<slug>-autoplan.md
  → docs/briefs/<slug>.approved-brief.md (optional)
  ↓
keel-compile (this tool)
  ↓
docs/playbooks/<slug>.playbook.md
  ↓
PO list-items + doctor contract verification (keel-run / keel-doctor)
  ↓
human review
  ↓
keel-run supervise run
```

The high-stakes lane target uses [staged-workflow-runner](https://github.com/AysajanE/staged-workflow-runner) instead of this compiler. The generic `gstack_design_to_po_playbook` pack is scaffolded but should be treated as a reviewed planning path, not an execution path. Both lanes must end in PO `list-items` + `doctor --playbook` verification.

## Architecture

Four stages, with a deliberately conservative Step 2 boundary:

```text
Stage 1: Python parse gstack artifacts             → gstack_plan_ir_v1.json
Stage 2: Candidate row authoring                   → po_candidate_rows_v1.json
         stub: scaffold-only dry-run/default
         external-json: command-backed JSON author
         claude/codex: command aliases, still external and JSON-only
         one bounded repair attempt by default
Stage 3: Python compiler preflight (fail closed)   → compiler_validation_report_v1.json
Stage 4: Python emit (deterministic markdown)      → <slug>.playbook.md
Post-check: PO list-items + doctor --playbook      → po_contract_verification
```

Key design rule: **model-backed authors may author candidate rows only**. Python owns:

- final Markdown table formatting (avoids parser drift)
- validation verdicts (fails closed on schema, paths, narrow-roots, prereqs)
- allowed_write_roots safety decisions
- PO contract verification when `--plan-orchestrator-root` is known
- any human-gate work (the compiler never touches `mark-manual-gate`)

Current status: `stub` remains scaffold-only. Non-dry-run stub output fails unless `--allow-stub-output` is explicit, and non-dry-run warnings fail unless `--allow-warnings REASON` is provided. Model-backed authors run as JSON-only planning calls from an isolated temporary cwd by default; they must not implement code or mutate the product repo.

One bounded model-backed repair attempt is enabled by default and can be disabled with `--no-row-repair`. Python validates the repaired candidate exactly like the initial candidate.

## Install

```bash
python -m pip install -e .
```

Optional dev extras:

```bash
python -m pip install -e .[dev]
```

## Product-Repo Shim

Keep the compiler as one shared checkout. Product repos that want a local command can copy:

```text
templates/product_repo/automation/run_gstack_compiler.py
```

to:

```text
<product-repo>/automation/run_gstack_compiler.py
```

Pin `GSTACK_COMPILER_ROOT` to `$KEEL_ROOT/tools/compiler` or another reviewed compiler checkout/release tag. The compiler meta sidecar records `compiler_version`, `compiler_git_sha`, emitted playbook SHA, and PO verification status so the product repo can prove which compiler produced a playbook without vendoring the compiler.

## Quick start

```bash
python automation/gstack_to_markdown_playbook_v1/cli.py compile \
  --repo-root . \
  --design docs/gstack/<slug>-office-hours.md \
  --autoplan docs/gstack/<slug>-autoplan.md \
  --approved-brief docs/briefs/<slug>.approved-brief.md \
  --out docs/playbooks/<slug>.playbook.md \
  --row-author external-json \
  --row-author-command "claude -p" \
  --plan-orchestrator-root $KEEL_ROOT/tools/plan-orchestrator
```

The model-backed row author must return raw `po_candidate_rows_v1` JSON on stdout. The compiler sends the prompt on stdin from an isolated cwd with obvious repo/path/secret environment variables removed, validates the JSON, optionally performs one repair attempt, emits Markdown itself, and runs PO contract verification when configured.

Dry run (uses deterministic stub row author; no LLM needed):

```bash
python automation/gstack_to_markdown_playbook_v1/cli.py compile \
  --repo-root . \
  --design docs/gstack/<slug>-office-hours.md \
  --out docs/playbooks/<slug>.playbook.md \
  --dry-run \
  --plan-orchestrator-root $KEEL_ROOT/tools/plan-orchestrator
```

When `--plan-orchestrator-root` is supplied, the compiler runs:

```bash
python $KEEL_ROOT/tools/plan-orchestrator/automation/run_plan_orchestrator.py list-items \
  --playbook docs/playbooks/<slug>.playbook.md
python $KEEL_ROOT/tools/plan-orchestrator/automation/run_plan_orchestrator.py doctor \
  --playbook docs/playbooks/<slug>.playbook.md --format json
```

Use `--skip-po-verify "reason"` only for local experiments.

The compiler writes three sibling artifacts:

```text
docs/playbooks/<slug>.playbook.md
docs/playbooks/<slug>.playbook.meta.json
docs/playbooks/<slug>.validation.json
```

Model-backed compiles also write:

```text
docs/playbooks/<slug>.ir.json
docs/playbooks/<slug>.rows.json
docs/playbooks/<slug>.author_input.json
docs/playbooks/<slug>.author_trace.json
```

Failed compiles never overwrite those official sidecars. Candidate diagnostics
are written under `.compile-failed.*` names, for example
`docs/playbooks/<slug>.compile-failed.validation.json`, so an older successful
playbook cannot be paired with a failed candidate's rows or trace.

The meta sidecar records compiler version, source hashes, emitted playbook hash, warnings, and PO verification status. The compiler never executes PO runs or manual gates.

```text
Next:
python $KEEL_ROOT/tools/plan-orchestrator/automation/run_plan_orchestrator.py list-items \
  --playbook docs/playbooks/<slug>.playbook.md
python $KEEL_ROOT/tools/plan-orchestrator/automation/run_plan_orchestrator.py doctor \
  --playbook docs/playbooks/<slug>.playbook.md --format json
```

## Boundaries

The compiler must not:

- emit a playbook that has not passed compiler preflight
- treat compiler preflight as the final contract authority; PO remains canonical
- author the markdown table itself (the LLM only emits JSON rows)
- populate reserved playbook columns (`change_profile`, `execution_mode`, `host_commands`)
- launch plan-orchestrator execution
- call `mark-manual-gate`
- write outside `docs/playbooks/` unless `--allow-outside-playbooks` is explicit
- fabricate repo paths the parser did not extract from authored gstack inputs
- emit cells containing `|`; PO's parser does not support escaped pipes

The public PO contract accepts some broad roots for hand-authored playbooks.
The compiler is stricter: model-authored rows must use narrow roots and may not
emit `src`, `tests`, or `test`.

## Repository layout

```text
automation/gstack_to_markdown_playbook_v1/
  cli.py              # argparse entrypoint, wires the four stages
  parse_gstack.py     # Stage 1: Python parse → IR
  stack_detect.py     # repo stack detection (Python / Node / etc.)
  ir_models.py        # dataclasses for gstack_plan_ir_v1
  row_models.py       # dataclasses for po_candidate_rows_v1
  row_author.py       # Stage 2: stub and model-backed JSON authors
  author_context.py   # deterministic row_author_context_v1 builder
  quality_gates.py    # semantic checks beyond JSON schema
  validators.py       # Stage 3: deterministic validation
  emit_markdown.py    # Stage 4: deterministic markdown emitter
  provenance.py       # HTML-comment provenance header
  schemas/
    gstack_plan_ir_v1.schema.json
    po_candidate_rows_v1.schema.json
    compiler_validation_report_v1.schema.json
    row_author_context_v1.schema.json
    row_author_trace_v1.schema.json
    row_repair_trace_v1.schema.json
  prompts/
    row_author_v2.md
    row_repair_v2.md
  tests/
    test_smoke.py
    test_cli_guards.py
    test_parse_gstack_tasks.py
    test_validate_paths.py
    test_emit_po_roundtrip.py
```

## License

MIT. See `LICENSE`.
