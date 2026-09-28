# SP-00b Local Docker Stack Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One command (`uv run hv up`) brings up the local infrastructure every later sub-project needs, and `uv run hv smoke` proves each service works: Postgres with pgvector, Valkey, Azurite blob storage, ClamAV, Mailpit, LiveKit, and Caddy serving `https://*.hirevion.localhost` with a locally trusted certificate; Grafana and GlitchTip on request.

**Architecture:** `infrastructure/local/compose.yaml` (project `hirevion`) with profiles `core` (postgres, valkey, azurite, clamav, mailpit), `edge` (caddy), `media` (livekit) and `obs` (otel-lgtm, glitchtip). Every image is pinned by digest; every port binds to 127.0.0.1 except LiveKit's media ports, which a phone on the LAN must reach. All secrets come from the gitignored root `.env` (generated per developer by `hv init-env` / `hv env-sync`), so no shared passwords or public dev keys exist. The `hv` CLI gains `up`, `down`, `reset`, `ps`, `logs`, `hosts`, `trust-ca` and `smoke`, built on small, tested modules: `stack.py` (compose command lines), `hosts.py` (hosts-file block), `trust.py` (Caddy CA), `smoke.py` (functional checks).

**Tech Stack:** Docker Compose v2, pgvector/pgvector (PostgreSQL 17), Valkey 8, Azurite, ClamAV, Mailpit, LiveKit server, Caddy 2, grafana/otel-lgtm, GlitchTip; Python: azure-storage-blob, redis, PyJWT.

## Global Constraints

- Everything in `MASTER_IMPLEMENTATION_PLAN.md` §13 and the SP-00a Global Constraints applies.
- Images are pinned as `name:tag@sha256:<digest>` using the digest pulled at implementation time.
- Host ports bind to `127.0.0.1`, except LiveKit RTC ports `7881/tcp` and `7882/udp`.
- No credential appears in `compose.yaml`, the Caddyfile or any committed file; they are interpolated from `.env`.
- The EICAR test string is never stored in the repository: it is assembled in memory from parts, and tests check it by SHA-256.
- Memory budget: `core` + `edge` + `media` must stay under ~4 GB of Docker memory; `obs` is optional.

## File Structure

| Path | Responsibility |
|---|---|
| `infrastructure/local/compose.yaml` | All local services, profiles, healthchecks, volumes |
| `infrastructure/local/postgres/init/01-databases.sh` | Creates `hirevion_test` and `glitchtip` databases and the `vector`, `pg_trgm`, `citext` extensions |
| `infrastructure/local/caddy/Caddyfile` | `*.hirevion.localhost` routing with Caddy's local CA |
| `infrastructure/local/downloads/.gitkeep` | Static downloads (desktop installers, update manifest) served by Caddy |
| `.env.example` | Adds `VALKEY_PASSWORD`, `AZURE_STORAGE_ACCOUNT`, `AZURE_STORAGE_KEY` |
| `tools/devcli/src/hirevion_devcli/envfile.py` | Generates the new secrets (Azure key as base64) |
| `tools/devcli/src/hirevion_devcli/stack.py` | Compose command lines and profile selection |
| `tools/devcli/src/hirevion_devcli/hosts.py` | Hostname list, managed hosts-file block, resolution check |
| `tools/devcli/src/hirevion_devcli/trust.py` | Export and trust Caddy's root certificate |
| `tools/devcli/src/hirevion_devcli/smoke.py` | Functional checks for every service |
| `tools/devcli/src/hirevion_devcli/cli.py` | New commands |
| `tools/devcli/src/hirevion_devcli/doctor.py` | Adds the hostname-resolution check |
| `.github/workflows/ci.yml` | Pins `ubuntu-24.04`; validates the compose file |
| `docs/runbooks/local-dev.md` | How to run, URLs, troubleshooting, phone testing |
| `docs/architecture/adr/0004-local-stack.md` | Decisions for the local stack |

---

### Task 1: Generated secrets for the new services

**Interfaces:**
- Produces: `GENERATED_KEYS` gains `VALKEY_PASSWORD: 32`; new `GENERATED_BASE64_KEYS: dict[str, int] = {"AZURE_STORAGE_KEY": 64}` (random bytes, standard base64); `generate_local_secrets()` returns both sets.

- [ ] **Step 1: Replace the secrets test** in `tools/devcli/tests/test_envfile.py`:

