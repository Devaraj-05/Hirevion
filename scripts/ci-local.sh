#!/usr/bin/env bash
# The CI workflow (.github/workflows/ci.yml), run on this PC. It is the merge gate while GitHub
# Actions are off (the free minutes are used up until they reset): a PR merges when this script
# passes on its branch, with its summary pasted into the PR.
#
#   bash scripts/ci-local.sh            jobs for what the branch changed against origin/main
#   bash scripts/ci-local.sh --all      every job, as CI runs on main
#   bash scripts/ci-local.sh python js  only the jobs named
#
# Jobs: hooks, python, contract, js, e2e, compose, desktop, desktop-e2e, rust, secrets.
# `e2e` needs the local stack and the API running (`uv run hv up`, `uv run hv api`); the Python
# tests need the stack too. The summary is also written to .ci-local/summary.md.
set -uo pipefail

cd "$(git rev-parse --show-toplevel)"
mkdir -p .ci-local
SUMMARY=.ci-local/summary.md
UV=${UV:-uv}
command -v "$UV" >/dev/null 2>&1 || UV="/c/Users/$USER/AppData/Local/Microsoft/WinGet/Packages/astral-sh.uv_Microsoft.Winget.Source_8wekyb3d8bbwe/uv.exe"

ALL_JOBS=(hooks python contract js e2e compose desktop desktop-e2e rust secrets)

changed_files() {
  git fetch -q origin main 2>/dev/null || true
  {
    git diff --name-only origin/main...HEAD
    git diff --name-only HEAD
    git ls-files --others --exclude-standard
  } | sort -u
}

# The same areas as the workflow's paths filter.
touches() {
  local pattern=$1
  grep -Eq "$pattern" <<<"$CHANGED"
}

pick_jobs() {
  local ci='^\.github/workflows/'
  JOBS=(hooks js secrets)
  touches "$ci|^backend/|^tools/|^pyproject\.toml$|^uv\.lock$" && JOBS+=(python)
  touches "$ci|^backend/|^packages/api-client/|^tools/api-codegen/|^uv\.lock$" && JOBS+=(contract)
  touches "$ci|^backend/|^recruitment-platform/|^packages/|^tools/devcli/|^tools/interview-simulator/|^uv\.lock$|^pnpm-lock\.yaml$" && JOBS+=(e2e)
  touches "$ci|^infrastructure/|^backend/|^docs/policies/|^uv\.lock$" && JOBS+=(compose)
  touches "$ci|^ai-interviewer-desktop/|^packages/|^pnpm-lock\.yaml$" && JOBS+=(desktop desktop-e2e)
  touches "$ci|^ai-interviewer-desktop/src-tauri/" && JOBS+=(rust)
  return 0
}

job_hooks() { sh tools/hooks/test-hooks.sh; }

job_python() {
  "$UV" sync --locked &&
    "$UV" run ruff check . &&
    "$UV" run ruff format --check . &&
    "$UV" run hv trace --check &&
    "$UV" run mypy tools/devcli/src backend/core/src backend/api/src \
      backend/interview_agent/src tools/voice_bench/src tools/interview-simulator/src &&
    "$UV" run pytest -q -p no:cacheprovider 2>&1 | tail -15
}

job_contract() {
  "$UV" run hv openapi --check &&
    pnpm --filter @hirevion/api-codegen generate >/dev/null &&
    git diff --exit-code packages/api-client/src/schema.d.ts
}

job_js() {
  # CI starts from a clean checkout: Next.js route types from an older build would fail tsc.
  rm -rf recruitment-platform/.next/types
  pnpm install --frozen-lockfile >/dev/null && pnpm lint && pnpm typecheck && pnpm test
}

job_e2e() {
  if ! curl -sf http://127.0.0.1:8000/api/v1/health/ready >/dev/null; then
    echo "The API isn't running: start the stack and the API (uv run hv up; uv run hv api), then rerun."
    return 1
  fi
  pnpm --filter @hirevion/recruitment-platform e2e
}

