"""CLI: wire the four compiler stages.

    python automation/gstack_to_markdown_playbook_v1/cli.py compile \\
      --repo-root . \\
      --design docs/gstack/<slug>-office-hours.md \\
      --autoplan docs/gstack/<slug>-autoplan.md \\
      --approved-brief docs/briefs/<slug>.approved-brief.md \\
      --out docs/playbooks/<slug>.playbook.md

The compiler never launches plan-orchestrator execution. When a plan-orchestrator root is
provided, it runs list-items + doctor as contract verification, then prints the exact
follow-up commands and exits.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from . import VALIDATION_REPORT_SCHEMA_ID
from .emit_markdown import emit_playbook_markdown
from .llm_clients import ModelClientError
from .parse_gstack import parse
from .quality_gates import validate_author_quality, warnings_as_compiler_warnings
from .row_author import RowAuthorError, RowAuthorOptions, build_author_trace, get_author
from .row_repair import repair_rows
from .stack_detect import detect
from .validators import validate, validate_ir_payload


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="gstack-to-markdown-playbook-v1",
        description="Compile approved gstack artifacts into plan-orchestrator markdown_playbook_v1.",
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    compile_p = sub.add_parser("compile", help="Compile a playbook from gstack inputs.")
    compile_p.add_argument("--repo-root", required=True, type=Path, help="Target product repo root.")
    compile_p.add_argument("--design", required=True, type=Path, help="Path to gstack design doc (e.g. /office-hours output).")
    compile_p.add_argument("--autoplan", type=Path, help="Optional path to /autoplan output.")
    compile_p.add_argument("--approved-brief", type=Path, help="Optional path to the approved build brief.")
    compile_p.add_argument("--out", required=True, type=Path, help="Output path for the playbook markdown.")
    compile_p.add_argument(
        "--row-author", default="stub",
        choices=["stub", "claude", "codex", "external-json"],
        help=(
            "Row author implementation: 'stub' (default), 'claude', 'codex', or "
            "'external-json'. Model-backed authors must output po_candidate_rows_v1 JSON."
        ),
    )
    compile_p.add_argument(
        "--row-author-command",
        default="",
        help=(
            "Override command for model-backed row authors. The rendered prompt is sent on stdin; "
            "stdout must be a single JSON object."
        ),
    )
    compile_p.add_argument(
        "--row-author-timeout-sec",
        type=int,
        default=180,
        help="Timeout in seconds for each model-backed row authoring or repair call.",
    )
    compile_p.add_argument(
        "--row-author-temperature",
        type=float,
        default=0.0,
        help="Recorded row-author temperature hint. External command authors receive only the prompt.",
    )
    repair_group = compile_p.add_mutually_exclusive_group()
    repair_group.add_argument(
        "--row-repair",
        dest="row_repair",
        action="store_true",
        default=True,
        help="Allow one bounded model-backed repair attempt after validation failure (default).",
    )
    repair_group.add_argument(
        "--no-row-repair",
        dest="row_repair",
        action="store_false",
        help="Disable the bounded repair attempt after validation failure.",
    )
    compile_p.add_argument(
        "--keep-author-artifacts",
        action="store_true",
        help="Write .ir.json, .rows.json, .author_input.json, and .author_trace.json on successful compiles.",
    )
    compile_p.add_argument(
        "--max-authored-rows",
        type=int,
        default=25,
        help="Maximum rows the author context asks a model-backed author to produce.",
    )
    compile_p.add_argument(
        "--allow-planning-gap-rows",
        action="store_true",
        help=(
            "If implementation tasks are behavioral but have no concrete paths, emit deterministic "
            "docs-only planning-gap rows instead of failing."
        ),
    )
    compile_p.add_argument(
        "--row-author-allow-repo-cwd",
        action="store_true",
        help=(
            "Debug-only escape hatch: run the model-backed row author from --repo-root "
            "instead of an isolated temporary directory."
        ),
    )
    compile_p.add_argument("--human-approved-by", default="", help="Name written into the playbook provenance header.")
    compile_p.add_argument("--dry-run", action="store_true", help="Use the deterministic stub author regardless of --row-author.")
    compile_p.add_argument(
        "--allow-stub-output",
        action="store_true",
        help="Allow scaffold-only stub output outside --dry-run. Forces every row through a signoff gate.",
    )
    compile_p.add_argument(
        "--allow-warnings",
        metavar="REASON",
        default="",
        help="Allow non-dry-run compiler warnings to pass. The reason is recorded in metadata.",
    )
    compile_p.add_argument(
        "--allow-outside-playbooks",
        action="store_true",
        help="Allow --out outside <repo-root>/docs/playbooks for tests or scratch output.",
    )
    compile_p.add_argument(
        "--plan-orchestrator-root",
        type=Path,
        help="Optional path to plan-orchestrator repo. When provided, PO verification runs unless --skip-po-verify is set.",
    )
    compile_p.add_argument(
        "--verify-with-po",
        action="store_true",
        help="Run plan-orchestrator list-items and doctor after emission. Requires --plan-orchestrator-root.",
    )
    compile_p.add_argument(
        "--skip-po-verify",
        metavar="REASON",
        default="",
        help="Skip mandatory PO verification even when --plan-orchestrator-root is provided. Reason is recorded.",
    )
    return p


def _slug(out_md: Path) -> str:
    """Strip a trailing '.playbook' from the stem so sidecars don't double it."""
    stem = out_md.stem
    return stem[: -len(".playbook")] if stem.endswith(".playbook") else stem


