"""The permission catalogue and the five PRD §6 system roles.

The web app (`recruitment-platform/src/auth/permissions.ts`) checks the same names; the session
endpoint's response type carries this list, so the generated client catches any drift. SP-02b
adds custom roles, whose permissions are stored per organisation.
"""

from __future__ import annotations

from collections.abc import Iterable

PERMISSIONS: tuple[str, ...] = (
    "dashboard.view",
    "jobs.view",
    "jobs.create",
    "candidates.view",
    "interviews.view",
    "interviews.templates.view",
    "questions.view",
    "reports.view",
    "reports.interview.view",
    "reports.proctoring.view",
    "reports.candidate.view",
    "reports.analytics.view",
    "notifications.view",
    "account.manage",
    "admin.view",
    "admin.organization.manage",
    "admin.users.manage",
    "admin.roles.manage",
    "admin.teams.manage",
    "admin.departments.manage",
    "admin.ai.manage",
    "admin.integrations.manage",
    "admin.security.manage",
    "admin.proctoring.manage",
    "admin.retention.manage",
    "admin.branding.manage",
    "admin.webhooks.manage",
    "admin.api_keys.manage",
    "admin.usage.view",
    "admin.audit.view",
    "platform.view",
    "platform.organizations.manage",
    "platform.ai.manage",
    "platform.security.manage",
    "platform.app_catalog.manage",
    "platform.desktop_releases.manage",
    "platform.audit.view",
    "platform.health.view",
)

SYSTEM_ROLES: dict[str, tuple[str, ...]] = {
    "super_admin": PERMISSIONS,
    "org_admin": tuple(p for p in PERMISSIONS if not p.startswith("platform.")),
    "recruiter": (
        "dashboard.view",
        "jobs.view",
        "jobs.create",
        "candidates.view",
        "interviews.view",
        "interviews.templates.view",
        "questions.view",
        "reports.view",
        "reports.interview.view",
        "reports.proctoring.view",
        "reports.candidate.view",
        "reports.analytics.view",
        "notifications.view",
        "account.manage",
    ),
    "hiring_manager": (
        "dashboard.view",
        "jobs.view",
        "candidates.view",
        "interviews.view",
        "reports.view",
        "reports.interview.view",
        "reports.proctoring.view",
        "reports.candidate.view",
        "notifications.view",
        "account.manage",
    ),
    "interviewer": (
        "dashboard.view",
        "interviews.view",
        "reports.view",
        "reports.interview.view",
        "notifications.view",
        "account.manage",
    ),
}

# The roles every ordinary organisation gets; only the Platform organisation has super_admin.
ORGANIZATION_ROLES: tuple[str, ...] = ("org_admin", "recruiter", "hiring_manager", "interviewer")

# Stored on the role rows; the web app shows translated names for system roles by key.
SYSTEM_ROLE_NAMES: dict[str, str] = {
    "super_admin": "Super admin",
    "org_admin": "Organisation admin",
    "recruiter": "Recruiter",
    "hiring_manager": "Hiring manager",
    "interviewer": "Interviewer",
}


def permissions_for(role_keys: Iterable[str]) -> list[str]:
    """The union of the roles' permissions, in catalogue order. Unknown roles grant nothing."""
    granted = {p for key in role_keys for p in SYSTEM_ROLES.get(key, ())}
    return [p for p in PERMISSIONS if p in granted]
