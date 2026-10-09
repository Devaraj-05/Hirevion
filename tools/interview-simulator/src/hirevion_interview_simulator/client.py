"""What the desktop app does on the wire (`candidate-auth.md`, `interview-session.md`): one
P-256 device key, a fresh DPoP proof per request (RFC 9449), access and interview-session
tokens bound to it."""

from __future__ import annotations

import base64
import hashlib
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import ec

USER_AGENT = "HirevionInterview/{version} (Windows 26200; x64)"
APP = {"channel": "stable", "os": "Windows 11 26200", "arch": "x64"}
CodeSource = Callable[[str], Awaitable[str]]


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


class SimulatorError(Exception):
    def __init__(self, response: httpx.Response) -> None:
        super().__init__(
            f"{response.request.method} {response.request.url.path}: "
            f"{response.status_code} {response.text[:300]}"
        )
        self.response = response
        self.status = response.status_code
        try:
            self.code = str(response.json().get("code"))
        except ValueError:
            self.code = ""


class DesktopClient:
    def __init__(
        self,
        http: httpx.AsyncClient,
        *,
        base_url: str,
        app_version: str = "1.4.0",
        device_name: str = "SIM-DESKTOP",
    ) -> None:
        self.http = http
        self.base_url = base_url.rstrip("/")
        self.app_version = app_version
        self.device_name = device_name
        self.key = ec.generate_private_key(ec.SECP256R1())
        numbers = self.key.public_key().public_numbers()
        self.jwk = {
            "kty": "EC",
            "crv": "P-256",
            "x": b64url(numbers.x.to_bytes(32, "big")),
            "y": b64url(numbers.y.to_bytes(32, "big")),
        }
        self.access: str | None = None
        self.refresh: str | None = None
        self.session_tokens: dict[str, str] = {}

    def proof(self, method: str, path: str, token: str | None = None) -> str:
        claims: dict[str, Any] = {
            "jti": str(uuid.uuid4()),
            "htm": method,
            "htu": f"{self.base_url}/api/v1{path}",
            "iat": int(time.time()),
        }
        if token is not None:
            claims["ath"] = b64url(hashlib.sha256(token.encode()).digest())
        return jwt.encode(
            claims, self.key, algorithm="ES256", headers={"typ": "dpop+jwt", "jwk": self.jwk}
        )

    async def call(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        token: str | None = None,
    ) -> httpx.Response:
        headers = {
            "DPoP": self.proof(method, path, token),
            "User-Agent": USER_AGENT.format(version=self.app_version),
        }
        if token is not None:
            headers["Authorization"] = f"DPoP {token}"
        return await self.http.request(
            method, f"{self.base_url}/api/v1{path}", json=json, headers=headers
        )

    async def _ok(self, response: httpx.Response) -> Any:
        if response.status_code >= 400:
            raise SimulatorError(response)
        return response.json() if response.content else None

    async def login(self, email: str, password: str, *, code: CodeSource | None = None) -> Any:
        body = {
            "email": email,
            "password": password,
            "app": {"version": self.app_version, **APP},
            "device": {"name": self.device_name},
        }
        answer = await self._ok(await self.call("POST", "/candidate-auth/login", json=body))
        if answer.get("status") == "otp_required":
            if code is None:
                raise RuntimeError("this device needs an emailed code; pass `code`")
            answer = await self._ok(
                await self.call(
                    "POST",
                    "/candidate-auth/otp/verify",
                    json={
                        "challenge_id": answer["challenge_id"],
                        "code": await code(answer["challenge_id"]),
                    },
                )
            )
        self.access, self.refresh = answer["access_token"], answer["refresh_token"]
        return answer

    async def session_token(self, interview_id: str) -> str:
        path = f"/candidate-auth/interviews/{interview_id}/session-token"
        answer = await self._ok(await self.call("POST", path, token=self.access))
        self.session_tokens[interview_id] = answer["session_token"]
        return str(answer["session_token"])

    async def interview(
        self, method: str, interview_id: str, action: str, json: dict[str, Any] | None = None
    ) -> httpx.Response:
        token = self.session_tokens.get(interview_id) or await self.session_token(interview_id)
        return await self.call(
            method, f"/interviews/{interview_id}/{action}", json=json, token=token
        )

    async def briefing(self, interview_id: str) -> Any:
        return await self._ok(await self.interview("GET", interview_id, "briefing"))

    async def system_check(self, interview_id: str, checks: list[str]) -> Any:
        names = set(checks) | {"cpu", "memory", "disk", "webview2"}
        results = [
            {"check": name, "status": "pass", "value": "simulated"} for name in sorted(names)
        ]
        body = {"app_version": self.app_version, "os": APP["os"], "results": results}
        return await self._ok(await self.interview("POST", interview_id, "system-checks", body))

    async def consent(
        self, interview_id: str, notice: dict[str, Any], *, accept: bool = True
    ) -> Any:
        body = {
            "notice_version": notice["version"],
            "items": [{"purpose": item["purpose"], "accepted": accept} for item in notice["items"]],
        }
        return await self._ok(await self.interview("POST", interview_id, "consents", body))

    async def request_accommodation(self, interview_id: str, kinds: list[str], note: str) -> Any:
        body = {"kinds": kinds, "note": note}
        return await self._ok(await self.interview("POST", interview_id, "accommodations", body))

    async def start(self, interview_id: str, system_check_id: str, consent_id: str) -> Any:
        body = {"system_check_id": system_check_id, "consent_id": consent_id}
        return await self._ok(await self.interview("POST", interview_id, "start", body))

    async def state(self, interview_id: str) -> Any:
        return (await self._ok(await self.interview("GET", interview_id, "session")))["state"]

    async def answer(self, interview_id: str, question_id: str, text: str) -> httpx.Response:
        body = {"question_id": question_id, "text": text}
        return await self.interview("POST", interview_id, "answer", body)

    async def workspace(
        self, interview_id: str, question_id: str, content: str, language: str = "python"
    ) -> httpx.Response:
        body = {
            "question_id": question_id,
            "kind": "code",
            "language": language,
            "content": content,
        }
        return await self.interview("POST", interview_id, "workspace", body)

    async def complete(self, interview_id: str, reason: str = "finished") -> Any:
        body = {"reason": reason}
        return await self._ok(await self.interview("POST", interview_id, "complete", body))
