"""Screening configuration: the organisation default and a job's own (SP-05 Task 2)."""

from collections.abc import Awaitable, Callable
from uuid import UUID

import pytest

from hirevion_core.access.actor import Actor
from hirevion_core.access.errors import Invalid
from hirevion_core.db.session import Database
from hirevion_core.identity.permissions import permissions_for
from hirevion_core.jobs import jobs
from hirevion_core.jobs.jobs import JobChanges
from hirevion_core.screening import config
from hirevion_core.screening.config import DEFAULT_WEIGHTS

pytestmark = pytest.mark.db

MakeOrganization = Callable[[str], Awaitable[UUID]]


@pytest.fixture
async def acme(make_organization: MakeOrganization, make_user) -> Actor:
    organization = await make_organization("Acme")
    user = await make_user(organization, roles=["org_admin"])
    return Actor(user, organization, frozenset(permissions_for(["org_admin"])))


async def test_a_job_inherits_the_default_until_it_has_its_own(
    app_db: Database, acme: Actor
) -> None:
    async with app_db.tenant(acme.organization_id) as session:
        job = await jobs.create_job(session, acme, JobChanges(title="Engineer"))
        built_in = await config.effective(session, job.id)
        assert (built_in.weights, built_in.blind, built_in.inherited) == (
            DEFAULT_WEIGHTS,
            True,
            True,
        )

        org_weights = {**DEFAULT_WEIGHTS, "education": 0, "domain": 15}
        await config.save(session, acme, None, weights=org_weights)
        inherited = await config.effective(session, job.id)
        assert (inherited.weights, inherited.inherited, inherited.version) == (org_weights, True, 1)

        own = await config.save(session, acme, job.id, blind=False)
        assert (own.weights, own.blind, own.inherited, own.version) == (
            org_weights,
            False,
            False,
            1,
        )
        again = await config.save(session, acme, job.id, knockouts={"required_skills": False})
        assert (again.version, again.knockouts["required_skills"]) == (2, False)

        await config.reset(session, acme, job.id)
        assert (await config.effective(session, job.id)).inherited is True


async def test_weights_must_be_known_whole_and_add_up_to_100(app_db: Database, acme: Actor) -> None:
    async with app_db.tenant(acme.organization_id) as session:
        for weights, code in (
            ({**DEFAULT_WEIGHTS, "experience": 30}, "weights-total"),
            ({**DEFAULT_WEIGHTS, "vibes": 0}, "unknown-factor"),
            ({**DEFAULT_WEIGHTS, "experience": -5, "domain": 40}, "invalid-weight"),
        ):
            with pytest.raises(Invalid) as refusal:
                await config.save(session, acme, None, weights=weights)
            assert (refusal.value.code, refusal.value.field) == (code, "weights")