```python
def test_generated_secrets_are_random_and_long_enough() -> None:
    first = generate_local_secrets()
    second = generate_local_secrets()
    assert set(first) == set(GENERATED_KEYS) | set(GENERATED_BASE64_KEYS)
    for key, length in GENERATED_KEYS.items():
        assert len(first[key]) == length
        assert first[key] != second[key]
    for key, size in GENERATED_BASE64_KEYS.items():
        assert len(base64.b64decode(first[key], validate=True)) == size
        assert first[key] != second[key]
```

(import `base64` and `GENERATED_BASE64_KEYS`). Run: expect `ImportError`.

- [ ] **Step 2: Implement** in `envfile.py`:

```python
GENERATED_KEYS: dict[str, int] = {
    "POSTGRES_PASSWORD": 32,
    "VALKEY_PASSWORD": 32,
    "LIVEKIT_API_SECRET": 48,
    "GLITCHTIP_SECRET_KEY": 50,
}
# Values that must be standard base64 (Azure storage keys): number of random bytes.
GENERATED_BASE64_KEYS: dict[str, int] = {"AZURE_STORAGE_KEY": 64}


def generate_local_secrets() -> dict[str, str]:
    values = {key: secrets.token_urlsafe(length)[:length] for key, length in GENERATED_KEYS.items()}
    for key, size in GENERATED_BASE64_KEYS.items():
        values[key] = base64.b64encode(secrets.token_bytes(size)).decode("ascii")
    return values
```

and add to `.env.example` (local infrastructure section): `VALKEY_PASSWORD=`, `AZURE_STORAGE_ACCOUNT=hirevion`, `AZURE_STORAGE_KEY=`.

- [ ] **Step 3: Run** all tests — expect pass. Run `uv run hv env-sync` — expect the three keys added to `.env`. **Commit** `feat(devcli): generate Valkey and Azure storage secrets`.

### Task 2: Compose command lines (`stack.py`)

**Interfaces:**
- Produces: `PROJECT_NAME = "hirevion"`, `COMPOSE_FILE = Path("infrastructure/local/compose.yaml")`, `DEFAULT_PROFILES = ("core", "edge", "media")`, `OPTIONAL_PROFILES = ("obs",)`, `select_profiles(include_obs: bool) -> list[str]`, `compose_command(repo_root: Path, profiles: Sequence[str], *args: str) -> list[str]`.

- [ ] **Step 1: Failing tests** `tools/devcli/tests/test_stack.py`:

```python
from pathlib import Path

from hirevion_devcli.stack import compose_command, select_profiles


def test_select_profiles() -> None:
    assert select_profiles(include_obs=False) == ["core", "edge", "media"]
    assert select_profiles(include_obs=True) == ["core", "edge", "media", "obs"]


def test_compose_command_uses_project_env_file_and_profiles(tmp_path: Path) -> None:
    command = compose_command(tmp_path, ["core", "edge"], "up", "--detach")
    assert command == [
        "docker",
        "compose",
        "--project-name",
        "hirevion",
        "--env-file",
        str(tmp_path / ".env"),
        "--file",
        str(tmp_path / "infrastructure" / "local" / "compose.yaml"),
        "--profile",
        "core",
        "--profile",
        "edge",
        "up",
        "--detach",
    ]
```

- [ ] **Step 2: Implement** `stack.py`:

```python
"""Docker Compose command lines for the local stack."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

PROJECT_NAME = "hirevion"
COMPOSE_FILE = Path("infrastructure/local/compose.yaml")
DEFAULT_PROFILES: tuple[str, ...] = ("core", "edge", "media")
OPTIONAL_PROFILES: tuple[str, ...] = ("obs",)


def select_profiles(include_obs: bool) -> list[str]:
    return [*DEFAULT_PROFILES, *(OPTIONAL_PROFILES if include_obs else ())]


def compose_command(repo_root: Path, profiles: Sequence[str], *args: str) -> list[str]:
    command = [
        "docker",
        "compose",
        "--project-name",
        PROJECT_NAME,
        "--env-file",
        str(repo_root / ".env"),
        "--file",
        str(repo_root / COMPOSE_FILE),
    ]
    for profile in profiles:
        command += ["--profile", profile]
    return [*command, *args]
```

- [ ] **Step 3: Run** — pass. **Commit** `feat(devcli): build docker compose command lines`.

