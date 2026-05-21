"""Stage 3: deterministic validation.

Fails closed. Produces a compiler_validation_report_v1.

Rules enforced:
- Schema shape for po_candidate_rows_v1.
- Duplicate step_id check; sorted order; zero-padded format.
- Path safety: no absolute paths, no forbidden roots (.local, .git, .codex, .claude,
  .mcp.json, secrets, .env*, ops/config).
- Narrow-roots: allowed_write_roots must not be empty; not "."; not bare top-level "src".
- Reserved columns rejected via schema (po_candidate_rows_v1 forbids additionalProperties).
- Prereq integrity: prereq tokens must reference defined step_ids OR be "none" OR a range "NN-NN".
- requires_red_green=true → at least one required_verification_commands entry.
- requires_red_green=false on docs-only items → at least required_verification_artifacts or
  deliverable artifact existence.
- Deliverable should fall inside at least one allowed_write_root.
- manual_gate value must match the enum (also enforced by schema).
- external_check value must match the enum.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from . import VALIDATION_REPORT_SCHEMA_ID
from .row_models import (
    VALID_EXTERNAL_CHECKS,
    VALID_MANUAL_GATES,
    CandidateRow,
    CandidateRowsBundle,
)

SCHEMA_DIR = Path(__file__).resolve().parent / "schemas"
FORBIDDEN_ROOT_PREFIXES = (
    ".local", ".git", ".codex", ".claude", ".mcp.json",
    "secrets", ".env", "ops/config",
)
_PREREQ_RANGE = re.compile(r"^[0-9]{2}-[0-9]{2}$")
_PREREQ_LIST = re.compile(r"^[0-9]{2}(,\s*[0-9]{2})*$")
_STEP_ID = re.compile(r"^[0-9]{2}$")
_BEHAVIORAL_SUFFIXES = {
    ".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java", ".kt",
    ".kts", ".swift", ".dart", ".rb", ".php", ".cs", ".cpp", ".c", ".h", ".hpp",
    ".sql", ".sh", ".bash", ".zsh", ".yaml", ".yml", ".toml", ".ini", ".cfg",
    ".json", ".Dockerfile",
}


def _finding(code: str, severity: str, message: str, **extras: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"code": code, "severity": severity, "message": message}
    for k, v in extras.items():
        if v is not None and v != "":
            out[k] = v
    return out


def _load_schema(filename: str) -> dict[str, Any]:
    return json.loads((SCHEMA_DIR / filename).read_text(encoding="utf-8"))


def _schema_findings(payload: dict[str, Any], schema_filename: str, *, label: str) -> list[dict[str, Any]]:
    validator = Draft202012Validator(_load_schema(schema_filename))
    findings: list[dict[str, Any]] = []
    for err in sorted(validator.iter_errors(payload), key=lambda item: list(item.path)):
        loc = ".".join(str(part) for part in err.path) or "<root>"
        findings.append(_finding(
            "JSON_SCHEMA_VALIDATION",
            "error",
            f"{label} schema error at {loc}: {err.message}",
        ))
    return findings


def validate_ir_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Validate gstack_plan_ir_v1 JSON against the bundled schema."""
    return _schema_findings(payload, "gstack_plan_ir_v1.schema.json", label="gstack_plan_ir_v1")


def validate_rows_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Validate raw po_candidate_rows_v1 JSON before dataclass normalization."""
    return _schema_findings(payload, "po_candidate_rows_v1.schema.json", label="po_candidate_rows_v1")


def validate_report_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Validate compiler_validation_report_v1 JSON against the bundled schema."""
    return _schema_findings(
        payload,
        "compiler_validation_report_v1.schema.json",
        label="compiler_validation_report_v1",
    )


def _normalize_repo_token(value: str) -> str:
    p = value.strip().strip("`").strip()
    while p.startswith("./"):
        p = p[2:]
    return p.rstrip("/") if p not in {".", "/"} else p


