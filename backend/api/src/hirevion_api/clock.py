"""Clock sync: clients line their event times up with the server clock (master plan §3.2).

A client notes its own clock when sending (t0) and receiving (t3). With the server's
`received_at_ms` (t1) and `sent_at_ms` (t2), its offset from the server is
`((t1 - t0) + (t2 - t3)) / 2` and the network round trip is `(t3 - t0) - (t2 - t1)`. It
trusts the sample with the shortest round trip (`@hirevion/api-client` `syncClock`).
"""

from __future__ import annotations

import time

from pydantic import BaseModel, Field

from hirevion_api.routing import api_router

router = api_router(tags=["clock"])


class ServerTime(BaseModel):
    received_at_ms: int = Field(description="Server clock (Unix ms) when the request arrived.")
    sent_at_ms: int = Field(description="Server clock (Unix ms) when the response was built.")


def _now_ms() -> int:
    return time.time_ns() // 1_000_000


@router.get("/time")
async def get_server_time() -> ServerTime:
    """The server clock, for estimating this client's clock offset."""
    received = _now_ms()
    return ServerTime(received_at_ms=received, sent_at_ms=_now_ms())
