# Security Policy

## Supported Versions

This compiler is pre-1.0. Security fixes target the default branch until
release branches exist.

## Reporting A Vulnerability

Do not open a public issue for a vulnerability. Use GitHub private
vulnerability reporting:

```text
https://github.com/AysajanE/gstack-playbook-compiler/security/advisories/new
```

If private vulnerability reporting is unavailable, contact the maintainer
through a private channel and include no sensitive details in any public issue.

Include:

- affected commit or release
- reproduction steps
- expected and actual behavior
- impact assessment
- any suggested mitigation

## Scope Notes

The compiler reads authored gstack design artifacts and emits a
`markdown_playbook_v1` for plan-orchestrator to execute. Security-relevant
behavior worth reporting includes:

- the compiler emitting a playbook that escapes its declared
  `allowed_write_roots`
- the compiler emitting paths it did not observe in the authored inputs
- validation that should fail closed but instead passes an unsafe row
- any path-traversal or injection reachable through compiler inputs

Vulnerabilities in plan-orchestrator, staged-workflow-runner, or other tools
should be reported to the owning repository unless the issue is caused by this
compiler's parsing, validation, or emission.
