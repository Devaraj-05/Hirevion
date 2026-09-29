import pytest

from hirevion_core.db.rls import CURRENT_ORG, grant_sql, tenant_policy_sql


def test_tenant_policy_enables_forces_and_scopes_to_the_current_organisation() -> None:
    statements = tenant_policy_sql("jobs")
    assert statements == [
        "ALTER TABLE jobs ENABLE ROW LEVEL SECURITY",
        "ALTER TABLE jobs FORCE ROW LEVEL SECURITY",
        f"CREATE POLICY jobs_tenant ON jobs TO hirevion_app "
        f"USING (organization_id = {CURRENT_ORG}) "
        f"WITH CHECK (organization_id = {CURRENT_ORG})",
    ]
    assert CURRENT_ORG == "NULLIF(current_setting('app.org_id', true), '')::uuid"


def test_grants_only_known_privileges() -> None:
    assert grant_sql("jobs", ["SELECT", "INSERT"]) == "GRANT SELECT, INSERT ON jobs TO hirevion_app"
    with pytest.raises(ValueError, match="privilege"):
        grant_sql("jobs", ["SELECT; DROP TABLE jobs"])


@pytest.mark.parametrize("name", ["Jobs", "jobs; drop", "", "1jobs", "a" * 64])
def test_rejects_unsafe_identifiers(name: str) -> None:
    with pytest.raises(ValueError, match="identifier"):
        tenant_policy_sql(name)