### Task 3: Hosts-file entries (`hosts.py`)

**Interfaces:**
- Produces: `DOMAIN`, `SUBDOMAINS`, `BEGIN`, `END`, `HOSTS_PATH`; `hostnames() -> list[str]`; `render_block(names: Sequence[str]) -> str` (one `127.0.0.1 name` line each); `apply_block(hosts_text: str, block: str) -> str` (inserts or replaces the managed block, CRLF line endings, other lines untouched); `unresolved(names, resolve=socket.getaddrinfo) -> list[str]` (names not resolving to a loopback address).

- [ ] **Step 1: Failing tests** `tools/devcli/tests/test_hosts.py`:

```python
import socket

from hirevion_devcli.hosts import BEGIN, END, apply_block, hostnames, render_block, unresolved


def test_hostnames_cover_every_local_site() -> None:
    names = hostnames()
    assert "app.hirevion.localhost" in names
    assert "api.hirevion.localhost" in names
    assert "livekit.hirevion.localhost" in names
    assert len(names) == len(set(names))


def test_render_block_has_one_line_per_name() -> None:
    block = render_block(["a.hirevion.localhost", "b.hirevion.localhost"])
    assert block.splitlines() == [
        BEGIN,
        "127.0.0.1 a.hirevion.localhost",
        "127.0.0.1 b.hirevion.localhost",
        END,
    ]


def test_apply_block_appends_and_keeps_existing_lines() -> None:
    hosts = "# comment\r\n127.0.0.1 localhost\r\n"
    updated = apply_block(hosts, render_block(["a.hirevion.localhost"]))
    assert updated.startswith("# comment\r\n127.0.0.1 localhost\r\n")
    assert "127.0.0.1 a.hirevion.localhost\r\n" in updated
    assert updated.endswith("\r\n")


def test_apply_block_replaces_previous_block_and_is_idempotent() -> None:
    first = apply_block("127.0.0.1 localhost\r\n", render_block(["old.hirevion.localhost"]))
    second = apply_block(first, render_block(["new.hirevion.localhost"]))
    assert "old.hirevion.localhost" not in second
    assert second.count(BEGIN) == 1
    assert apply_block(second, render_block(["new.hirevion.localhost"])) == second


def test_unresolved_reports_names_that_do_not_point_here() -> None:
    def fake_resolve(name: str, port: int) -> list[tuple[object, ...]]:
        if name == "good.hirevion.localhost":
            return [(socket.AF_INET, 1, 6, "", ("127.0.0.1", port))]
        if name == "remote.hirevion.localhost":
            return [(socket.AF_INET, 1, 6, "", ("10.0.0.5", port))]
        raise socket.gaierror("not found")

    names = ["good.hirevion.localhost", "remote.hirevion.localhost", "missing.hirevion.localhost"]
    assert unresolved(names, resolve=fake_resolve) == [
        "remote.hirevion.localhost",
        "missing.hirevion.localhost",
    ]
```

- [ ] **Step 2: Implement** `hosts.py`:

```python
"""Hosts-file entries for the *.hirevion.localhost development sites.

Browsers resolve *.localhost on their own, but Windows does not, so Python, Node
and Rust clients need these entries.
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

DOMAIN = "hirevion.localhost"
SUBDOMAINS: tuple[str, ...] = (
    "app",
    "candidate",
    "api",
    "ws",
    "eye",
    "livekit",
    "storage",
    "mail",
    "grafana",
    "errors",
    "downloads",
)
BEGIN = "# BEGIN hirevion (managed by `hv hosts`)"
END = "# END hirevion"
HOSTS_PATH = Path(r"C:\Windows\System32\drivers\etc\hosts")

Resolver = Callable[[str, int], Sequence[tuple[Any, ...]]]


def hostnames() -> list[str]:
    return [f"{name}.{DOMAIN}" for name in SUBDOMAINS]


def render_block(names: Sequence[str]) -> str:
    return "\n".join([BEGIN, *(f"127.0.0.1 {name}" for name in names), END]) + "\n"


def apply_block(hosts_text: str, block: str) -> str:
    """Insert or replace the managed block; every other line is kept as it was."""
    lines = hosts_text.splitlines()
    block_lines = block.splitlines()
    if BEGIN in lines and END in lines[lines.index(BEGIN) :]:
        start = lines.index(BEGIN)
        end = lines.index(END, start)
        lines = [*lines[:start], *block_lines, *lines[end + 1 :]]
    else:
        if lines and lines[-1].strip():
            lines.append("")
        lines.extend(block_lines)
    return "\r\n".join(lines) + "\r\n"


def unresolved(names: Sequence[str], resolve: Resolver = socket.getaddrinfo) -> list[str]:
    missing: list[str] = []
    for name in names:
        try:
            addresses = {str(info[4][0]) for info in resolve(name, 443)}
        except OSError:
            missing.append(name)
            continue
        if not any(ipaddress.ip_address(address).is_loopback for address in addresses):
            missing.append(name)
    return missing
```

