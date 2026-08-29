# Ticket 001: Add the missing .env.example environment contract

- **ID**: ticket-001
- **Owner**: unresolved:agent
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-08-29

## Problem

`doctor-agent` observed that this repository declares environment configuration
but ships no `.env.example`. A contributor and an automated environment probe
therefore have no committed contract describing which variables the package
expects. The finding is recorded as `subactor/doctor-agent` issue #62 with
failure type `missing-file` and reproduce step `.env.example`.

## Goal and scope

Add a committed `.env.example` that names the environment variables this
package reads, without values. Nothing else changes.

## Acceptance criteria

- [ ] AC-01: `.env.example` exists at the repository root.
- [ ] AC-02: It names only variables this repository actually reads, and carries
  no secret value.
- [ ] AC-03: The existing test suite still passes.

## Delivery

This ticket is executed by the local OneDev control plane because hosted GitHub
Actions capacity is unavailable. The declared route is
`poa://subactor.dev/process/repository-pr-validator/v1`, so the scheduler
prepares an exact ticket branch and pull request and stops; approval and merge
remain with the protected Validator boundary.
