# Ticket 002: Declare the test dependency so a clean environment can run the suite

- **ID**: ticket-002
- **Owner**: unresolved:agent
- **Status**: DONE
- **Workflow state**: DONE
- **Created**: 2026-08-29

## Problem

This repository ships a `tests/` directory but declares no test dependency, so
an environment built only from `pyproject.toml` cannot run the suite. The local
OneDev execution profile gate reproduced it exactly:

```
PROFILE_RUNTIME_GATE_FAILED
step=2 command=python: .profile-venv/bin/python: No module named pytest
```

Because that gate must pass before the repository may be granted change
authority, the undeclared dependency also blocks every automated repair here.

## Goal and scope

Declare a `test` extra containing pytest. The profile detector prefers a `test`
extra over a `dev` extra and then installs `-e .[test]`, which puts pytest in
the environment that runs the suite.

## Acceptance criteria

- [x] AC-01: `pyproject.toml` declares `project.optional-dependencies.test`
  containing pytest.
- [x] AC-02: No runtime dependency of the package itself changes.

## Verification

`onedev-cli-agent profiles validate if-uri/urirun-fleet` must stop reporting
`PROFILE_RUNTIME_GATE_FAILED` for the missing pytest module.
