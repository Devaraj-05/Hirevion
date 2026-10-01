"""Why an access operation was refused. The API answers each as an RFC 9457 problem with the
same status and `code`; `field` points a form at the input to fix."""

from __future__ import annotations

from typing import ClassVar


class AccessError(Exception):
    status: ClassVar[int] = 400

    def __init__(
        self, code: str, title: str, *, field: str | None = None, detail: str | None = None
    ) -> None:
        super().__init__(f"{self.status} {code}")
        self.code = code
        self.title = title
        self.field = field
        self.detail = detail


class NotFound(AccessError):
    status = 404


class Refused(AccessError):
    """Not allowed for this actor (escalation, the Platform organisation, ...)."""

    status = 403


class Conflict(AccessError):
    """Clashes with what exists (a name in use, the last admin, a system role, ...)."""

    status = 409


class Invalid(AccessError):
    """A value the rules don't accept (an unknown time zone, team or permission, ...)."""

    status = 422
