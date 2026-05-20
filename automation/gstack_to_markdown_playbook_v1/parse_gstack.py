"""Stage 1: deterministic parser.

Reads gstack design + optional /autoplan + optional approved brief and produces a
gstack_plan_ir_v1.json. Never invents paths.

Strategy:
- Split markdown into H2 sections.
- For each known section heading (Problem Statement, Constraints, Premises, Recommended
  Approach, etc.) extract bullet lists or paragraphs as appropriate.
- Hash files for traceability.
- Regex-extract path-like tokens (only paths the parser literally observed).
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path

from .ir_models import GstackPlanIR, ImplementationTask, SourceArtifact, StackProfile


_H2 = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
_H3 = re.compile(r"^###\s+(.+?)\s*$", re.MULTILINE)
# Match `path/like/this.ext` or bare relative paths that contain a slash and a likely extension.
_PATH_INLINE = re.compile(r"`([^`]+?)`")
_PATH_BARE = re.compile(r"\b([a-zA-Z_][\w./\-]+/[\w./\-]+\.[a-zA-Z0-9]{1,8})\b")
_BULLET = re.compile(r"^[\-\*]\s+(.+?)\s*$", re.MULTILINE)
_TOP_LEVEL_TASK = re.compile(r"^\s*(?:[-*]\s+|\d+[.)]\s+)(?:\[[ xX]\]\s*)?(.+?)\s*$")
_FIELD_LINE = re.compile(
    r"^\s*(?:[-*]\s+)?(?:\*\*)?"
    r"(files?|verify|verification|tests?|notes?|priority|effort)"
    r"(?:\*\*)?\s*:\s*(.*?)\s*$",
    re.IGNORECASE,
)
_MANUAL_GATE_WORDS = (
    "approval", "approved", "signoff", "sign-off", "human gate", "manual gate",
    "human review", "reviewer", "presenter review", "security review", "operator confirmation",
)
_EXTERNAL_DEP_WORDS = (
    "open wearables", "oura", "8 sleep", "pyEight", "stripe", "supabase", "vercel",
    "fastapi", "duckdb", "parquet", "launchd", "iCloud", "tailscale",
)


def _hash_file(path: Path) -> SourceArtifact:
    data = path.read_bytes()
    return SourceArtifact(
        kind="office_hours",
        path=str(path),
        sha256=hashlib.sha256(data).hexdigest(),
        byte_size=len(data),
    )


def _split_h2(md: str) -> dict[str, str]:
    """Split markdown into a dict keyed by lowercased H2 heading.

    Duplicate H2 names are appended rather than overwritten. gstack design,
    autoplan, and approved-brief artifacts often reuse headings such as
    "Constraints"; silently losing the earlier section weakens grounding.
    """
    matches = list(_H2.finditer(md))
    sections: dict[str, str] = {}
    if not matches:
        return sections
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(md)
        title = m.group(1).strip().lower()
        body = md[start:end].strip()
        if title in sections and body:
            sections[title] = sections[title] + "\n\n" + body
        else:
            sections[title] = body
    return sections


def _find_section(sections: dict[str, str], *needles: str) -> str:
    for title, body in sections.items():
        for needle in needles:
            if needle in title:
                return body
    return ""


def _extract_bullets(body: str) -> list[str]:
    bullets = [m.group(1).strip() for m in _BULLET.finditer(body)]
    bullets = [b for b in bullets if b and not b.startswith("#")]
    seen: set[str] = set()
    out: list[str] = []
    for b in bullets:
        if b not in seen:
            seen.add(b)
            out.append(b)
    return out


def _extract_candidate_paths(md: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    # Backticked inline tokens first
    for m in _PATH_INLINE.finditer(md):
        token = m.group(1).strip()
        if "/" in token and not token.startswith(("http://", "https://")) and " " not in token:
            if token not in seen:
                seen.add(token)
                found.append(token)
    # Bare-path tokens with an extension
    for m in _PATH_BARE.finditer(md):
        token = m.group(1).strip()
        if token not in seen and not token.startswith(("http://", "https://")):
            seen.add(token)
            found.append(token)
    return found


def _clean_task_title(raw: str) -> str:
    title = raw.strip().strip("*").strip()
    title = re.sub(r"^(?:task|implementation task)\s*[:\-]\s*", "", title, flags=re.IGNORECASE)
    return title.strip()


def _extract_file_tokens(text: str) -> list[str]:
    """Extract repo-relative file tokens from a Files: field.

    This is intentionally a little broader than _extract_candidate_paths:
    Files: may list root-level files like README.md or pyproject.toml.
    """
    found: list[str] = []
    seen: set[str] = set()
    for m in _PATH_INLINE.finditer(text):
        token = m.group(1).strip()
        if token and " " not in token and not token.startswith(("http://", "https://", "/", "~")):
            if token not in seen:
                seen.add(token)
                found.append(token)
    for token in re.findall(r"\b([A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*\.[A-Za-z0-9._-]+)\b", text):
        if token.startswith(("http://", "https://", "/", "~")):
            continue
        if token not in seen:
            seen.add(token)
            found.append(token)
    return found


def _split_verify_values(text: str) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    backticked = [m.group(1).strip() for m in _PATH_INLINE.finditer(text)]
    candidates = backticked or [part.strip() for part in re.split(r"\s*;\s*", text) if part.strip()]
    for value in candidates:
        value = re.sub(r"^\s*[-*]\s+", "", value).strip()
        if value and value.lower() != "none" and value not in seen:
            seen.add(value)
            values.append(value)
    return values


def _parse_task_block(lines: list[str], phase: str) -> ImplementationTask | None:
    if not lines:
        return None
    title_match = _TOP_LEVEL_TASK.match(lines[0])
    if not title_match:
        return None
    task = _clean_task_title(title_match.group(1))
    files_text: list[str] = []
    verify_text: list[str] = []
    notes: list[str] = []
    active_field: str | None = None

    for raw in lines[1:]:
        stripped = raw.strip()
        if not stripped:
            continue
        field_match = _FIELD_LINE.match(raw)
        if field_match:
            field = field_match.group(1).lower()
            value = field_match.group(2).strip()
            if field.startswith("file"):
                active_field = "files"
                if value:
                    files_text.append(value)
            elif field in {"verify", "verification", "test", "tests"}:
                active_field = "verify"
                if value:
                    verify_text.append(value)
            else:
                active_field = "notes"
                if value:
                    notes.append(f"{field}: {value}")
            continue

        continuation = re.sub(r"^\s*[-*]\s+", "", raw).strip()
        if not continuation:
            continue
        if active_field == "files":
            files_text.append(continuation)
        elif active_field == "verify":
            verify_text.append(continuation)
        else:
            notes.append(continuation)

    files = _extract_file_tokens("\n".join(files_text))
    verify: list[str] = []
    for item in verify_text:
        for command in _split_verify_values(item):
            if command not in verify:
                verify.append(command)
    note_text = "; ".join(notes)
    return ImplementationTask(task=task, phase=phase, files=files, verify=verify, notes=note_text)


def _parse_implementation_task_blocks(body: str, phase: str) -> list[ImplementationTask]:
    tasks: list[ImplementationTask] = []
    current: list[str] = []

    def flush() -> None:
        nonlocal current
        parsed = _parse_task_block(current, phase)
        if parsed is not None:
            tasks.append(parsed)
        current = []

    for raw in body.splitlines():
        line = raw.rstrip()
        if not line.strip():
            if current:
                current.append(line)
            continue
        field_match = _FIELD_LINE.match(line)
        task_match = _TOP_LEVEL_TASK.match(line)
        is_new_task = bool(task_match and not field_match and len(line) - len(line.lstrip(" ")) <= 3)
        if is_new_task:
            if current:
                flush()
            current = [line]
        elif current:
            current.append(line)
    if current:
        flush()
    return tasks


def _extract_implementation_tasks(autoplan_md: str) -> list[ImplementationTask]:
    """Parse /autoplan-style 'Implementation Tasks' rows.

    /autoplan output structure is not standardized across versions; this is best-effort.
    We look for headings or bullet lists under sections whose title contains 'implementation',
    'tasks', or 'phase'.
    """
    sections = _split_h2(autoplan_md)
    relevant = {t: b for t, b in sections.items() if any(
        w in t for w in ("implementation", "tasks", "execution plan", "phase plan")
    )}
    out: list[ImplementationTask] = []
    if not relevant:
        return out
    for title, body in relevant.items():
        h3_matches = list(_H3.finditer(body))
        if h3_matches:
            for i, m in enumerate(h3_matches):
                phase_title = m.group(1).strip()
                start = m.end()
                end = h3_matches[i + 1].start() if i + 1 < len(h3_matches) else len(body)
                phase_body = body[start:end]
                parsed = _parse_implementation_task_blocks(phase_body, phase_title)
                if parsed:
                    out.extend(parsed)
                    continue
                bullets = _extract_bullets(phase_body)
                for b in bullets:
                    out.append(ImplementationTask(task=b, phase=phase_title))
        else:
            parsed = _parse_implementation_task_blocks(body, title.title())
            if parsed:
                out.extend(parsed)
                continue
            bullets = _extract_bullets(body)
            for b in bullets:
                out.append(ImplementationTask(task=b, phase=title.title()))
    return out


def _extract_hints(md: str, words: tuple[str, ...]) -> list[str]:
    md_lower = md.lower()
    hits: list[str] = []
    seen: set[str] = set()
    for word in words:
        if word.lower() in md_lower:
            if word not in seen:
                seen.add(word)
                hits.append(word)
    return hits


def parse(
    *,
    design_path: Path | None,
    autoplan_path: Path | None = None,
    approved_brief_path: Path | None = None,
    stack_profile: StackProfile | None = None,
) -> GstackPlanIR:
    source_artifacts: list[SourceArtifact] = []
    bodies: list[str] = []
    if design_path is not None:
        art = _hash_file(design_path)
        art.kind = "office_hours"
        source_artifacts.append(art)
        bodies.append(design_path.read_text(encoding="utf-8"))
    autoplan_md = ""
    if autoplan_path is not None:
        art = _hash_file(autoplan_path)
        art.kind = "autoplan"
        source_artifacts.append(art)
        autoplan_md = autoplan_path.read_text(encoding="utf-8")
        bodies.append(autoplan_md)
    if approved_brief_path is not None:
        art = _hash_file(approved_brief_path)
        art.kind = "approved_brief"
        source_artifacts.append(art)
        bodies.append(approved_brief_path.read_text(encoding="utf-8"))

    combined = "\n\n".join(bodies)
    sections = _split_h2(combined)

    problem = _find_section(sections, "problem statement", "what makes this cool")
    constraints_body = _find_section(sections, "constraints")
    premises_body = _find_section(sections, "premises")
    approach_body = _find_section(sections, "recommended path", "recommended approach", "approaches considered")
    risks_body = _find_section(sections, "risk", "tripwires", "contingenc")
    non_goals_body = _find_section(sections, "non-goals", "out of scope", "what this is not")

    product_goal_lines = [ln.strip() for ln in problem.splitlines() if ln.strip()]
    product_goal = product_goal_lines[0] if product_goal_lines else ""

    non_goals = _extract_bullets(non_goals_body)
    constraints = _extract_bullets(constraints_body) or _extract_bullets(premises_body)
    risk_hints = _extract_bullets(risks_body)

    implementation_tasks = _extract_implementation_tasks(autoplan_md) if autoplan_md else []

    candidate_repo_paths = _extract_candidate_paths(combined)

    manual_gate_hints = _extract_hints(combined, _MANUAL_GATE_WORDS)
    external_dependency_hints = _extract_hints(combined, _EXTERNAL_DEP_WORDS)
    verification_hints: list[str] = []
    for ln in combined.splitlines():
        s = ln.strip()
        if s.startswith(("pytest", "python -m", "npm ", "npx ", "pnpm ", "yarn ", "git ")):
            verification_hints.append(s)

    return GstackPlanIR(
        compiled_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        source_artifacts=source_artifacts,
        product_goal=product_goal,
        non_goals=non_goals,
        constraints=constraints,
        recommended_approach=approach_body.strip(),
        implementation_tasks=implementation_tasks,
        candidate_repo_paths=candidate_repo_paths,
        verification_hints=verification_hints,
        manual_gate_hints=manual_gate_hints,
        external_dependency_hints=external_dependency_hints,
        risk_hints=risk_hints,
        stack_profile=stack_profile,
    )
