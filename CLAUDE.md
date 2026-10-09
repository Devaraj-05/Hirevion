# Hirevion — instructions for Claude Code

Hirevion is an enterprise AI recruitment and interview platform with two separate applications: the **Recruitment Platform** (web) and the **Candidate Windows Desktop AI Interview** (Tauri `.exe`), plus the **Third-Eye** mobile-browser camera and a shared Python backend.

- Requirements: `AI_Recruitment_Platform_Complete_PRD.md` (cited as §n).
- Architecture, sub-projects, schedule and PRD traceability: `MASTER_IMPLEMENTATION_PLAN.md`. It is the source of truth for sequencing, and its §13 "Global constraints" apply to every change.
- Detailed per-sub-project plans live in `docs/superpowers/plans/`.
- What's left, in order, with each part's definition of done and lane: `PENDING_TASKS.md`. Read it before starting new work, and update it when a part lands.
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
