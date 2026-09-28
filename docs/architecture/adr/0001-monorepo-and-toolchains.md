# ADR-0001: One monorepo with uv, pnpm and Cargo workspaces

- **Status:** Accepted
- **Date:** 2026-09-28
- **Sub-project:** SP-00a

## Context

Hirevion has two separate applications (Recruitment Platform web, Candidate Windows Desktop AI Interview), the Third-Eye mobile page and a shared Python backend (PRD §5, §93). They share API contracts, event schemas and design tokens, and one developer builds them with Claude Code.

## Decision

- One repository using the PRD §93 top-level layout.
- Python: a uv workspace at the root, Python 3.12, `uv.lock` committed. Shared lint and test settings live in the root `pyproject.toml`.
- TypeScript: pnpm workspaces with Turborepo, added when the first TypeScript package lands (SP-03).
- Rust: a Cargo workspace inside `ai-interviewer-desktop/src-tauri` (SP-08).
- Developer tasks run through one Python CLI, `hv` (`uv run hv --help`).
- Git hooks in `.githooks/` enforce the commit identity, block AI attribution and block secrets; CI runs their self-test.
- Text files use LF line endings (`.gitattributes`, `.editorconfig`); Windows scripts keep CRLF.

## Consequences

- One CI pipeline and shared contracts; each application still has its own build and release.
- Fresh clones must run `git config core.hooksPath .githooks` once (README).
- uv manages the Python version, so nothing depends on the system Python.
