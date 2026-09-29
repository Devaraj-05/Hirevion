"""Functional checks for the local stack (`hv smoke`).

Each check does one real round-trip against a running service and never includes a
secret in its result.
"""

from __future__ import annotations

import smtplib
import socket
import ssl
import struct
import time
import uuid
from collections.abc import Callable, Mapping
from email.message import EmailMessage
from pathlib import Path
from typing import Any

import httpx
import jwt
import redis
from azure.core.exceptions import AzureError
from azure.storage.blob import BlobServiceClient

from hirevion_core.storage.paths import job_blob
from hirevion_core.storage.service import StorageService, StorageSettings

from .checks import CheckResult, Runner, run_command
from .stack import compose_command
from .trust import LOCAL_CA_PATH

# Assembled at runtime so no file in the repository contains the test string.
_EICAR_PARTS = (r"X5O!P%@AP[4\PZX54(P^)7CC)7}$", "EICAR-STANDARD-", "ANTIVIRUS-TEST-FILE!$H+H*")
EICAR_SHA256 = "275a021bbfb6489e54d471899f7db9d1663fc695ec2fe2a2c4538aabf651fd0f"
REQUIRED_EXTENSIONS = frozenset({"citext", "pg_trgm", "vector"})

CLAMD_ADDRESS = ("127.0.0.1", 3310)
MAILPIT_SEARCH_URL = "http://127.0.0.1:8025/api/v1/search"
LIVEKIT_LIST_ROOMS_URL = "http://127.0.0.1:7880/twirp/livekit.RoomService/ListRooms"
CADDY_CHECK_URL = "https://mail.hirevion.localhost/api/v1/info"
# One fixed blob that every run overwrites, under an organisation id no tenant can have.
SMOKE_ORG = uuid.UUID("00000000-0000-7000-8000-00000000500e")
SMOKE_JOB = uuid.UUID("00000000-0000-7000-8000-00000000500f")
SIGNED_SMOKE_BODY = b"hirevion signed-url smoke"

ValkeyFactory = Callable[[str], Any]
BlobFactory = Callable[[str], Any]
SocketFactory = Callable[[tuple[str, int]], Any]
SmtpFactory = Callable[[str, int], Any]


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


def check_postgres(
    repo_root: Path, values: Mapping[str, str], runner: Runner = run_command
) -> CheckResult:
    command = compose_command(
        repo_root,
        ["core"],
        "exec",
        "-T",
        "postgres",
        "psql",
        "-U",
        values["POSTGRES_USER"],
        "-d",
        values["POSTGRES_DB"],
        "-tAc",
        "SELECT extname FROM pg_extension ORDER BY 1",
    )
    completed = runner(command)
    if completed.returncode != 0:
        return CheckResult("postgres", "fail", "could not query Postgres; is `hv up` running?")
    missing = REQUIRED_EXTENSIONS - parse_extensions(completed.stdout)
    if missing:
        return CheckResult("postgres", "fail", "missing extensions: " + ", ".join(sorted(missing)))
    return CheckResult("postgres", "ok", "pgvector, pg_trgm and citext installed")


def _default_valkey(password: str) -> Any:
    return redis.Redis(host="127.0.0.1", port=6379, password=password, socket_timeout=5)


def check_valkey(password: str, factory: ValkeyFactory = _default_valkey) -> CheckResult:
    key = f"hv:smoke:{uuid.uuid4().hex}"
    try:
        client = factory(password)
        client.set(key, "ok", ex=30)
        value = client.get(key)
        client.delete(key)
    except redis.RedisError as exc:
        return CheckResult("valkey", "fail", f"round-trip failed ({type(exc).__name__})")
    if value != b"ok":
        return CheckResult("valkey", "fail", "wrote a key but read back something else")
    return CheckResult("valkey", "ok", "authenticated SET/GET/DEL round-trip")


def _default_blob_service(connection_string: str) -> Any:
    return BlobServiceClient.from_connection_string(connection_string)