def _sidecar_path(out_md: Path, kind: str) -> Path:
    """kind is one of: 'meta', 'validation', 'ir', 'rows', 'author_input', 'author_trace'."""
    base = _slug(out_md)
    suffix = {
        "meta": ".playbook.meta.json",
        "validation": ".validation.json",
        "ir": ".ir.json",
        "rows": ".rows.json",
        "author_input": ".author_input.json",
        "author_trace": ".author_trace.json",
    }[kind]
    return out_md.with_name(base + suffix)


def _write_sidecar(out_md: Path, kind: str, payload: dict) -> Path:
    sibling = _sidecar_path(out_md, kind)
    sibling.parent.mkdir(parents=True, exist_ok=True)
    sibling.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return sibling


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _compiler_git_sha() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parents[2],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _failure_report(code: str, message: str) -> dict:
    return {
        "schema_version": VALIDATION_REPORT_SCHEMA_ID,
        "validated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status": "fail",
        "errors": [
            {
                "code": code,
                "severity": "error",
                "message": message,
            }
        ],
        "warnings": [],
        "row_summaries": [],
        "repair_attempts": 0,
    }


def _report_passed(report: dict) -> bool:
    return report.get("status") in {"pass", "repaired_pass"} and not report.get("errors")


def _merge_quality_into_report(report: dict, quality: dict) -> dict:
    report["errors"] = [*report.get("errors", []), *quality.get("errors", [])]
    report["warnings"] = [*report.get("warnings", []), *quality.get("warnings", [])]
    if report["errors"]:
        report["status"] = "fail"
    return report


def _append_compiler_warnings(bundle, warnings: list[str]) -> None:
    seen = set(bundle.compiler_warnings)
    for warning in warnings:
        if warning not in seen:
            bundle.compiler_warnings.append(warning)
            seen.add(warning)


def _report_warnings_as_strings(report: dict) -> list[str]:
    out: list[str] = []
    for warning in report.get("warnings", []):
        code = warning.get("code", "WARNING")
        message = warning.get("message", "")
        step = warning.get("step_id")
        prefix = f"{code}"
        if step:
            prefix += f"[{step}]"
        out.append(f"{prefix}: {message}")
    return out


def _write_diagnostic_sidecars(
    *,
    out_md: Path,
    ir_payload: dict,
    report: dict,
    bundle=None,
    author_input: dict | None = None,
    author_trace: dict | None = None,
) -> None:
    out_md.parent.mkdir(parents=True, exist_ok=True)
    _write_sidecar(out_md, "validation", report)
    _write_sidecar(out_md, "ir", ir_payload)
    if bundle is not None:
        _write_sidecar(out_md, "rows", bundle.to_dict())
    if author_input is not None:
        _write_sidecar(out_md, "author_input", author_input)
    if author_trace is not None:
        _write_sidecar(out_md, "author_trace", author_trace)


