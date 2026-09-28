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
    claims = jwt.decode(
        token,
        secret,
        algorithms=["HS256"],
        options={"verify_exp": False, "verify_nbf": False},
    )
    assert claims == {"iss": "key", "nbf": 1_000, "exp": 1_060, "video": {"roomList": True}}
