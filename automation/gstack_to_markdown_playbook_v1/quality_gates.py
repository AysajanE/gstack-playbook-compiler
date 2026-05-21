"""Semantic quality gates for Step-2 row author output."""

from __future__ import annotations

import re
from typing import Any

from .ir_models import GstackPlanIR
from .path_policy import (
    classify_path,
    normalize_repo_path,
    path_inside_any_root,
    root_derived_from_known_path,
)
from .row_models import CandidateRow, CandidateRowsBundle
from .verification_policy import is_behavioral_path, is_test_path

PLACEHOLDER_PATTERNS = (
    re.compile(r"\bTBD\b", re.I),
    re.compile(r"\bTODO\b"),
    re.compile(r"\bfill in\b", re.I),
    re.compile(r"\bplaceholder\b", re.I),
    re.compile(r"\.placeholder\b", re.I),
    re.compile(r"\bexample/path\b", re.I),
    re.compile(r"\bvarious files\b", re.I),
    re.compile(r"\brepo changes\b", re.I),
    re.compile(r"\badd tests as needed\b", re.I),
    re.compile(r"\bcompiler-stub\b", re.I),
)
ACTION_VERBS = (
    "add",
    "build",
    "convert",
    "create",
    "configure",
    "delete",
    "document",
    "draft",
    "expose",
    "extend",
    "extract",
    "generate",
    "implement",
    "introduce",
    "migrate",
    "move",
    "normalize",
    "publish",
    "refactor",
    "register",
    "remove",
    "replace",
    "run",
    "seed",
    "test",
    "turn",
    "update",
    "validate",
    "verify",
    "wire",
    "write",
)
RISKY_MANUAL_GATE_TERMS = (
    "security",
    "auth",
    "deploy",
    "production",
    "migration",
    "payment",
    "presenter",
    "release",
    "secret",
)
RISKY_TEXT_TERMS = (
    "auth",
    "authorization",
    "permission",
    "secret",
    "payment",
    "stripe",
    "deploy",
    "production",
)


