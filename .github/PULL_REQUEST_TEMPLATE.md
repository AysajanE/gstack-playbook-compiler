## Summary

## Verification

- [ ] `python -m unittest discover -s automation/gstack_to_markdown_playbook_v1/tests -p 'test_*.py'` passes
- [ ] New behavior has tests and fixtures

## Contract Check

- [ ] Python still owns the final Markdown table (no LLM-authored Markdown)
- [ ] No reserved columns authored (`change_profile`, `execution_mode`, `host_commands`)
- [ ] `allowed_write_roots` stays narrow; no broad roots emitted
- [ ] Validation still fails closed; no validator was relaxed to pass a new author
- [ ] No repo paths are invented beyond what the parser observed