def _is_absolute_path(p: str) -> bool:
    p = p.strip().strip("`")
    return p.startswith("/") or p.startswith("~") or re.match(r"^[A-Za-z]:[\\/]", p) is not None


def _is_forbidden_path(path: str) -> bool:
    if _is_absolute_path(path):
        return True
    r = _normalize_repo_token(path)
    if not r:
        return True
    for prefix in FORBIDDEN_ROOT_PREFIXES:
        if prefix == ".env":
            if r == ".env" or r.startswith(".env.") or r.startswith(".env/"):
                return True
            continue
        if r == prefix or r.startswith(prefix + "/"):
            return True
    if "/.env" in r or "/.git/" in r or "/.local/" in r:
        return True
    return False


def _is_suspicious_broad_root(root: str) -> bool:
    r = _normalize_repo_token(root)
    return r in {".", "src", "tests"}


def _path_inside_any_root(path: str, roots: list[str]) -> bool:
    p = _normalize_repo_token(path)
    for root in roots:
        r = _normalize_repo_token(root)
        if not r:
            continue
        if p == r or p.startswith(r + "/"):
            return True
    return False


def _has_pipe(value: Any) -> bool:
    if isinstance(value, str):
        return "|" in value
    if isinstance(value, list):
        return any(_has_pipe(item) for item in value)
    return False


def _is_docs_only_for_bare_docs(row: CandidateRow) -> bool:
    if row.requires_red_green:
        return False
    if row.external_check != "none":
        return False
    if not row.deliverable:
        return False
    if not all(_normalize_repo_token(path).startswith("docs/") for path in row.deliverable):
        return False
    risk_text = " ".join([row.phase, row.action, *row.notes]).lower()
    blocked_terms = ("security", "auth", "secret", "deploy", "migration", "infra", "production")
    return not any(term in risk_text for term in blocked_terms)


def _looks_behavioral_path(path: str) -> bool:
    p = _normalize_repo_token(path)
    name = Path(p).name
    if name in {"Dockerfile", "docker-compose.yml", "docker-compose.yaml"}:
        return True
    return any(p.endswith(suffix) for suffix in _BEHAVIORAL_SUFFIXES)


def _repo_path_exists(repo_root: Path, rel_path: str) -> bool:
    return (repo_root / _normalize_repo_token(rel_path)).exists()