- [ ] **Step 3: Run** — pass. **Commit** `feat(devcli): manage hosts entries for the local sites`.

### Task 4: Smoke-check helpers (`smoke.py`, pure parts)

**Interfaces:**
- Produces: `EICAR_SHA256`, `eicar() -> bytes`, `instream_payload(data: bytes, chunk_size: int = 8192) -> bytes`, `parse_clamd_reply(reply: bytes) -> tuple[bool, str]`, `REQUIRED_EXTENSIONS`, `parse_extensions(output: str) -> set[str]`, `blob_connection_string(account: str, key: str) -> str`, `livekit_token(api_key: str, api_secret: str, now: int) -> str`.

- [ ] **Step 1: Failing tests** `tools/devcli/tests/test_smoke.py`:

```python
import hashlib
import struct

import jwt

from hirevion_devcli.smoke import (
    EICAR_SHA256,
    blob_connection_string,
    eicar,
    instream_payload,
    livekit_token,
    parse_clamd_reply,
    parse_extensions,
)


def test_eicar_is_the_standard_test_string() -> None:
    assert hashlib.sha256(eicar()).hexdigest() == EICAR_SHA256


def test_instream_payload_frames_chunks_and_terminates() -> None:
    payload = instream_payload(b"abcde", chunk_size=3)
    expected = (
        b"zINSTREAM\0"
        + struct.pack(">I", 3)
        + b"abc"
        + struct.pack(">I", 2)
        + b"de"
        + struct.pack(">I", 0)
    )
    assert payload == expected


def test_parse_clamd_reply() -> None:
    assert parse_clamd_reply(b"stream: Win.Test.EICAR_HDB-1 FOUND\0") == (
        True,
        "stream: Win.Test.EICAR_HDB-1 FOUND",
    )
    assert parse_clamd_reply(b"stream: OK\0") == (False, "stream: OK")


def test_parse_extensions() -> None:
    assert parse_extensions("citext\npg_trgm\nplpgsql\nvector\n") == {
        "citext",
        "pg_trgm",
        "plpgsql",
        "vector",
    }


def test_blob_connection_string_points_at_local_azurite() -> None:
    assert blob_connection_string("acct", "a2V5") == (
        "DefaultEndpointsProtocol=http;AccountName=acct;AccountKey=a2V5;"
        "BlobEndpoint=http://127.0.0.1:10000/acct;"
    )


def test_livekit_token_grants_room_listing_for_one_minute() -> None:
    secret = "s" * 48
    token = livekit_token("key", secret, now=1_000)
    claims = jwt.decode(token, secret, algorithms=["HS256"], options={"verify_exp": False, "verify_nbf": False})
    assert claims == {"iss": "key", "nbf": 1_000, "exp": 1_060, "video": {"roomList": True}}
```

- [ ] **Step 2: Implement** the pure helpers in `smoke.py`:

