"""One-shot LLM repair for failed row author output."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from .ir_models import GstackPlanIR
from .llm_clients import JsonModelClient, parse_json_object_strict, render_prompt
from .row_models import CandidateRowsBundle
from .validators import validate_rows_payload


@dataclass
class RowRepairResult:
    bundle: CandidateRowsBundle
    trace: dict[str, Any]
    raw_model_output: str = ""


def repair_rows(
    *,
    ir: GstackPlanIR,
    author_context: dict[str, Any],
    failed_bundle: CandidateRowsBundle,
    validation_report: dict[str, Any],
    quality_findings: dict[str, Any],
    model_client: JsonModelClient,
    timeout_sec: int,
) -> RowRepairResult:
    prompt = render_prompt(
        "row_repair_v2.md",
        {
            "IR_JSON": json.dumps(ir.to_dict(), indent=2, sort_keys=True),
            "AUTHOR_CONTEXT_JSON": json.dumps(author_context, indent=2, sort_keys=True),
            "FAILED_ROWS_JSON": json.dumps(failed_bundle.to_dict(), indent=2, sort_keys=True),
            "VALIDATION_REPORT_JSON": json.dumps(validation_report, indent=2, sort_keys=True),
            "QUALITY_FINDINGS_JSON": json.dumps(quality_findings, indent=2, sort_keys=True),
        },
    )
    raw = model_client.complete_json(prompt=prompt, timeout_sec=timeout_sec)
    payload = parse_json_object_strict(raw)
    schema_errors = validate_rows_payload(payload)
    if schema_errors:
        details = "; ".join(err["message"] for err in schema_errors[:3])
        raise ValueError(f"po_candidate_rows_v1 schema validation failed: {details}")
    bundle = CandidateRowsBundle.from_dict(payload)
    return RowRepairResult(
        bundle=bundle,
        trace={
            "schema_version": "row_repair_trace_v1",
            "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        },
        raw_model_output=raw,
    )
