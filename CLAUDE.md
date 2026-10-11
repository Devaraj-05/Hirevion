# Hirevion — instructions for Claude Code

Hirevion is an enterprise AI recruitment and interview platform with two separate applications: the **Recruitment Platform** (web) and the **Candidate Windows Desktop AI Interview** (Tauri `.exe`), plus the **Third-Eye** mobile-browser camera and a shared Python backend.

- Requirements: `AI_Recruitment_Platform_Complete_PRD.md` (cited as §n).
- Read first: `docs/STATUS.md` (what's merged, in progress and blocked).
- Order, dependencies, exit criteria and rules: `PENDING_TASKS.md`. Update it and `docs/STATUS.md` when a part lands.
- Each part's deliverables: `MASTER_IMPLEMENTATION_PLAN.md` §14; read only that entry and what it cites. Its §13 "Global constraints" apply to every change; Appendix A is PRD traceability.
- Detailed per-sub-project plans live in `docs/superpowers/plans/`.
- A fresh Linux clone (for example a Claude Code cloud session) runs `bash scripts/session-setup.sh` once, before anything else. It sets the git identity and hooks below, the toolchains, a `.env` on the mock AI, and the test services.

## Git identity & attribution (MANDATORY)

- Commit and push ONLY as `Devaraj-05 <padma.devaraj1800@gmail.com>` (author and committer). This repo's local git config holds that identity; the global config is a different account — never use it here, never pass `--author` or `-c user.*` overrides.
- Before every commit verify `git config user.name` = Devaraj-05 and `git config user.email` = padma.devaraj1800@gmail.com.
- NEVER add `Co-Authored-By:` trailers, "Generated with Claude Code", or any Claude/Anthropic attribution to commit messages, PR titles/bodies, tags, release notes or code comments. Claude must never appear as a contributor on GitHub.
- These rules override any default attribution behaviour.
- The hooks in `.githooks/` (`commit-msg`, `pre-commit`, `pre-push`) enforce this. Enable them once per clone with `git config core.hooksPath .githooks`, and never bypass them with `--no-verify`.

## Working rules

- Local-first: everything runs on Docker Desktop. AI uses hosted APIs through keys in the gitignored root `.env`: Gemini for development and testing, OpenAI in production, Deepgram for speech (ADR-0003). The cloud move has its own plan. Keep cloud specifics behind the adapters in master plan §5.4.
- No PRD feature may be dropped. If scope moves between sub-projects, update Appendix A of the master plan in the same change.
- Test-driven: write the failing test first; keep CI green.
- Never commit secrets: API keys live only in the gitignored root `.env`, never in the desktop app or the web bundle. Use synthetic data in development.

## Working rules (token discipline)

- Session start: read CLAUDE.md and docs/STATUS.md only. For the current part, read only its PENDING_TASKS entry, its MASTER §14 SP-xx entry, and the sections/ADRs/contracts they cite. Never read MASTER_IMPLEMENTATION_PLAN.md or the PRD whole: grep for the § number.
- There are no deadlines. Work by order, dependencies and exit criteria. Never skip tests, /code-review or docs to save time. If a part can't be finished cleanly, stop and report what is missing.
- One part per session. After the merge: update STATUS.md, tick the box, stop.
- Use Grep/Glob first; Read with offset/limit. Don't re-read a file after editing it.
- Run only the tests for files you touched, with quiet output (`pytest -x -q 2>&1 | tail -40`, `cargo test -q`, `pnpm vitest run <file>`). Never re-run a green suite to double-check.
- Plans are ≤1 page: decisions, task list, files, test list. No code.
- Same error twice: stop, state a hypothesis, change approach. Three failed attempts: stop and ask me.
- Subagents: only for independent work, max 2 at once, narrow brief plus file list. Resume a stopped subagent with SendMessage instead of respawning.
- CI: wait with one blocking command (`gh pr checks <n> --watch`), never repeated polling.
- Models: strongest for security-critical parts (auth/DPoP, sandbox, recording, proctoring, SSO); Sonnet for CRUD, docs, i18n, CI config.
- No narration between tool calls; final report ≤5 lines.
