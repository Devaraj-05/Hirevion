import hashlib
import struct
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any, ClassVar

import httpx
import jwt
import redis
import respx

from hirevion_devcli.smoke import (
    EICAR_SHA256,
    LIVEKIT_LIST_ROOMS_URL,
    MAILPIT_SEARCH_URL,
    SIGNED_SMOKE_BODY,
    blob_connection_string,
    check_blob_storage,
    check_clamav,
    check_https,
    check_livekit,
    check_mailpit,
    check_postgres,
    check_signed_storage,
    check_valkey,
    eicar,
    instream_payload,
    livekit_token,
    parse_clamd_reply,
    parse_extensions,
)

VALUES = {"POSTGRES_USER": "hirevion", "POSTGRES_DB": "hirevion"}


def fake_runner(stdout: str, returncode: int = 0) -> Any:
    def run(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(list(args), returncode, stdout=stdout, stderr="")

    return run


def test_check_postgres_passes_when_extensions_exist(tmp_path: Path) -> None:
    result = check_postgres(tmp_path, VALUES, fake_runner("citext\npg_trgm\nplpgsql\nvector\n"))
    assert result.status == "ok"


def test_check_postgres_names_missing_extensions(tmp_path: Path) -> None:
    result = check_postgres(tmp_path, VALUES, fake_runner("plpgsql\n"))
    assert result.status == "fail"
    assert "vector" in result.detail


def test_check_postgres_fails_when_container_is_down(tmp_path: Path) -> None:
    assert check_postgres(tmp_path, VALUES, fake_runner("", returncode=1)).status == "fail"


class FakeValkey:
    def __init__(self) -> None:
        self.data: dict[str, bytes] = {}

    def set(self, name: str, value: str, ex: int) -> bool:
        self.data[name] = value.encode()
        return True

    def get(self, name: str) -> bytes | None:
        return self.data.get(name)

    def delete(self, name: str) -> int:
        return 1 if self.data.pop(name, None) is not None else 0


def test_check_valkey_round_trip() -> None:
    store = FakeValkey()
    assert check_valkey("pw", factory=lambda password: store).status == "ok"
    assert store.data == {}


def test_check_valkey_reports_connection_errors() -> None:
    def broken(password: str) -> Any:
        raise redis.ConnectionError("refused")

    assert check_valkey("pw", factory=broken).status == "fail"


class FakeBlob:
    def __init__(self, store: dict[str, bytes], name: str) -> None:
        self.store, self.name = store, name

    def upload_blob(self, data: bytes, overwrite: bool) -> None:
        self.store[self.name] = data

    def download_blob(self) -> Any:
        data = self.store[self.name]

        class Downloader:
            def readall(self) -> bytes:
                return data

        return Downloader()


class FakeContainer:
    def __init__(self) -> None:
        self.created = False
        self.deleted = False
        self.blobs: dict[str, bytes] = {}

    def create_container(self) -> None:
        self.created = True

    def get_blob_client(self, name: str) -> FakeBlob:
        return FakeBlob(self.blobs, name)

    def delete_container(self) -> None:
        self.deleted = True


def test_check_blob_storage_round_trip_and_cleanup() -> None:
    container = FakeContainer()
    seen: list[str] = []

    class FakeService:
        def get_container_client(self, name: str) -> FakeContainer:
            return container

    def factory(connection_string: str) -> FakeService:
        seen.append(connection_string)
        return FakeService()

    result = check_blob_storage("acct", "a2V5", factory=factory)
    assert result.status == "ok"
    assert container.created and container.deleted
    assert seen == [blob_connection_string("acct", "a2V5")]


class FakeSocket:
    def __init__(self, reply: bytes) -> None:
        self.reply = reply
        self.sent = b""

    def __enter__(self) -> "FakeSocket":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def sendall(self, data: bytes) -> None:
        self.sent += data

    def recv(self, size: int) -> bytes:
        reply, self.reply = self.reply, b""
        return reply


def clamd(*replies: bytes) -> Any:
    queue = list(replies)

    def connect(address: tuple[str, int]) -> FakeSocket:
        return FakeSocket(queue.pop(0))

    return connect


def test_check_clamav_detects_the_test_signature() -> None:
    result = check_clamav(connect=clamd(b"PONG\0", b"stream: Eicar-Signature FOUND\0"))
    assert result.status == "ok"


def test_check_clamav_fails_when_signature_is_missed() -> None:
    result = check_clamav(connect=clamd(b"PONG\0", b"stream: OK\0"))
    assert result.status == "fail"


def test_check_clamav_fails_when_unreachable() -> None:
    def refused(address: tuple[str, int]) -> FakeSocket:
        raise ConnectionRefusedError

    assert check_clamav(connect=refused).status == "fail"


class FakeSmtp:
    sent: ClassVar[list[Any]] = []

    def __init__(self, host: str, port: int) -> None:
        pass

    def __enter__(self) -> "FakeSmtp":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def send_message(self, message: Any) -> None:
        FakeSmtp.sent.append(message)


@respx.mock
def test_check_mailpit_sends_and_finds_message() -> None:
    respx.get(MAILPIT_SEARCH_URL).mock(return_value=httpx.Response(200, json={"messages_count": 1}))
    delete = respx.delete(MAILPIT_SEARCH_URL).mock(return_value=httpx.Response(200))
    with httpx.Client() as client:
        result = check_mailpit(client, smtp_factory=FakeSmtp)
    assert result.status == "ok"
    assert FakeSmtp.sent
    assert delete.called


@respx.mock
def test_check_mailpit_fails_when_message_missing() -> None:
    respx.get(MAILPIT_SEARCH_URL).mock(return_value=httpx.Response(200, json={"messages_count": 0}))
    respx.delete(MAILPIT_SEARCH_URL).mock(return_value=httpx.Response(200))
    with httpx.Client() as client:
        result = check_mailpit(client, smtp_factory=FakeSmtp, attempts=1)
    assert result.status == "fail"


@respx.mock
def test_check_livekit_accepts_signed_request() -> None:
    route = respx.post(LIVEKIT_LIST_ROOMS_URL).mock(return_value=httpx.Response(200, json={}))
    with httpx.Client() as client:
        result = check_livekit("key", "s" * 48, client)
    assert result.status == "ok"
    assert route.calls.last.request.headers["Authorization"].startswith("Bearer ")


@respx.mock
def test_check_livekit_rejected_key_fails() -> None:
    respx.post(LIVEKIT_LIST_ROOMS_URL).mock(return_value=httpx.Response(401))
    with httpx.Client() as client:
        assert check_livekit("key", "s" * 48, client).status == "fail"


@respx.mock
def test_check_https_ok_and_connect_error_warns() -> None:
    respx.get("https://mail.hirevion.localhost/api/v1/info").mock(return_value=httpx.Response(200))
    respx.get("https://down.hirevion.localhost/").mock(side_effect=httpx.ConnectError("tls"))
    with httpx.Client() as client:
        assert check_https("https://mail.hirevion.localhost/api/v1/info", client).status == "ok"
        assert check_https("https://down.hirevion.localhost/", client).status == "warn"


UPLOAD = "https://storage.hirevion.localhost/hirevion/hirevion/o/jobs/j/smoke.txt?sp=cw"
DOWNLOAD = "https://storage.hirevion.localhost/hirevion/hirevion/o/jobs/j/smoke.txt?sp=r"


@respx.mock
def test_signed_storage_round_trips_through_caddy() -> None:
    put = respx.put(UPLOAD).mock(return_value=httpx.Response(201))
    respx.get(DOWNLOAD).mock(return_value=httpx.Response(200, content=SIGNED_SMOKE_BODY))
    with httpx.Client() as client:
        result = check_signed_storage(UPLOAD, DOWNLOAD, client)
    assert result.status == "ok"
    assert put.calls.last.request.headers["x-ms-blob-type"] == "BlockBlob"


@respx.mock
def test_signed_storage_names_the_fix_when_refused() -> None:
    respx.put(UPLOAD).mock(return_value=httpx.Response(404))
    with httpx.Client() as client:
        result = check_signed_storage(UPLOAD, DOWNLOAD, client)
    assert result.status == "fail"
    assert "hv storage-init" in result.detail


@respx.mock
def test_signed_storage_fails_when_the_read_differs() -> None:
    respx.put(UPLOAD).mock(return_value=httpx.Response(201))
    respx.get(DOWNLOAD).mock(return_value=httpx.Response(200, content=b"other"))
    with httpx.Client() as client:
        assert check_signed_storage(UPLOAD, DOWNLOAD, client).status == "fail"


@respx.mock
def test_signed_storage_warns_when_caddy_is_unreachable() -> None:
    respx.put(UPLOAD).mock(side_effect=httpx.ConnectError("tls"))
    with httpx.Client() as client:
        assert check_signed_storage(UPLOAD, DOWNLOAD, client).status == "warn"


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
    claims = jwt.decode(
        token,
        secret,
        algorithms=["HS256"],
        options={"verify_exp": False, "verify_nbf": False},
    )
    assert claims == {"iss": "key", "nbf": 1_000, "exp": 1_060, "video": {"roomList": True}}
