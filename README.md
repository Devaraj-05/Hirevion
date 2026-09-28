# Hirevion

Enterprise AI recruitment and interview platform:

- **Recruitment Platform** (web): jobs, resume screening and ranking, candidates, interview configuration, live monitoring, reports, analytics and administration.
- **Candidate Windows Desktop AI Interview** (`AI-Interview.exe`): AI voice interview, coding, recording and proctoring.
- **Third-Eye**: a phone browser page that adds a second camera angle.
- **Backend**: the shared Python services behind all three.

Key documents:

- Requirements: [AI_Recruitment_Platform_Complete_PRD.md](AI_Recruitment_Platform_Complete_PRD.md)
- Architecture, sub-projects and schedule: [MASTER_IMPLEMENTATION_PLAN.md](MASTER_IMPLEMENTATION_PLAN.md)
- Decisions: [docs/architecture/adr](docs/architecture/adr/README.md)
- Rules for contributors (human or AI): [CLAUDE.md](CLAUDE.md)

## Prerequisites (Windows 11)

| Tool | Version | Needed for |
|---|---|---|
| Git for Windows | 2.40+ | everything |
| Docker Desktop (WSL2) | recent | the local stack |
| uv | 0.5+ | the Python toolchain (uv installs Python 3.12 itself) |
| Node.js | 24 LTS | the web, desktop and third-eye apps |
| pnpm | 9+ | TypeScript workspaces |
| Rust via rustup, with Visual Studio 2022 Build Tools (C++ workload) | Rust 1.85+ | the desktop app |

## First-time setup

1. `git config core.hooksPath .githooks` turns on the repository's git guards.
2. `uv sync` creates the Python environment.
3. `uv run hv init-env` creates `.env` with fresh local secrets.
4. Add `OPENAI_API_KEY` and `DEEPGRAM_API_KEY` to `.env`. It is gitignored; never commit it.
5. `uv run hv doctor` checks your tools, Docker and API keys.

## Everyday commands

| Command | What it does |
|---|---|
| `uv run hv --help` | Lists developer commands |
| `uv run pytest` | Runs the Python tests |
| `uv run ruff check .` | Lints the Python code |
| `sh tools/hooks/test-hooks.sh` | Tests the git hooks |