job_compose() {
  docker compose --env-file .env -f infrastructure/local/compose.yaml \
    --profile core --profile edge --profile media --profile obs config --quiet &&
    docker build -q -f backend/api/Dockerfile -t hirevion-api:ci-local . >/dev/null &&
    docker rm -f hirevion-api-ci-local >/dev/null 2>&1
  docker run -d --name hirevion-api-ci-local -p 127.0.0.1:18000:8000 \
    -e OTEL_SDK_DISABLED=true -e POSTGRES_USER=ci -e POSTGRES_PASSWORD=ci \
    -e POSTGRES_APP_PASSWORD=ci -e POSTGRES_RELAY_PASSWORD=ci hirevion-api:ci-local >/dev/null || return 1
  local ok=1
  for _ in $(seq 1 30); do
    if curl -fsS http://127.0.0.1:18000/api/v1/health/live >/dev/null; then ok=0; break; fi
    sleep 1
  done
  [ "$ok" -eq 0 ] || docker logs hirevion-api-ci-local | tail -30
  docker rm -f hirevion-api-ci-local >/dev/null 2>&1
  return "$ok"
}

job_desktop() {
  local tauri=ai-interviewer-desktop/src-tauri
  pnpm --filter @hirevion/ai-interviewer-desktop build &&
    cargo fmt --all --check --manifest-path "$tauri/Cargo.toml" &&
    cargo clippy --manifest-path "$tauri/Cargo.toml" --workspace --all-targets --locked -- -D warnings &&
    cargo test -q --manifest-path "$tauri/Cargo.toml" --workspace --locked
}

job_desktop-e2e() {
  if ! grep -q '"e2e"' ai-interviewer-desktop/package.json; then
    echo "No desktop e2e script on this branch."
    return 0
  fi
  pnpm --filter @hirevion/ai-interviewer-desktop e2e
}

job_rust() {
  cargo deny --manifest-path ai-interviewer-desktop/src-tauri/Cargo.toml \
    check advisories bans licenses sources
}

job_secrets() {
  if command -v gitleaks >/dev/null 2>&1; then
    gitleaks git --no-banner --log-opts="origin/main..HEAD" .
  else
    # gitleaks isn't installed: look for the usual secret shapes in what the branch adds.
    # GitGuardian (a GitHub App, not an Action) still scans every push.
    local hits
    hits=$(git diff origin/main...HEAD -U0 | grep -E '^\+' | grep -E \
      'BEGIN [A-Z ]*PRIVATE KEY|AKIA[0-9A-Z]{16}|eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.|sk-[A-Za-z0-9]{20,}|AIza[0-9A-Za-z_-]{35}|ghp_[A-Za-z0-9]{36}' || true)
    [ -z "$hits" ] || { echo "$hits"; return 1; }
    echo "gitleaks isn't installed; pattern scan of the branch's additions found nothing."
  fi
}

CHANGED=$(changed_files)
if [ "$#" -eq 0 ]; then
  pick_jobs
elif [ "$1" = "--all" ]; then
  JOBS=("${ALL_JOBS[@]}")
else
  JOBS=("$@")
fi

failed=0
{
  echo "### Local CI ($(git rev-parse --short HEAD), $(date -u +%Y-%m-%dT%H:%MZ))"
  echo
  echo "| Job | Result | Time |"
  echo "|---|---|---|"
} >"$SUMMARY"

for job in "${ALL_JOBS[@]}"; do
  wanted=0
  for j in "${JOBS[@]}"; do [ "$j" = "$job" ] && wanted=1; done
  if [ "$wanted" -eq 0 ]; then
    echo "| $job | skipped (not touched) | |" >>"$SUMMARY"
    continue
  fi
  echo "=== $job"
  start=$(date +%s)
  if "job_$job" >".ci-local/$job.log" 2>&1; then
    result=pass
  else
    result=FAIL
    failed=1
    tail -40 ".ci-local/$job.log"
  fi
  echo "| $job | $result | $(($(date +%s) - start)) s |" >>"$SUMMARY"
  echo "    $result"
done

echo
cat "$SUMMARY"
exit "$failed"