def _finding(
    code: str,
    severity: str,
    message: str,
    *,
    step_id: str | None = None,
    column: str | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {"code": code, "severity": severity, "message": message}
    if step_id:
        out["step_id"] = step_id
    if column:
        out["column"] = column
    return out


def _tokens_from_prereqs(value: str) -> list[str]:
    raw = value.strip()
    if not raw or raw.lower() == "none":
        return []
    out: list[str] = []
    for token in [part.strip() for part in raw.split(",") if part.strip()]:
        if re.fullmatch(r"[0-9]{2}-[0-9]{2}", token):
            start, end = token.split("-")
            if int(start) > int(end):
                out.extend([start, end])
                continue
            width = max(len(start), len(end))
            for value in range(int(start), int(end) + 1):
                out.append(str(value).zfill(width))
        else:
            out.append(token)
    return out


def _all_path_values(row: CandidateRow) -> list[tuple[str, str]]:
    values: list[tuple[str, str]] = []
    for column in (
        "repo_surfaces",
        "deliverable",
        "consult_paths",
        "required_verification_artifacts",
    ):
        for path in getattr(row, column):
            values.append((column, normalize_repo_path(path)))
    return values


def _source_task_ids_from_row(row: CandidateRow) -> set[str]:
    ids: set[str] = set()
    text = " ".join(row.notes)
    for match in re.finditer(r"source_task:\s*(task_[0-9]{3})", text):
        ids.add(match.group(1))
    return ids


def _has_placeholder_text(row: CandidateRow) -> tuple[str, str] | None:
    fields: list[tuple[str, str]] = [
        ("action", row.action),
        ("exit_criteria", row.exit_criteria),
        ("deliverable", " ".join(row.deliverable)),
        ("notes", " ".join(row.notes)),
    ]
    for column, text in fields:
        for pattern in PLACEHOLDER_PATTERNS:
            if pattern.search(text):
                return column, pattern.pattern
    return None


def _action_specificity_error(row: CandidateRow) -> str | None:
    action = row.action.strip()
    if len(action) < 12 or len(action) > 240:
        return "action must be between 12 and 240 characters"
    first = action.split(maxsplit=1)[0].lower().strip(":")
    if first not in ACTION_VERBS:
        return f"action should start with a concrete implementation verb, got {first!r}"
    if len(action.split()) < 4:
        return "action is too short to name a concrete object"
    return None


def _exit_criteria_specific(row: CandidateRow) -> bool:
    text = row.exit_criteria
    if any(path and path in text for path in row.deliverable):
        return True
    if any(cmd and cmd in text for cmd in row.required_verification_commands):
        return True
    lowered = text.lower()
    return any(word in lowered for word in ("passes", "exists", "renders", "returns", "contains"))


def _task_warning_covered(task_id: str, warnings: list[str]) -> bool:
    return any(task_id in warning for warning in warnings)


def validate_author_quality(
    *,
    bundle: CandidateRowsBundle,
    ir: GstackPlanIR,
    author_context: dict[str, Any],
) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    max_rows = int(author_context.get("global_rules", {}).get("max_rows", 25))
    if len(bundle.rows) > max_rows:
        errors.append(
            _finding(
                "AUTHOR_TOO_MANY_ROWS",
                "error",
                f"author emitted {len(bundle.rows)} rows, exceeding max_rows={max_rows}",
            )
        )

    for finding in author_context.get("context_findings", []):
        severity = finding.get("severity", "error")
        target = errors if severity == "error" else warnings
        target.append(
            _finding(
                str(finding.get("code", "AUTHOR_CONTEXT_FINDING")),
                severity,
                str(finding.get("message", "context finding")),
            )
        )

    known_paths = {normalize_repo_path(path) for path in author_context.get("known_paths", [])}
    known_write_roots = {
        normalize_repo_path(root) for root in author_context.get("known_write_roots", [])
    }
    constrained_roots = {
        normalize_repo_path(root)
        for root in author_context.get("global_rules", {}).get(
            "constrained_allowed_write_roots", []
        )
        if normalize_repo_path(root)
    }
    path_ledger = {
        normalize_repo_path(entry.get("path", "")): entry
        for entry in author_context.get("path_ledger", [])
        if entry.get("path")
    }
    safe_deliverable_paths = {
        path
        for path, entry in path_ledger.items()
        if entry.get("safe_as_deliverable", False)
    }

    seen_ids: set[str] = set()
    manual_gated_rows = 0
    task_to_rows: dict[str, list[str]] = {}

    for row in bundle.rows:
        placeholder = _has_placeholder_text(row)
        if placeholder:
            column, term = placeholder
            errors.append(
                _finding(
                    "AUTHOR_PLACEHOLDER_TEXT",
                    "error",
                    f"row contains placeholder/vague term {term!r}",
                    step_id=row.step_id,
                    column=column,
                )
            )

        action_error = _action_specificity_error(row)
        if action_error:
            errors.append(
                _finding(
                    "AUTHOR_ACTION_TOO_VAGUE",
                    "error",
                    action_error,
                    step_id=row.step_id,
                    column="action",
                )
            )

        if not _exit_criteria_specific(row):
            errors.append(
                _finding(
                    "AUTHOR_EXIT_CRITERIA_TOO_VAGUE",
                    "error",
                    "exit_criteria must reference a deliverable, command outcome, behavior, or artifact",
                    step_id=row.step_id,
                    column="exit_criteria",
                )
            )

        for column, path in _all_path_values(row):
            if path and path not in known_paths:
                errors.append(
                    _finding(
                        "AUTHOR_INVENTED_PATH",
                        "error",
                        f"{column} path {path!r} is not in the author path ledger",
                        step_id=row.step_id,
                        column=column,
                    )
                )
            elif column == "repo_surfaces":
                entry = path_ledger.get(path)
                if entry and not entry.get("safe_as_repo_surface", False):
                    errors.append(
                        _finding(
                            "AUTHOR_INVENTED_PATH",
                            "error",
                            f"repo_surfaces path {path!r} is not safe as a repo surface",
                            step_id=row.step_id,
                            column=column,
                        )
                    )
            elif column == "deliverable":
                entry = path_ledger.get(path)
                if entry and not entry.get("safe_as_deliverable", False):
                    errors.append(
                        _finding(
                            "AUTHOR_UNSAFE_DELIVERABLE_PATH",
                            "error",
                            f"deliverable path {path!r} is not marked safe_as_deliverable in the author path ledger",
                            step_id=row.step_id,
                            column=column,
                        )
                    )

        for root in row.allowed_write_roots:
            normalized = normalize_repo_path(root)
            if constrained_roots and not (
                normalized in constrained_roots
                or path_inside_any_root(normalized, sorted(constrained_roots))
            ):
                errors.append(
                    _finding(
                        "AUTHOR_WRITE_ROOT_OUTSIDE_APPROVED_CONSTRAINT",
                        "error",
                        (
                            f"allowed_write_roots entry {normalized!r} is outside "
                            f"approved write roots {sorted(constrained_roots)}"
                        ),
                        step_id=row.step_id,
                        column="allowed_write_roots",
                    )
                )
            if normalized not in known_write_roots and not root_derived_from_known_path(
                normalized, safe_deliverable_paths
            ):
                errors.append(
                    _finding(
                        "AUTHOR_INVENTED_PATH",
                        "error",
                        f"allowed_write_roots entry {normalized!r} is not derived from a known deliverable",
                        step_id=row.step_id,
                        column="allowed_write_roots",
                    )
                )

        if len(row.allowed_write_roots) > 3:
            errors.append(
                _finding(
                    "AUTHOR_ROW_TOO_BROAD",
                    "error",
                    "row uses more than 3 allowed_write_roots",
                    step_id=row.step_id,
                    column="allowed_write_roots",
                )
            )

        if row.requires_red_green and not row.required_verification_commands:
            errors.append(
                _finding(
                    "AUTHOR_BEHAVIORAL_WITHOUT_VERIFICATION",
                    "error",
                    "behavioral row has no required verification command",
                    step_id=row.step_id,
                    column="required_verification_commands",
                )
            )
        if any(is_behavioral_path(path) for path in row.deliverable) and not row.requires_red_green:
            errors.append(
                _finding(
                    "AUTHOR_BEHAVIORAL_WITHOUT_VERIFICATION",
                    "error",
                    "behavioral deliverable must set requires_red_green=true",
                    step_id=row.step_id,
                    column="requires_red_green",
                )
            )

        for prereq in _tokens_from_prereqs(row.prerequisites):
            if prereq not in seen_ids:
                errors.append(
                    _finding(
                        "AUTHOR_FORWARD_PREREQUISITE",
                        "error",
                        f"prerequisite {prereq!r} must appear before row {row.step_id}",
                        step_id=row.step_id,
                        column="prerequisites",
                    )
                )
        seen_ids.add(row.step_id)

        if row.manual_gate != "none":
            manual_gated_rows += 1

        for task_id in _source_task_ids_from_row(row):
            task_to_rows.setdefault(task_id, []).append(row.step_id)

        test_deliverables = [path for path in row.deliverable if is_test_path(path)]
        if row.requires_red_green and test_deliverables:
            command_text = " ".join(row.required_verification_commands)
            if not any(test_path in command_text for test_path in test_deliverables):
                warnings.append(
                    _finding(
                        "AUTHOR_TEST_COMMAND_NOT_TARGETED",
                        "warning",
                        "row declares a test deliverable but verification does not reference it",
                        step_id=row.step_id,
                        column="required_verification_commands",
                    )
                )

        for path in row.deliverable:
            kind = classify_path(path)
            if kind == "db":
                text = " ".join(row.required_verification_commands).lower()
                if not any(term in text for term in ("migration", "schema", "dry", "rollback")):
                    warnings.append(
                        _finding(
                            "AUTHOR_DB_WITHOUT_MIGRATION_VERIFICATION",
                            "warning",
                            "database deliverable should include migration/schema/rollback verification",
                            step_id=row.step_id,
                            column="required_verification_commands",
                        )
                    )
                if row.manual_gate == "none":
                    warnings.append(
                        _finding(
                            "AUTHOR_DB_WITHOUT_MANUAL_GATE",
                            "warning",
                            "database deliverable should usually require manual signoff",
                            step_id=row.step_id,
                            column="manual_gate",
                        )
                    )
            if kind == "infra" and row.manual_gate == "none":
                warnings.append(
                    _finding(
                        "AUTHOR_INFRA_WITHOUT_MANUAL_GATE",
                        "warning",
                        "infra deliverable should usually require manual signoff",
                        step_id=row.step_id, column="manual_gate",
                    )
                )
        risky_text = " ".join([row.phase, row.action, *row.deliverable, *row.notes]).lower()
        if row.manual_gate == "none" and any(term in risky_text for term in RISKY_TEXT_TERMS):
            warnings.append(
                _finding(
                    "AUTHOR_RISKY_ROW_WITHOUT_MANUAL_GATE",
                    "warning",
                    "risky auth/security/payment/deploy/production row should usually require manual signoff",
                    step_id=row.step_id,
                    column="manual_gate",
                )
            )

        if row.deliverable and row.allowed_write_roots:
            for deliverable in row.deliverable:
                if not path_inside_any_root(deliverable, row.allowed_write_roots):
                    errors.append(
                        _finding(
                            "AUTHOR_ROW_TOO_BROAD",
                            "error",
                            f"deliverable {deliverable!r} is outside allowed_write_roots",
                            step_id=row.step_id,
                            column="deliverable",
                        )
                    )

    if bundle.rows and manual_gated_rows == len(bundle.rows):
        errors.append(
            _finding(
                "AUTHOR_ALL_ROWS_MANUAL_GATED",
                "error",
                "all rows are manual gated; gates must not hide weak row quality",
            )
        )

    for card in author_context.get("task_cards", []):
        task_id = card.get("task_id", "")
        if not task_id:
            continue
        if task_id not in task_to_rows and not _task_warning_covered(task_id, bundle.compiler_warnings):
            errors.append(
                _finding(
                    "AUTHOR_UNCOVERED_TASK",
                    "error",
                    f"{task_id} is not mapped to any row and not explained in compiler_warnings",
                )
            )

    if ir.external_dependency_hints and all(
        row.external_check == "none" for row in bundle.rows
    ):
        warnings.append(
            _finding(
                "AUTHOR_EXTERNAL_HINTS_WITHOUT_CHECK",
                "warning",
                "source artifacts mention external dependencies, but no row requires external evidence",
            )
        )

    risky_gate = any(
        any(term in hint.lower() for term in RISKY_MANUAL_GATE_TERMS)
        for hint in ir.manual_gate_hints
    )
    if risky_gate and all(row.manual_gate == "none" for row in bundle.rows):
        warnings.append(
            _finding(
                "AUTHOR_MANUAL_HINTS_WITHOUT_GATE",
                "warning",
                "source artifacts mention a risky manual gate, but no row has manual_gate set",
            )
        )

    return {
        "status": "fail" if errors else "pass",
        "errors": errors,
        "warnings": warnings,
    }


def warnings_as_compiler_warnings(quality: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for warning in quality.get("warnings", []):
        code = warning.get("code", "AUTHOR_WARNING")
        message = warning.get("message", "")
        step = warning.get("step_id")
        prefix = f"{code}"
        if step:
            prefix += f"[{step}]"
        out.append(f"{prefix}: {message}")
    return out
