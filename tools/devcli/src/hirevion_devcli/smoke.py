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