```python
"""Functional checks for the local stack (`hv smoke`)."""

from __future__ import annotations

import struct

import jwt

# Assembled at runtime so no file in the repository contains the test string.
_EICAR_PARTS = (r"X5O!P%@AP[4\PZX54(P^)7CC)7}$", "EICAR-STANDARD-", "ANTIVIRUS-TEST-FILE!$H+H*")
EICAR_SHA256 = "275a021bbfb6489e54d471899f7db9d1663fc695ec2fe2a2c4538aabf651fd0f"
REQUIRED_EXTENSIONS = frozenset({"citext", "pg_trgm", "vector"})


def eicar() -> bytes:
    return "".join(_EICAR_PARTS).encode("ascii")


def instream_payload(data: bytes, chunk_size: int = 8192) -> bytes:
    frames = [b"zINSTREAM\0"]
    for start in range(0, len(data), chunk_size):
        chunk = data[start : start + chunk_size]
        frames.append(struct.pack(">I", len(chunk)) + chunk)
    frames.append(struct.pack(">I", 0))
    return b"".join(frames)


def parse_clamd_reply(reply: bytes) -> tuple[bool, str]:
    text = reply.rstrip(b"\0").decode("utf-8", errors="replace").strip()
    return text.endswith("FOUND"), text


def parse_extensions(output: str) -> set[str]:
    return {line.strip() for line in output.splitlines() if line.strip()}


def blob_connection_string(account: str, key: str) -> str:
    return (
        f"DefaultEndpointsProtocol=http;AccountName={account};AccountKey={key};"
        f"BlobEndpoint=http://127.0.0.1:10000/{account};"
    )


def livekit_token(api_key: str, api_secret: str, now: int) -> str:
    claims = {"iss": api_key, "nbf": now, "exp": now + 60, "video": {"roomList": True}}
    return jwt.encode(claims, api_secret, algorithm="HS256")
```

Add dependencies to `tools/devcli/pyproject.toml`: `azure-storage-blob>=12.20`, `pyjwt>=2.8`, `redis>=5.0`.

- [ ] **Step 3: Run** — pass. **Commit** `feat(devcli): add smoke-check helpers`.

### Task 5: The compose stack

**Files:** `infrastructure/local/compose.yaml`, `infrastructure/local/postgres/init/01-databases.sh`, `infrastructure/local/caddy/Caddyfile`, `infrastructure/local/downloads/.gitkeep`.

- [ ] **Step 1: Resolve image digests.** For each image below, run `docker pull <image:tag>` then `docker image inspect --format "{{index .RepoDigests 0}}" <image:tag>`, and write `image: <image:tag>@<digest>` in the compose file: `pgvector/pgvector:pg17`, `valkey/valkey:8`, `mcr.microsoft.com/azure-storage/azurite:latest`, `clamav/clamav:stable`, `axllent/mailpit:latest`, `livekit/livekit-server:latest`, `caddy:2`, `grafana/otel-lgtm:latest`, `glitchtip/glitchtip:latest`. For GlitchTip, list `/code/bin` in the image to confirm the worker and migrate commands.

- [ ] **Step 2: Write the Postgres init script** `infrastructure/local/postgres/init/01-databases.sh`:

```sh
#!/bin/sh
# Creates the extra local databases and the extensions every Hirevion database needs.
set -eu

for db in "$POSTGRES_DB" hirevion_test glitchtip; do
  exists=$(psql -tA --username "$POSTGRES_USER" --dbname postgres \
    -c "SELECT 1 FROM pg_database WHERE datname = '$db'")
  if [ "$exists" != "1" ]; then
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres -c "CREATE DATABASE \"$db\""
  fi
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$db" <<'SQL'
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS citext;
SQL
done
```

- [ ] **Step 3: Write the Caddyfile** `infrastructure/local/caddy/Caddyfile`:

```
# Local HTTPS for *.hirevion.localhost using Caddy's own CA (trust it with `uv run hv trust-ca`).
# Application upstreams (host ports 3000, 5174, 8000, 8001) come online in later sub-projects.
{
	local_certs
}

app.hirevion.localhost {
	handle /api/* {
		reverse_proxy host.docker.internal:8000
	}
	handle /ws/* {
		reverse_proxy host.docker.internal:8001
	}
	handle {
		reverse_proxy host.docker.internal:3000
	}
}

candidate.hirevion.localhost {
	reverse_proxy host.docker.internal:3000
}

api.hirevion.localhost {
	reverse_proxy host.docker.internal:8000
}

ws.hirevion.localhost {
	reverse_proxy host.docker.internal:8001
}

eye.hirevion.localhost {
	reverse_proxy host.docker.internal:5174
}

livekit.hirevion.localhost {
	reverse_proxy livekit:7880
}

storage.hirevion.localhost {
	reverse_proxy azurite:10000
}

mail.hirevion.localhost {
	reverse_proxy mailpit:8025
}

grafana.hirevion.localhost {
	reverse_proxy otel-lgtm:3000
}

errors.hirevion.localhost {
	reverse_proxy glitchtip:8000
}

downloads.hirevion.localhost {
	root * /srv/downloads
	file_server browse
}
```

