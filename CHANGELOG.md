# Changelog

All notable changes to the gstack playbook compiler are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project aims to follow [Semantic Versioning](https://semver.org/).

## [0.2.0] - 2026-05-21

### Added

- Model-backed Step 2 row authoring through JSON-only external commands:
  `external-json`, `claude`, and `codex`.
- Deterministic `row_author_context_v1` sidecars, author traces, prompt/output
  hashes, and one bounded repair attempt.
- Shared path policy, safe-deliverable quality gates, verification-command
  safety validation, and parser support for table-formatted implementation
  tasks.
- Compile-failure diagnostics under `.compile-failed.*`, including PO contract
  verification payloads.

### Changed

- Source artifact paths are recorded repo-relative when `--repo-root` is known.
- Source inputs must be promoted under `docs/gstack/` or `docs/briefs/` by
  default, with an explicit noncanonical-input escape hatch for tests.
- External row-author commands run from an isolated temporary cwd with a
  sanitized environment by default.
- Verification commands are safety-checked for every row, including docs-only
  rows.
- The emitter always writes all six `markdown_playbook_v1` sections and refuses
  raw pipe characters instead of mutating them.

## [0.1.0] - 2026-05-20

Initial public release.

### Added

- Four-stage compiler: Python parse → candidate row authoring → fail-closed
  validation → deterministic Markdown emission.
- `gstack_plan_ir_v1`, `po_candidate_rows_v1`, and
  `compiler_validation_report_v1` schemas.
- Deterministic stub row author for scaffold output. Real LLM row authors
  (`claude`, `codex`) are reserved for future implementation and currently
  raise `NotImplementedError`.
- Plan-orchestrator contract verification: when `--plan-orchestrator-root` is
  supplied, the compiler runs PO `list-items` and `doctor --playbook` after
  emission.
- Conservative alpha gates: non-dry-run stub output requires
  `--allow-stub-output`; non-dry-run warnings require `--allow-warnings REASON`;
  output outside `docs/playbooks/` requires `--allow-outside-playbooks`.
- Provenance sidecar recording compiler version, source hashes, emitted
  playbook hash, warnings, and PO verification status.
- Product-repo shim template under `templates/product_repo/`.

### Notes

- This release is intentionally alpha. The stub author is scaffold-only;
  treat its output as a draft that needs human review before plan-orchestrator
  executes it.
- The compiler never launches plan-orchestrator execution and never calls
  `mark-manual-gate`.