def _validate_row(row: CandidateRow, defined_ids: set[str], *, repo_root: Path | None) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    step_id = row.step_id

    if not _STEP_ID.match(step_id):
        findings.append(_finding(
            "INVALID_STEP_ID_FORMAT", "error",
            "step_id must be a zero-padded two-digit identifier.",
            step_id=step_id, column="step_id",
        ))

    for col_name in (
        "phase", "action", "why_now", "owner_type", "prerequisites", "exit_criteria",
        "repo_surfaces", "deliverable", "allowed_write_roots", "manual_gate_reason",
        "manual_gate_evidence", "external_dependencies", "consult_paths",
        "required_verification_commands", "required_verification_artifacts", "notes",
    ):
        if _has_pipe(getattr(row, col_name)):
            findings.append(_finding(
                "PIPE_IN_CELL", "error",
                "Pipe characters are forbidden because plan-orchestrator's markdown parser splits on '|'.",
                step_id=step_id, column=col_name,
            ))

    # Path safety in repo_surfaces, deliverable, consult_paths, required_verification_artifacts
    for col_name in ("repo_surfaces", "deliverable", "consult_paths", "required_verification_artifacts"):
        for entry in getattr(row, col_name):
            if _is_absolute_path(entry):
                findings.append(_finding(
                    "ABSOLUTE_PATH", "error",
                    f"{col_name} entry {entry!r} is an absolute path; use repo-relative paths.",
                    step_id=step_id, column=col_name,
                ))
            if _is_forbidden_path(entry):
                findings.append(_finding(
                    "FORBIDDEN_PATH", "error",
                    f"{col_name} entry {entry!r} is forbidden (runtime/secrets/absolute).",
                    step_id=step_id, column=col_name,
                ))
            if repo_root is not None and col_name in {"repo_surfaces", "consult_paths"}:
                if not _repo_path_exists(repo_root, entry):
                    findings.append(_finding(
                        "REPO_PATH_MISSING", "warning",
                        f"{col_name} entry {entry!r} does not exist under repo_root.",
                        step_id=step_id, column=col_name,
                    ))

    # allowed_write_roots checks
    if not row.allowed_write_roots:
        findings.append(_finding(
            "MISSING_ALLOWED_WRITE_ROOTS", "error",
            "allowed_write_roots must not be empty.",
            step_id=step_id, column="allowed_write_roots",
        ))
    for root in row.allowed_write_roots:
        if _is_absolute_path(root):
            findings.append(_finding(
                "ABSOLUTE_PATH", "error",
                f"allowed_write_roots {root!r} is an absolute path; use repo-relative roots.",
                step_id=step_id, column="allowed_write_roots",
            ))
        if _is_forbidden_path(root):
            findings.append(_finding(
                "FORBIDDEN_WRITE_ROOT", "error",
                f"allowed_write_roots {root!r} is forbidden (runtime/secrets/absolute).",
                step_id=step_id, column="allowed_write_roots",
            ))
        if _is_suspicious_broad_root(root):
            findings.append(_finding(
                "SUSPICIOUS_BROAD_WRITE_ROOT", "error",
                f"allowed_write_roots {root!r} is too broad; use a narrower repo-relative root.",
                step_id=step_id, column="allowed_write_roots",
            ))
        if _normalize_repo_token(root) == "docs" and not _is_docs_only_for_bare_docs(row):
            findings.append(_finding(
                "BARE_DOCS_ROOT_FOR_NON_DOCS_ROW", "error",
                "Bare 'docs' is allowed only for docs-only rows; use a narrower docs/<subdir> root.",
                step_id=step_id, column="allowed_write_roots",
            ))

    # Required cells non-empty
    if not row.repo_surfaces:
        findings.append(_finding(
            "MISSING_REPO_SURFACES", "error",
            "repo_surfaces must not be empty.",
            step_id=step_id, column="repo_surfaces",
        ))
    if not row.deliverable:
        findings.append(_finding(
            "MISSING_DELIVERABLE", "error",
            "deliverable must not be empty.",
            step_id=step_id, column="deliverable",
        ))

    # requires_red_green discipline
    if row.requires_red_green:
        if not row.required_verification_commands:
            findings.append(_finding(
                "RED_GREEN_WITHOUT_COMMANDS", "error",
                "requires_red_green=true requires at least one required_verification_commands entry.",
                step_id=step_id, column="required_verification_commands",
            ))
    else:
        if any(_looks_behavioral_path(path) for path in row.deliverable):
            findings.append(_finding(
                "BEHAVIORAL_DELIVERABLE_WITHOUT_RED_GREEN", "warning",
                "Behavioral-looking deliverables should usually set requires_red_green=true.",
                step_id=step_id, column="requires_red_green",
            ))
        if not row.required_verification_artifacts and not row.deliverable:
            findings.append(_finding(
                "DOCS_ONLY_WITHOUT_ARTIFACT", "warning",
                "requires_red_green=false items should declare a verification artifact (or rely on deliverable existence).",
                step_id=step_id, column="required_verification_artifacts",
            ))

    # Manual gate / external check enums (defense in depth; schema also catches)
    if row.manual_gate not in VALID_MANUAL_GATES:
        findings.append(_finding(
            "INVALID_MANUAL_GATE", "error",
            f"manual_gate {row.manual_gate!r} is not in {sorted(VALID_MANUAL_GATES)}.",
            step_id=step_id, column="manual_gate",
        ))
    if row.external_check not in VALID_EXTERNAL_CHECKS:
        findings.append(_finding(
            "INVALID_EXTERNAL_CHECK", "error",
            f"external_check {row.external_check!r} is not in {sorted(VALID_EXTERNAL_CHECKS)}.",
            step_id=step_id, column="external_check",
        ))

    # Prereq integrity
    p = row.prerequisites.strip()
    if p and p.lower() != "none":
        if _PREREQ_RANGE.match(p):
            start, end = p.split("-")
            if start not in defined_ids or end not in defined_ids:
                findings.append(_finding(
                    "PREREQ_RANGE_UNDEFINED", "error",
                    f"prerequisites {p!r} references step_ids not in this plan.",
                    step_id=step_id, column="prerequisites",
                ))
        elif _PREREQ_LIST.match(p):
            ids = [x.strip() for x in p.split(",")]
            for i in ids:
                if i not in defined_ids:
                    findings.append(_finding(
                        "PREREQ_LIST_UNDEFINED", "error",
                        f"prerequisites references undefined step_id {i!r}.",
                        step_id=step_id, column="prerequisites",
                    ))
        else:
            findings.append(_finding(
                "PREREQ_FORMAT", "error",
                f"prerequisites {p!r} must be 'none', a comma-separated list of step_ids, or a NN-NN range.",
                step_id=step_id, column="prerequisites",
            ))

    # Deliverable should fall inside at least one allowed_write_root (loose check).
    for d in row.deliverable:
        if row.allowed_write_roots and not _path_inside_any_root(d, row.allowed_write_roots):
            findings.append(_finding(
                "DELIVERABLE_OUTSIDE_WRITE_ROOTS", "error",
                f"deliverable {d!r} is not inside any allowed_write_roots entry.",
                step_id=step_id, column="deliverable",
            ))

    return findings