def check_blob_storage(
    account: str, key: str, factory: BlobFactory = _default_blob_service
) -> CheckResult:
    try:
        service = factory(blob_connection_string(account, key))
        container = service.get_container_client(f"hv-smoke-{uuid.uuid4().hex[:12]}")
        container.create_container()
        try:
            blob = container.get_blob_client("hello.txt")
            blob.upload_blob(b"hirevion", overwrite=True)
            data = blob.download_blob().readall()
        finally:
            container.delete_container()
    except (AzureError, ValueError) as exc:
        return CheckResult("storage", "fail", f"blob round-trip failed ({type(exc).__name__})")
    if data != b"hirevion":
        return CheckResult("storage", "fail", "uploaded a blob but read back something else")
    return CheckResult("storage", "ok", "container create, upload, download, delete")


def _connect(address: tuple[str, int]) -> socket.socket:
    return socket.create_connection(address, timeout=30)


def _clamd_request(payload: bytes, connect: SocketFactory) -> bytes:
    with connect(CLAMD_ADDRESS) as sock:
        sock.sendall(payload)
        chunks: list[bytes] = []
        while True:
            data = sock.recv(4096)
            if not data:
                break
            chunks.append(data)
            if data.endswith(b"\0"):
                break
        return b"".join(chunks)


def check_clamav(connect: SocketFactory = _connect) -> CheckResult:
    try:
        pong = _clamd_request(b"zPING\0", connect)
        found, reply = parse_clamd_reply(_clamd_request(instream_payload(eicar()), connect))
    except OSError as exc:
        return CheckResult(
            "clamav", "fail", f"cannot reach clamd ({type(exc).__name__}); first start is slow"
        )
    if pong.rstrip(b"\0") != b"PONG":
        return CheckResult("clamav", "fail", "unexpected reply to PING")
    if not found:
        return CheckResult("clamav", "fail", f"test signature not detected: {reply}")
    return CheckResult("clamav", "ok", "detected the EICAR test signature")


def _default_smtp(host: str, port: int) -> Any:
    return smtplib.SMTP(host, port, timeout=10)


def check_mailpit(
    http: httpx.Client, smtp_factory: SmtpFactory = _default_smtp, attempts: int = 10
) -> CheckResult:
    subject = f"hv smoke {uuid.uuid4().hex}"
    message = EmailMessage()
    message["From"] = "smoke@hirevion.localhost"
    message["To"] = "dev@hirevion.localhost"
    message["Subject"] = subject
    message.set_content("Hirevion local stack smoke test.")
    query = {"query": f'subject:"{subject}"'}
    try:
        with smtp_factory("127.0.0.1", 1025) as smtp:
            smtp.send_message(message)
        count = 0
        for _ in range(attempts):
            response = http.get(MAILPIT_SEARCH_URL, params=query)
            count = int(response.json().get("messages_count", 0)) if response.is_success else 0
            if count:
                break
            time.sleep(0.2)
        http.delete(MAILPIT_SEARCH_URL, params=query)
    except (OSError, httpx.HTTPError) as exc:
        return CheckResult("mailpit", "fail", f"mail round-trip failed ({type(exc).__name__})")
    if count < 1:
        return CheckResult("mailpit", "fail", "message sent but not found in Mailpit")
    return CheckResult("mailpit", "ok", "SMTP delivery visible in Mailpit")


def check_livekit(
    api_key: str, api_secret: str, http: httpx.Client, now: Callable[[], float] = time.time
) -> CheckResult:
    token = livekit_token(api_key, api_secret, int(now()))
    try:
        response = http.post(
            LIVEKIT_LIST_ROOMS_URL, json={}, headers={"Authorization": f"Bearer {token}"}
        )
    except httpx.HTTPError as exc:
        return CheckResult("livekit", "fail", f"cannot reach LiveKit ({type(exc).__name__})")
    if response.status_code != 200:
        return CheckResult("livekit", "fail", f"ListRooms returned HTTP {response.status_code}")
    return CheckResult("livekit", "ok", "API key accepted; room service reachable")


