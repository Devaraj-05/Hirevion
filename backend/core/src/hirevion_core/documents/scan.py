"""Virus scanning before anything reads a file: ClamAV's clamd (INSTREAM over TCP) locally and in
production; a fake that knows only the EICAR test string for tests and for CI, which has no
ClamAV."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ScanResult:
    clean: bool
    signature: str | None = None


class ScanUnavailable(Exception):
    """The scanner couldn't be asked; the file must wait, never pass unscanned."""


class Scanner(Protocol):
    async def scan(self, data: bytes) -> ScanResult: ...


class ClamdScanner:
    def __init__(
        self, host: str, port: int, *, timeout: float = 30.0, chunk_size: int = 64 * 1024
    ) -> None:
        self._host, self._port = host, port
        self._timeout, self._chunk_size = timeout, chunk_size

    async def scan(self, data: bytes) -> ScanResult:
        try:
            async with asyncio.timeout(self._timeout):
                reader, writer = await asyncio.open_connection(self._host, self._port)
                try:
                    writer.write(b"zINSTREAM\0")
                    for start in range(0, len(data), self._chunk_size):
                        chunk = data[start : start + self._chunk_size]
                        writer.write(len(chunk).to_bytes(4, "big") + chunk)
                    writer.write((0).to_bytes(4, "big"))
                    await writer.drain()
                    reply = (await reader.readuntil(b"\0")).rstrip(b"\0").decode()
                finally:
                    writer.close()
        except (OSError, TimeoutError, asyncio.IncompleteReadError) as error:
            raise ScanUnavailable(str(error) or type(error).__name__) from error
        # "stream: OK", "stream: <signature> FOUND" or "<message> ERROR".
        verdict = reply.partition(": ")[2]
        if verdict == "OK":
            return ScanResult(clean=True)
        if verdict.endswith(" FOUND"):
            return ScanResult(clean=False, signature=verdict.removesuffix(" FOUND"))
        raise ScanUnavailable(reply)


class FakeScanner:
    """Reports the EICAR test string, and nothing else, as infected."""

    _EICAR = b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE"

    async def scan(self, data: bytes) -> ScanResult:
        if self._EICAR in data:
            return ScanResult(clean=False, signature="Eicar-Test-Signature")
        return ScanResult(clean=True)