- [ ] **Step 4: Write** `infrastructure/local/compose.yaml` with the services, profiles, ports, volumes, healthchecks and `.env` interpolation described in the Architecture section: postgres (`pg_isready`), valkey (`--requirepass`, `valkey-cli ping`), azurite (`AZURITE_ACCOUNTS="${AZURE_STORAGE_ACCOUNT}:${AZURE_STORAGE_KEY}"`, TCP check via node), clamav (image healthcheck, 5-minute start period for the first signature download), mailpit (`/mailpit readyz`), livekit (`LIVEKIT_CONFIG` with keys and Valkey, `--node-ip ${LIVEKIT_NODE_IP}`), caddy (Caddyfile, data volume, downloads mount), otel-lgtm (Grafana on 127.0.0.1:3001, OTLP 4317/4318), glitchtip web + worker + migrate (database `glitchtip`, Valkey db 1, Mailpit SMTP). Validate with `docker compose --env-file .env -f infrastructure/local/compose.yaml config --quiet`.

- [ ] **Step 5: Start and check.** `docker compose ... --profile core --profile edge --profile media up --detach --wait` → every service healthy; `docker stats --no-stream` → total memory for these profiles under ~4 GB. **Commit** `feat(infra): add local Docker stack`.

### Task 6: Live smoke checks and CLI commands

**Interfaces:**
- Produces (in `smoke.py`): `check_postgres(root, values, runner) -> CheckResult`, `check_valkey(password) -> CheckResult`, `check_blob_storage(account, key) -> CheckResult`, `check_clamav() -> CheckResult`, `check_mailpit(http) -> CheckResult`, `check_livekit(api_key, api_secret, http) -> CheckResult`, `check_https(url, ca_file, http) -> CheckResult`, `run_smoke(root, values, include_obs) -> list[CheckResult]`.
- Produces (in `trust.py`): `CA_CONTAINER_PATH`, `LOCAL_CA_PATH`, `export_ca_command(root) -> list[str]`, `trust_ca_command(cert: Path) -> list[str]`.
- CLI: `hv up [--obs]`, `hv down`, `hv reset`, `hv ps`, `hv logs [SERVICE]`, `hv hosts`, `hv trust-ca`, `hv smoke [--obs]`; `hv doctor` adds a `hostnames` check.

- [ ] **Step 1: Failing tests** for `trust.py` (command lines), the doctor `hostnames` check (with a fake resolver), and `hv up` invoking `compose_command(..., "up", "--detach", "--wait", "--remove-orphans")` through an injectable runner.
- [ ] **Step 2: Implement** the live checks (each wraps one real round-trip: Postgres extensions via `docker compose exec`, Valkey SET/GET/DEL, Azurite container create/upload/download/delete, ClamAV PING and EICAR-over-INSTREAM, Mailpit SMTP send then API search and delete, LiveKit `ListRooms` with a signed token, HTTPS through Caddy verified against the exported CA), `trust.py`, and the CLI commands. Elevation for `hv hosts` writes the new hosts content to a temp file and copies it over the hosts file from an elevated PowerShell (one UAC prompt), then flushes DNS.
- [ ] **Step 3: Run** unit tests, ruff, mypy — clean. **Run for real:** `uv run hv up`, `uv run hv hosts` (approve UAC), `uv run hv trust-ca` (approve the certificate dialog), `uv run hv smoke` → every check ok. **Commit** `feat(devcli): add local stack commands and smoke checks`.

### Task 7: CI, runbook and ADR

- [ ] CI: pin `runs-on: ubuntu-24.04` for all jobs; add a `compose` job: `uv sync --locked`, `uv run hv init-env`, `docker compose --env-file .env -f infrastructure/local/compose.yaml config --quiet`.
- [ ] `docs/runbooks/local-dev.md`: first-time setup (env, hosts, CA), daily commands, URL table, ports, memory tips, phone testing (set `LIVEKIT_NODE_IP` to the LAN IP; same Wi-Fi; quick tunnel for HTTPS), troubleshooting (port 80/443 in use, ClamAV first start, `hv reset`).
- [ ] `docs/architecture/adr/0004-local-stack.md` + ADR index: profiles, digest pinning, loopback-only ports, per-developer generated secrets (no public dev keys), Caddy local CA + hosts entries, Valkey instead of Redis.
- [ ] Full verification (tests, ruff, mypy, hook self-test, `hv smoke`); push; watch CI; merge.