def _print_next_steps(out_md: Path, plan_orchestrator_root: Path | None) -> None:
    if plan_orchestrator_root is not None:
        prefix = f"python {plan_orchestrator_root}/automation/run_plan_orchestrator.py"
    else:
        prefix = "python /path/to/plan-orchestrator/automation/run_plan_orchestrator.py"
    print("\nNext:")
    print(f"{prefix} list-items --playbook {out_md}")
    print(f"{prefix} doctor --playbook {out_md} --format json")


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _enforce_output_path(repo_root: Path, out_md: Path, *, allow_outside: bool) -> None:
    expected_root = repo_root / "docs" / "playbooks"
    if allow_outside:
        return
    if not _is_relative_to(out_md, expected_root):
        raise ValueError(
            f"--out must be under {expected_root} unless --allow-outside-playbooks is set."
        )


def _repo_relative_required(path: Path, repo_root: Path, *, label: str) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(repo_root.resolve())
    except ValueError as exc:
        raise ValueError(
            f"{label} must be under --repo-root. Promote gstack artifacts into docs/gstack "
            f"or docs/briefs first: {path}"
        ) from exc
    return resolved


def _force_stub_manual_gates(bundle) -> None:
    for row in bundle.rows:
        if row.manual_gate == "none":
            row.manual_gate = "signoff"
            row.manual_gate_reason = (
                row.manual_gate_reason
                or "Stub-authored scaffold row requires human signoff before any PO execution."
            )
            if not row.manual_gate_evidence:
                row.manual_gate_evidence = ["human-reviewed scaffold row"]
        if "stub-output-forced-signoff" not in row.notes:
            row.notes.append("stub-output-forced-signoff")


