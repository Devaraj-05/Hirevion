#!/usr/bin/env bash
# Prepares a fresh Linux clone (a Claude Code cloud session, or any box without the local stack)
# to build, test and commit Hirevion. Safe to run again. It sets up:
#   1. the git identity and hooks every commit must use (CLAUDE.md);
#   2. the toolchains: Python 3.12 via uv, Node 24 with pnpm;
#   3. a .env with fresh throwaway secrets and the mock AI (no real keys in cloud sessions);
#   4. the services the tests need: PostgreSQL with pgvector, Valkey or Redis, and Mailpit.
#      It uses the local Docker stack when Docker works, and apt packages otherwise.
# Then it migrates the dev database, seeds the demo users and runs a quick smoke test.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
SUDO=""
if [ "$(id -u)" -ne 0 ] && command -v sudo >/dev/null; then SUDO="sudo"; fi
log() { printf '\n== %s\n' "$*"; }

log "Git identity and hooks"
git config user.name "Devaraj-05"
git config user.email "padma.devaraj1800@gmail.com"
git config core.hooksPath .githooks

log "Toolchains"
export PATH="$HOME/.local/bin:$PATH"
if ! command -v uv >/dev/null; then
  curl -LsSf https://astral.sh/uv/install.sh | sh || python3 -m pip install --user uv
fi
node_major() { node -p 'process.versions.node.split(".")[0]' 2>/dev/null || echo 0; }
if [ "$(node_major)" != "24" ]; then
  # The workspace pins Node 24 (package.json engines).
  $SUDO npm install -g n >/dev/null 2>&1 && $SUDO n 24 >/dev/null
  hash -r
fi
corepack enable >/dev/null 2>&1 || $SUDO corepack enable
uv sync --locked
pnpm install --frozen-lockfile

log "Settings (.env)"
[ -f .env ] || uv run hv init-env
set_env() {
  if grep -q "^$1=" .env; then sed -i "s|^$1=.*|$1=$2|" .env; else printf '%s=%s\n' "$1" "$2" >> .env; fi
}
set_env HV_AI_PROFILE mock
set_env HV_AI_MOCK_SCRIPTS recruitment-platform/e2e/auth/ai-scripts.json
set_env HV_DOCUMENTS_SCAN false
set_env HV_HIBP_ENABLED false
set_env OTEL_SDK_DISABLED true
env_value() { grep "^$1=" .env | head -1 | cut -d= -f2- | sed 's/^"//; s/"$//'; }
PG_USER=$(env_value POSTGRES_USER)
PG_PASSWORD=$(env_value POSTGRES_PASSWORD)
PG_DB=$(env_value POSTGRES_DB)
VALKEY_PASSWORD=$(env_value VALKEY_PASSWORD)

docker_works() { command -v docker >/dev/null && docker info >/dev/null 2>&1; }

if docker_works; then
  log "Services (Docker)"
  docker compose -f infrastructure/local/compose.yaml --env-file .env --profile core \
    up -d postgres valkey mailpit azurite
else
  log "Services (apt: PostgreSQL with pgvector, Redis, Mailpit)"
  export DEBIAN_FRONTEND=noninteractive
  if ! command -v pg_ctlcluster >/dev/null; then
    $SUDO apt-get update -qq
    $SUDO apt-get install -y -qq postgresql postgresql-contrib >/dev/null
  fi
  PG_VERSION=$(ls /usr/lib/postgresql | sort -n | tail -1)
  if [ ! -f "/usr/share/postgresql/$PG_VERSION/extension/vector.control" ]; then
    $SUDO apt-get install -y -qq "postgresql-$PG_VERSION-pgvector" >/dev/null
  fi
  $SUDO pg_ctlcluster "$PG_VERSION" main start 2>/dev/null || true
  for _ in $(seq 1 30); do pg_isready -q -h 127.0.0.1 && break; sleep 1; done
  as_postgres() { if [ "$(id -u)" -eq 0 ]; then runuser -u postgres -- "$@"; else sudo -u postgres "$@"; fi; }
  run_psql() { as_postgres psql -v ON_ERROR_STOP=1 -qtA "$@"; }
  if [ "$(run_psql -c "SELECT 1 FROM pg_roles WHERE rolname = '$PG_USER'")" != "1" ]; then
    run_psql -c "CREATE ROLE \"$PG_USER\" LOGIN SUPERUSER PASSWORD '$PG_PASSWORD'"
  else
    run_psql -c "ALTER ROLE \"$PG_USER\" WITH LOGIN SUPERUSER PASSWORD '$PG_PASSWORD'"
  fi
  for db in "$PG_DB" hirevion_test; do
    if [ "$(run_psql -c "SELECT 1 FROM pg_database WHERE datname = '$db'")" != "1" ]; then
      run_psql -c "CREATE DATABASE \"$db\" OWNER \"$PG_USER\""
    fi
    run_psql -d "$db" -c "CREATE EXTENSION IF NOT EXISTS vector; CREATE EXTENSION IF NOT EXISTS pg_trgm; CREATE EXTENSION IF NOT EXISTS citext;"
  done

  if ! command -v valkey-server >/dev/null && ! command -v redis-server >/dev/null; then
    $SUDO apt-get install -y -qq redis-server >/dev/null
  fi
  KV=$(command -v valkey-server || command -v redis-server)
  KV_CLI=$(command -v valkey-cli || command -v redis-cli)
  if ! "$KV_CLI" -a "$VALKEY_PASSWORD" --no-auth-warning ping >/dev/null 2>&1; then
    "$KV" --bind 127.0.0.1 --port 6379 --requirepass "$VALKEY_PASSWORD" --daemonize yes \
      --save "" --appendonly no >/dev/null
  fi

  if ! command -v mailpit >/dev/null; then
    mkdir -p "$HOME/.local/bin"
    curl -fsSL https://github.com/axllent/mailpit/releases/latest/download/mailpit-linux-amd64.tar.gz \
      | tar -xz -C "$HOME/.local/bin" mailpit
  fi
  if ! curl -sf http://127.0.0.1:8025/readyz >/dev/null; then
    nohup mailpit --smtp 127.0.0.1:1025 --listen 127.0.0.1:8025 >/tmp/mailpit.log 2>&1 &
  fi
fi

log "Database"
uv run hv migrate
uv run hv seed-identity >/dev/null

log "Smoke test"
uv run pytest -p no:cacheprovider -q backend/api/tests/test_health.py
cat <<'EOF'

Ready. Remember:
  - commits go out as Devaraj-05 (checked by .githooks; never pass --no-verify);
  - the AI is the mock here: tests and end-to-end runs need no keys;
  - full checks: uv run ruff check . && uv run mypy <see ci.yml> && uv run pytest;
    web: pnpm --filter @hirevion/recruitment-platform test / typecheck; pnpm exec biome check .
EOF
