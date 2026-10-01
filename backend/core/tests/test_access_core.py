"""The access domain's building blocks: refusals, the "leave it" sentinel, the admin role."""

import pytest

from hirevion_core.access import UNSET, Unset, admin_role_key
from hirevion_core.access.errors import AccessError, Conflict, Invalid, NotFound, Refused
from hirevion_core.identity import PLATFORM_ORGANIZATION_ID
from hirevion_core.ids import uuid7


@pytest.mark.parametrize(
    ("error", "status"), [(NotFound, 404), (Conflict, 409), (Refused, 403), (Invalid, 422)]
)
def test_each_refusal_has_its_status(error: type[AccessError], status: int) -> None:
    refusal = error("name-taken", "That name is in use", field="name", detail="Pick another.")
    assert (refusal.status, refusal.code, refusal.title) == (
        status,
        "name-taken",
        "That name is in use",
    )
    assert (refusal.field, refusal.detail) == ("name", "Pick another.")


def test_unset_is_neither_none_nor_a_value() -> None:
    assert isinstance(UNSET, Unset)
    assert UNSET is not None
    assert not UNSET


def test_the_platform_keeps_super_admins_and_organisations_keep_org_admins() -> None:
    assert admin_role_key(PLATFORM_ORGANIZATION_ID) == "super_admin"
    assert admin_role_key(uuid7()) == "org_admin"