def _run_po_verification(*, out_md: Path, plan_orchestrator_root: Path) -> dict:
    """Verify the emitted playbook is parseable+normalizable by plan-orchestrator.

    The compiler only validates the *playbook contract* here, not the user's
    overall PO operational readiness. Specifically:

    - `list-items` must succeed (the parser must consume the markdown).
    - `doctor --playbook` may report non-playbook check failures
      (e.g. `git_identity`, `clean_tracked_checkout`, `agent_environment`)
      without failing the compile, because those concern *future PO execution*
      on the user's machine, not whether this playbook artifact is contract-valid.
      We parse doctor's JSON and require `playbook_parse` and `playbook_normalize`
      specifically to be "ok".

    Use sys.executable rather than literal "python" so the compiler subprocesses
    the same interpreter that's running it. Systems that ship only `python3`
    (and no bare `python` symlink) would otherwise fail here.
    """
    runner = plan_orchestrator_root / "automation" / "run_plan_orchestrator.py"
    if not runner.is_file():
        return {
            "status": "fail",
            "error": f"plan-orchestrator runner not found: {runner}",
            "commands": [],
        }
    env = os.environ.copy()
    env.setdefault("PLAN_ORCHESTRATOR_CLEAN_ENV_CONFIRMED", "1")

    def _run(cmd: list[str]) -> dict:
        proc = subprocess.run(
            cmd,
            cwd=plan_orchestrator_root,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        return {
            "command": cmd,
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
        }

    results: list[dict] = []

    list_cmd = [sys.executable, str(runner), "list-items", "--playbook", str(out_md), "--format", "json"]
    list_result = _run(list_cmd)
    results.append(list_result)
    if list_result["returncode"] != 0:
        return {"status": "fail", "reason": "list-items failed", "commands": results}

    doctor_cmd = [sys.executable, str(runner), "doctor", "--playbook", str(out_md), "--format", "json"]
    doctor_result = _run(doctor_cmd)
    results.append(doctor_result)

    try:
        doctor_data = json.loads(doctor_result["stdout"])
    except json.JSONDecodeError:
        return {
            "status": "fail",
            "reason": "doctor output was not valid JSON",
            "commands": results,
        }

    playbook_check_names = {"playbook_parse", "playbook_normalize"}
    playbook_checks: dict[str, str] = {}
    non_playbook_failures: list[str] = []
    for check in doctor_data.get("checks", []):
        name = check.get("name", "")
        status = check.get("status", "")
        if name in playbook_check_names:
            playbook_checks[name] = status
        elif status not in ("ok", "skipped"):
            non_playbook_failures.append(f"{name}={status}")

    missing = playbook_check_names - playbook_checks.keys()
    failed = [n for n, s in playbook_checks.items() if s != "ok"]
    if missing or failed:
        return {
            "status": "fail",
            "reason": (
                f"playbook checks not ok: missing={sorted(missing)}, failed={sorted(failed)}"
            ),
            "commands": results,
            "non_playbook_warnings": non_playbook_failures,
        }

    return {
        "status": "pass",
        "commands": results,
        "non_playbook_warnings": non_playbook_failures,
    }


def cmd_compile(args: argparse.Namespace) -> int:
    repo_root: Path = args.repo_root.resolve()
    out_md: Path = args.out.resolve()
    plan_orchestrator_root = args.plan_orchestrator_root.resolve() if args.plan_orchestrator_root else None

    if args.verify_with_po and args.skip_po_verify:
        print("error: --verify-with-po and --skip-po-verify are mutually exclusive.", file=sys.stderr)
        return 2
    if args.verify_with_po and plan_orchestrator_root is None:
        print("error: --verify-with-po requires --plan-orchestrator-root.", file=sys.stderr)
        return 2

    try:
        _enforce_output_path(repo_root, out_md, allow_outside=args.allow_outside_playbooks)
        design_path = _repo_relative_required(args.design, repo_root, label="--design")
        autoplan_path = (
            _repo_relative_required(args.autoplan, repo_root, label="--autoplan")
            if args.autoplan else None
        )
        approved_brief_path = (
            _repo_relative_required(args.approved_brief, repo_root, label="--approved-brief")
            if args.approved_brief else None
        )
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    # Stage 0: detect stack
    stack_profile = detect(repo_root)

    # Stage 1: parse
    ir = parse(
        design_path=design_path,
        autoplan_path=autoplan_path,
        approved_brief_path=approved_brief_path,
        stack_profile=stack_profile,
        repo_root=repo_root,
    )
    ir_schema_errors = validate_ir_payload(ir.to_dict())
    if ir_schema_errors:
        print("error: parsed IR failed bundled JSON schema validation.", file=sys.stderr)
        for err in ir_schema_errors:
            print(f"  [{err['code']}]: {err['message']}", file=sys.stderr)
        out_md.parent.mkdir(parents=True, exist_ok=True)
        _write_sidecar(out_md, "ir", ir.to_dict())
        return 3

    # Stage 2: row author
    author_name = "stub" if args.dry_run else args.row_author
    if author_name == "stub" and not args.dry_run and not args.allow_stub_output:
        print(
            "error: row_author='stub' is scaffold-only. Use --dry-run or pass "
            "--allow-stub-output for an explicit scaffold compile.",
            file=sys.stderr,
        )
        return 2
    try:
        author = get_author(
            author_name,
            command=args.row_author_command,
            cwd=repo_root if args.row_author_allow_repo_cwd else None,
        )
    except (ModelClientError, NotImplementedError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    author_options = RowAuthorOptions(
        timeout_sec=args.row_author_timeout_sec,
        repair_enabled=args.row_repair,
        max_rows=args.max_authored_rows,
        allow_planning_gap_rows=args.allow_planning_gap_rows,
        temperature=args.row_author_temperature,
    )
    try:
        author_result = author.author(
            ir=ir,
            repo_root=repo_root,
            options=author_options,
        )
    except RowAuthorError as e:
        report = _failure_report(e.code, e.message)
        print(f"error: {e.message}", file=sys.stderr)
        _write_diagnostic_sidecars(
            out_md=out_md,
            ir_payload=ir.to_dict(),
            report=report,
            bundle=e.bundle,
            author_input=e.author_input,
            author_trace=e.trace,
        )
        return 3
    bundle = author_result.bundle
    author_input = author_result.author_input
    author_trace = author_result.trace

    if author_name == "stub":
        if ir.manual_gate_hints and all(row.manual_gate == "none" for row in bundle.rows):
            bundle.compiler_warnings.append(
                "manual_gate_hints_ignored: source artifacts mention manual approval/review, but no row has a manual_gate."
            )
        if ir.external_dependency_hints and all(row.external_check == "none" for row in bundle.rows):
            bundle.compiler_warnings.append(
                "external_dependency_hints_ignored: source artifacts mention external dependencies, but no row requires external evidence."
            )
    if author_name == "stub" and not args.dry_run and args.allow_stub_output:
        _force_stub_manual_gates(bundle)
        bundle.compiler_warnings.append(
            "compiler-stub: --allow-stub-output used; every row was forced to manual_gate=signoff."
        )

    # Stage 3: validate
    report = validate(bundle, repo_root=repo_root)
    quality = {"status": "pass", "errors": [], "warnings": []}
    if author_name != "stub":
        quality = validate_author_quality(
            bundle=bundle,
            ir=ir,
            author_context=author_input,
        )
        _append_compiler_warnings(bundle, warnings_as_compiler_warnings(quality))
        report = _merge_quality_into_report(report, quality)

    repair_attempted = False
    if (
        not _report_passed(report)
        and author_name != "stub"
        and author_options.repair_enabled
        and getattr(author, "model_client", None) is not None
    ):
        repair_attempted = True
        report["repair_attempts"] = 1
        try:
            original_author_trace = dict(author_trace)
            repair_result = repair_rows(
                ir=ir,
                author_context=author_input,
                failed_bundle=bundle,
                validation_report=report,
                quality_findings=quality,
                model_client=author.model_client,
                timeout_sec=author_options.timeout_sec,
            )
            bundle = repair_result.bundle
            author_result.bundle = bundle
            author_result.repair_attempted = True
            author_trace = build_author_trace(
                row_author=f"{author_name}:repaired",
                prompt="",
                bundle=bundle,
                author_context=author_input,
                warnings=list(bundle.compiler_warnings),
            )
            author_trace["repair_attempted"] = True
            author_trace["initial_trace"] = original_author_trace
            author_trace["repair_trace"] = repair_result.trace
            report = validate(bundle, repo_root=repo_root)
            quality = validate_author_quality(
                bundle=bundle,
                ir=ir,
                author_context=author_input,
            )
            _append_compiler_warnings(bundle, warnings_as_compiler_warnings(quality))
            report = _merge_quality_into_report(report, quality)
            report["repair_attempts"] = 1
            if _report_passed(report):
                report["status"] = "repaired_pass"
        except Exception as e:  # noqa: BLE001 - repair must fail closed with diagnostics.
            report.setdefault("errors", []).append(
                {
                    "code": "AUTHOR_REPAIR_FAILED",
                    "severity": "error",
                    "message": f"bounded row repair failed: {e}",
                }
            )
            report["status"] = "fail"
            author_trace["repair_attempted"] = True
            author_trace["repair_error"] = str(e)

    _append_compiler_warnings(bundle, _report_warnings_as_strings(report))

    if not _report_passed(report):
        print("error: compiler preflight failed; refusing to emit playbook.", file=sys.stderr)
        for err in report["errors"]:
            loc = err.get("step_id", "-")
            col = err.get("column", "-")
            print(f"  [{err['code']}] step={loc} col={col}: {err['message']}", file=sys.stderr)
        _write_diagnostic_sidecars(
            out_md=out_md,
            ir_payload=ir.to_dict(),
            report=report,
            bundle=bundle,
            author_input=author_input,
            author_trace=author_trace,
        )
        return 3
    if bundle.compiler_warnings and not args.dry_run and not args.allow_warnings:
        print("error: non-dry-run compiler warnings require --allow-warnings REASON.", file=sys.stderr)
        for w in bundle.compiler_warnings:
            print(f"  - {w}", file=sys.stderr)
        _write_diagnostic_sidecars(
            out_md=out_md,
            ir_payload=ir.to_dict(),
            report=report,
            bundle=bundle,
            author_input=author_input,
            author_trace=author_trace,
        )
        return 3

    # Stage 4: emit
    md = emit_playbook_markdown(
        ir=ir,
        bundle=bundle,
        human_approved_by=args.human_approved_by,
    )
    out_md.parent.mkdir(parents=True, exist_ok=True)
    tmp_out_md = out_md.with_name(out_md.name + ".tmp")
    tmp_out_md.write_text(md, encoding="utf-8")

    should_verify_with_po = bool(args.verify_with_po or plan_orchestrator_root)
    po_verification = {
        "status": "not_run",
        "reason": "no plan-orchestrator root was provided",
    }
    if args.skip_po_verify:
        should_verify_with_po = False
        po_verification = {"status": "skipped", "reason": args.skip_po_verify}
    if should_verify_with_po:
        po_verification = _run_po_verification(
            out_md=tmp_out_md,
            plan_orchestrator_root=plan_orchestrator_root,
        )
        if po_verification["status"] != "pass":
            _write_sidecar(out_md, "validation", report)
            tmp_out_md.unlink(missing_ok=True)
            print("error: PO contract verification failed.", file=sys.stderr)
            for result in po_verification.get("commands", []):
                print(f"  command: {' '.join(result['command'])}", file=sys.stderr)
                print(f"  returncode: {result['returncode']}", file=sys.stderr)
                if result.get("stderr"):
                    print(result["stderr"], file=sys.stderr)
            return 4

    tmp_out_md.replace(out_md)
    emitted_sha256 = _sha256_file(out_md)

    # Sidecar artifacts
    _write_sidecar(out_md, "meta", {
        "schema_version": "gstack_to_markdown_playbook_v1.meta.v1",
        "compiled_by": "gstack_to_markdown_playbook_v1",
        "compiler_version": __version__,
        "compiler_git_sha": _compiler_git_sha(),
        "compiled_at": ir.compiled_at,
        "row_author": author_name,
        "row_repair_attempted": repair_attempted,
        "compiler_preflight": report["status"],
        "po_contract_verification": po_verification,
        "warning_override_reason": args.allow_warnings,
        "skip_po_verify_reason": args.skip_po_verify,
        "source_artifacts": [s.__dict__ for s in ir.source_artifacts],
        "emitted_playbook_path": str(out_md),
        "emitted_playbook_sha256": emitted_sha256,
        "row_count": len(bundle.rows),
        "compiler_warnings": bundle.compiler_warnings,
    })
    _write_sidecar(out_md, "validation", report)
    if args.keep_author_artifacts or author_name != "stub":
        _write_sidecar(out_md, "ir", ir.to_dict())
        _write_sidecar(out_md, "rows", bundle.to_dict())
        _write_sidecar(out_md, "author_input", author_input)
        _write_sidecar(out_md, "author_trace", author_trace)

    print(f"Wrote:")
    print(f"  - {out_md}")
    print(f"  - {_sidecar_path(out_md, 'meta')}")
    print(f"  - {_sidecar_path(out_md, 'validation')}")
    if args.keep_author_artifacts or author_name != "stub":
        print(f"  - {_sidecar_path(out_md, 'ir')}")
        print(f"  - {_sidecar_path(out_md, 'rows')}")
        print(f"  - {_sidecar_path(out_md, 'author_input')}")
        print(f"  - {_sidecar_path(out_md, 'author_trace')}")
    if bundle.compiler_warnings:
        print("\nCompiler warnings (review before running PO):")
        for w in bundle.compiler_warnings:
            print(f"  - {w}")
    if po_verification["status"] == "pass":
        print("\nPO contract verification: pass")
    elif po_verification["status"] == "skipped":
        print(f"\nPO contract verification: skipped ({po_verification['reason']})")
    _print_next_steps(out_md, plan_orchestrator_root)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "compile":
        return cmd_compile(args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