def check_https(url: str, http: httpx.Client) -> CheckResult:
    try:
        response = http.get(url)
    except httpx.ConnectError:
        return CheckResult(
            "https", "warn", "cannot connect; run `uv run hv hosts` and `uv run hv trust-ca`"
        )
    except httpx.HTTPError as exc:
        return CheckResult("https", "fail", f"request failed ({type(exc).__name__})")
    if response.status_code >= 500:
        return CheckResult("https", "fail", f"{url} returned HTTP {response.status_code}")
    return CheckResult("https", "ok", f"trusted HTTPS via Caddy ({url})")


def check_signed_storage(upload_url: str, download_url: str, http: httpx.Client) -> CheckResult:
    """Upload and read back through Caddy with signed URLs, as browsers and the desktop do."""
    try:
        stored = http.put(
            upload_url, content=SIGNED_SMOKE_BODY, headers={"x-ms-blob-type": "BlockBlob"}
        )
        if stored.status_code != 201:
            return CheckResult(
                "signed-storage",
                "fail",
                f"signed upload returned HTTP {stored.status_code}; run `uv run hv storage-init`",
            )
        read = http.get(download_url)
    except httpx.ConnectError:
        return CheckResult(
            "signed-storage", "warn", "cannot reach https://storage.hirevion.localhost"
        )
    except httpx.HTTPError as exc:
        return CheckResult("signed-storage", "fail", f"request failed ({type(exc).__name__})")
    if read.status_code != 200 or read.content != SIGNED_SMOKE_BODY:
        return CheckResult(
            "signed-storage", "fail", f"signed download returned HTTP {read.status_code}"
        )
    return CheckResult("signed-storage", "ok", "signed upload and download through Caddy")


def signed_smoke_urls(values: Mapping[str, str]) -> tuple[str, str]:
    storage = StorageService(
        StorageSettings(
            azure_storage_account=values["AZURE_STORAGE_ACCOUNT"],
            azure_storage_key=values["AZURE_STORAGE_KEY"],  # type: ignore[arg-type]
        )
    )
    path = job_blob(SMOKE_ORG, SMOKE_JOB, "smoke.txt")
    return storage.upload_url(SMOKE_ORG, path), storage.download_url(SMOKE_ORG, path)


def check_http(name: str, url: str, http: httpx.Client) -> CheckResult:
    try:
        response = http.get(url)
    except httpx.HTTPError as exc:
        return CheckResult(name, "fail", f"cannot reach {url} ({type(exc).__name__})")
    if response.status_code != 200:
        return CheckResult(name, "fail", f"{url} returned HTTP {response.status_code}")
    return CheckResult(name, "ok", f"{url} healthy")


def run_smoke(
    repo_root: Path, values: Mapping[str, str], include_obs: bool, runner: Runner = run_command
) -> list[CheckResult]:
    ca_file = repo_root / LOCAL_CA_PATH
    with httpx.Client(timeout=15) as http:
        results = [
            check_postgres(repo_root, values, runner),
            check_valkey(values["VALKEY_PASSWORD"]),
            check_blob_storage(values["AZURE_STORAGE_ACCOUNT"], values["AZURE_STORAGE_KEY"]),
            check_clamav(),
            check_mailpit(http),
            check_livekit(values["LIVEKIT_API_KEY"], values["LIVEKIT_API_SECRET"], http),
        ]
        if include_obs:
            results.append(check_http("grafana", "http://127.0.0.1:3001/api/health", http))
            results.append(check_http("glitchtip", "http://127.0.0.1:8100/_health/", http))
    if not ca_file.exists():
        results.append(
            CheckResult("https", "warn", "Caddy CA not exported yet; run `uv run hv trust-ca`")
        )
        return results
    context = ssl.create_default_context(cafile=str(ca_file))
    with httpx.Client(timeout=15, verify=context) as tls:
        results.append(check_https(CADDY_CHECK_URL, tls))
        results.append(check_signed_storage(*signed_smoke_urls(values), tls))
    return results
