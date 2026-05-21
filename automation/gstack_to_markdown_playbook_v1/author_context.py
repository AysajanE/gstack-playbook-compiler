"""Build deterministic row-author context from gstack_plan_ir_v1."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .ir_models import GstackPlanIR
from .path_policy import (
    clamp_write_roots,
    classify_path,
    is_forbidden_path,
    normalize_repo_path,
)
from .verification_policy import (
    infer_verification_commands,
    task_requires_red_green,
    task_text_looks_behavioral,
)


_ALLOWED_ROOT_RE = re.compile(
    r"only allowed write roots?\s+(?:is|are)\s+(.+)$",
    re.IGNORECASE,
)


def _rel_if_under(path: Path, root: Path) -> str | None:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return None


def _source_artifact_paths(ir: GstackPlanIR, repo_root: Path) -> list[str]:
    out: list[str] = []
    for artifact in ir.source_artifacts:
        raw = artifact.path
        rel: str | None = None
        p = Path(raw)
        if p.is_absolute():
            rel = _rel_if_under(p, repo_root)
        else:
            rel = normalize_repo_path(raw)
        if rel and rel not in out and not is_forbidden_path(rel):
            out.append(rel)
    return out


def _existing_parent_surfaces(path: str, repo_root: Path) -> list[str]:
    p = normalize_repo_path(path)
    out: list[str] = []
    if "/" not in p:
        return out

    parent = p.rsplit("/", 1)[0]
    while parent and parent != ".":
        if (repo_root / parent).is_dir():
            out.append(parent)
            break
        if "/" not in parent:
            break
        parent = parent.rsplit("/", 1)[0]
    return out


def _add_ledger_entry(
    ledger: dict[str, dict[str, Any]],
    *,
    path: str,
    repo_root: Path,
    mentioned_by: str,
    safe_as_deliverable: bool = False,
    source_doc: bool = False,
) -> None:
    p = normalize_repo_path(path)
    if not p or is_forbidden_path(p):
        return
    entry = ledger.setdefault(
        p,
        {
            "path": p,
            "status": "exists" if (repo_root / p).exists() else "missing",
            "kind": "source_doc" if source_doc else classify_path(p),
            "mentioned_by": [],
            "safe_as_deliverable": False,
            "safe_as_repo_surface": False,
        },
    )
    if mentioned_by not in entry["mentioned_by"]:
        entry["mentioned_by"].append(mentioned_by)
    exists = (repo_root / p).exists()
    if source_doc:
        entry["kind"] = "source_doc"
    if safe_as_deliverable:
        entry["safe_as_deliverable"] = True
        if not exists:
            entry["status"] = "declared_missing"
    if exists:
        entry["safe_as_repo_surface"] = True


def _constraint_conflicts(ir: GstackPlanIR) -> list[dict[str, Any]]:
    constraints = " ".join(ir.constraints).lower()
    if not constraints:
        return []
    blocks_code = any(
        phrase in constraints
        for phrase in (
            "do not modify application code",
            "no application code",
            "docs only",
            "documentation only",
        )
    )
    if not blocks_code:
        return []
    findings: list[dict[str, Any]] = []
    for idx, task in enumerate(ir.implementation_tasks, start=1):
        if task_requires_red_green(task.files):
            findings.append(
                {
                    "code": "CONSTRAINT_TASK_CONFLICT",
                    "severity": "error",
                    "task_id": f"task_{idx:03d}",
                    "message": "Constraints prohibit application-code changes, but the task declares behavioral files.",
                }
            )
    return findings


def extract_constrained_write_roots(constraints: list[str]) -> list[str]:
    roots: list[str] = []
    for constraint in constraints:
        match = _ALLOWED_ROOT_RE.search(constraint)
        if not match:
            continue
        text = match.group(1)
        candidates = re.findall(r"`([^`]+)`", text) or re.split(r"[,;]\s*", text)
        for raw in candidates:
            root = normalize_repo_path(raw.strip().rstrip("."))
            if root and root not in roots:
                roots.append(root)
    return roots


def build_author_context(
    *,
    ir: GstackPlanIR,
    repo_root: Path,
    max_repo_files: int = 5000,
    max_rows: int = 25,
) -> dict[str, Any]:
    """Build row_author_context_v1 for the LLM row author."""
    repo_root = repo_root.resolve()
    source_paths = _source_artifact_paths(ir, repo_root)
    ledger: dict[str, dict[str, Any]] = {}

    for source in source_paths:
        _add_ledger_entry(
            ledger,
            path=source,
            repo_root=repo_root,
            mentioned_by="source_artifact",
            source_doc=True,
        )

    for path in ir.candidate_repo_paths:
        _add_ledger_entry(
            ledger,
            path=path,
            repo_root=repo_root,
            mentioned_by="candidate_repo_paths",
        )

    task_cards: list[dict[str, Any]] = []
    for idx, task in enumerate(ir.implementation_tasks, start=1):
        task_id = f"task_{idx:03d}"
        files = [normalize_repo_path(path) for path in task.files if normalize_repo_path(path)]
        for path in files:
            _add_ledger_entry(
                ledger,
                path=path,
                repo_root=repo_root,
                mentioned_by=task_id,
                safe_as_deliverable=True,
            )
            for parent in _existing_parent_surfaces(path, repo_root):
                _add_ledger_entry(
                    ledger,
                    path=parent,
                    repo_root=repo_root,
                    mentioned_by=task_id,
                    safe_as_deliverable=False,
                )
                ledger[parent]["safe_as_repo_surface"] = True

        existing_repo_surfaces = list(source_paths)
        for path in files:
            for parent in _existing_parent_surfaces(path, repo_root):
                if parent not in existing_repo_surfaces:
                    existing_repo_surfaces.append(parent)
            entry = ledger.get(path)
            if entry and entry["safe_as_repo_surface"] and path not in existing_repo_surfaces:
                existing_repo_surfaces.append(path)

        suggested_roots = []
        for path in files:
            root = path.rsplit("/", 1)[0] if "/" in path else path
            if root not in suggested_roots:
                suggested_roots.append(root)

        behavioral = task_requires_red_green(files)
        missing_declared_files = not files
        missing_paths_behavioral = not files and task_text_looks_behavioral(task.task, task.phase)
        verification_candidates = infer_verification_commands(
            task_files=files,
            task_verify=task.verify,
            stack_profile=ir.stack_profile,
            repo_root=repo_root,
        )
        risk_flags: list[str] = []
        if ir.manual_gate_hints:
            risk_flags.append("manual_gate_hints_present")
        if ir.external_dependency_hints:
            risk_flags.append("external_dependency_hints_present")
        if missing_declared_files:
            risk_flags.append("missing_declared_files")

        task_cards.append(
            {
                "task_id": task_id,
                "source_order": idx,
                "phase": task.phase,
                "task": task.task,
                "notes": task.notes,
                "declared_files": files,
                "existing_repo_surfaces": existing_repo_surfaces,
                "declared_deliverables": files,
                "suggested_allowed_write_roots": suggested_roots,
                "clamped_allowed_write_roots": clamp_write_roots(files),
                "behavioral": behavioral,
                "missing_declared_files": missing_declared_files,
                "missing_paths_behavioral": missing_paths_behavioral,
                "verification_candidates": verification_candidates,
                "risk_flags": risk_flags,
            }
        )

    path_ledger = sorted(ledger.values(), key=lambda item: item["path"])
    known_paths = [entry["path"] for entry in path_ledger]
    known_write_roots: list[str] = []
    for card in task_cards:
        for root in card["clamped_allowed_write_roots"]:
            if root not in known_write_roots:
                known_write_roots.append(root)

    return {
        "schema_version": "row_author_context_v1",
        "repo_root": ".",
        "source_artifact_paths": source_paths,
        "global_rules": {
            "max_rows": max_rows,
            "max_write_roots_per_row": 3,
            "forbidden_write_roots": [
                ".",
                "src",
                "tests",
                ".local",
                ".git",
                ".codex",
                ".claude",
                ".mcp.json",
                "ops/config",
                "secrets",
                ".env",
                ".env.*",
            ],
            "pipe_characters_forbidden": True,
            "markdown_is_python_emitted": True,
            "max_repo_files": max_repo_files,
            "constrained_allowed_write_roots": extract_constrained_write_roots(ir.constraints),
        },
        "stack_profile": ir.stack_profile.__dict__ if ir.stack_profile else None,
        "path_ledger": path_ledger,
        "known_paths": known_paths,
        "known_write_roots": known_write_roots,
        "task_cards": task_cards,
        "context_findings": _constraint_conflicts(ir),
        "manual_gate_hints": list(ir.manual_gate_hints),
        "external_dependency_hints": list(ir.external_dependency_hints),
        "risk_hints": list(ir.risk_hints),
    }
