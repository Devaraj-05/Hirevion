"""The permission catalogue and the five system roles (PRD §6; SP-02 spec, "Roles")."""

import re
from pathlib import Path

from hirevion_core.identity.permissions import (
    ORGANIZATION_ROLES,
    PERMISSIONS,
    SYSTEM_ROLES,
    permissions_for,
)

WEB_CATALOGUE = Path(__file__).resolve().parents[3] / "recruitment-platform/src/auth/permissions.ts"


def test_the_catalogue_matches_the_web_app() -> None:
    # The web app checks the same names; until the client type carries them, compare the files.
    source = WEB_CATALOGUE.read_text(encoding="utf-8")
    block = re.search(r"export const PERMISSIONS = \[(.*?)\] as const", source, re.DOTALL)
    assert block is not None
    assert list(PERMISSIONS) == re.findall(r'"([a-z_.]+)"', block.group(1))


def test_every_role_manages_its_own_account_with_known_permissions() -> None:
    for role, permissions in SYSTEM_ROLES.items():
        assert "account.manage" in permissions, role
        assert set(permissions) <= set(PERMISSIONS), role


def test_only_the_super_admin_reaches_the_platform() -> None:
    for role in ORGANIZATION_ROLES:
        assert not any(p.startswith("platform.") for p in SYSTEM_ROLES[role]), role
    assert "platform.organizations.manage" in SYSTEM_ROLES["super_admin"]


def test_a_sessions_permissions_are_the_ordered_union_of_its_roles() -> None:
    combined = set(SYSTEM_ROLES["recruiter"]) | set(SYSTEM_ROLES["interviewer"])
    assert permissions_for(["interviewer", "recruiter"]) == [
        p for p in PERMISSIONS if p in combined
    ]


def test_unknown_roles_grant_nothing() -> None:
    assert permissions_for(["root"]) == []
