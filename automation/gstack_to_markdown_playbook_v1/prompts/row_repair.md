# row_repair prompt

Your previous output failed deterministic validation. You get ONE repair attempt.

You are given:

- the original prompt and inputs
- the candidate rows you produced
- the validation report errors and warnings

You must produce a new `po_candidate_rows_v1` JSON object that fixes EVERY error listed in
the validation report. You may not change rows that had no errors except to fix prereq
integrity if their step IDs changed.

If you cannot fix an error (e.g., a required path simply does not exist), insert a row note
that explicitly states the limitation, set `manual_gate = "signoff"`, and add the warning to
`compiler_warnings`.

Return JSON conforming to `po_candidate_rows_v1`. No prose. No backticks around the JSON.