def validate(bundle: CandidateRowsBundle, *, repo_root: Path | None = None) -> dict[str, Any]:
    """Return a compiler_validation_report_v1 dict."""
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    row_summaries: list[dict[str, Any]] = []

    errors.extend(_schema_findings(
        bundle.to_dict(),
        "po_candidate_rows_v1.schema.json",
        label="po_candidate_rows_v1",
    ))

    seen_ids: set[str] = set()
    duplicates: set[str] = set()
    for row in bundle.rows:
        if row.step_id in seen_ids:
            duplicates.add(row.step_id)
        seen_ids.add(row.step_id)
    for dup in sorted(duplicates):
        errors.append(_finding(
            "DUPLICATE_STEP_ID", "error",
            f"step_id {dup!r} appears more than once.",
            step_id=dup, column="step_id",
        ))

    defined_ids = seen_ids
    previous_id = ""
    for row in bundle.rows:
        if _STEP_ID.match(row.step_id):
            if previous_id and row.step_id <= previous_id:
                errors.append(_finding(
                    "STEP_ID_ORDER", "error",
                    "step_id values must be strictly increasing in row order.",
                    step_id=row.step_id, column="step_id",
                ))
            previous_id = row.step_id
        row_findings = _validate_row(row, defined_ids, repo_root=repo_root)
        for f in row_findings:
            if f["severity"] == "error":
                errors.append(f)
            else:
                warnings.append(f)
        row_summaries.append({
            "step_id": row.step_id,
            "phase": row.phase,
            "issues": sum(1 for f in row_findings if f["severity"] == "error"),
        })

    status = "fail" if errors else "pass"
    report = {
        "schema_version": VALIDATION_REPORT_SCHEMA_ID,
        "validated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status": status,
        "errors": errors,
        "warnings": warnings,
        "row_summaries": row_summaries,
        "repair_attempts": 0,
    }
    report_schema_errors = validate_report_payload(report)
    if report_schema_errors:
        report["status"] = "fail"
        report["errors"] = [*report["errors"], *report_schema_errors]
    return report
