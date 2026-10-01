"""The permission catalogue and the five system roles (PRD §6; SP-02 spec, "Roles")."""

import re
from pathlib import Path

from hirevion_core.identity.permissions import (
    ASSIGNABLE_PERMISSIONS,
    BASELINE_PERMISSIONS,
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


def test_unknown_roles_grant_only_the_baseline() -> None:
    assert permissions_for(["root"]) == list(BASELINE_PERMISSIONS)


def test_every_session_manages_its_own_account() -> None:
    assert permissions_for([]) == ["account.manage"]


def test_custom_role_grants_join_in_catalogue_order_and_unknown_names_are_dropped() -> None:
    # A permission removed from the catalogue simply stops applying to the roles that stored it.
    assert permissions_for(["interviewer"], ["jobs.view", "nonsense.perm"]) == [
        p for p in PERMISSIONS if p in {*SYSTEM_ROLES["interviewer"], "jobs.view"}
    ]


def test_custom_roles_may_hold_everything_but_the_platform() -> None:
    assert not any(p.startswith("platform.") for p in ASSIGNABLE_PERMISSIONS)
    assert set(ASSIGNABLE_PERMISSIONS) | {
        p for p in PERMISSIONS if p.startswith("platform.")
    } == set(PERMISSIONS)
    assert list(ASSIGNABLE_PERMISSIONS) == [p for p in PERMISSIONS if p in ASSIGNABLE_PERMISSIONS]
