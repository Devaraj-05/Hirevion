"""The permission catalogue and the five PRD §6 system roles.

The web app (`recruitment-platform/src/auth/permissions.ts`) checks the same names; the session
endpoint's response type carries this list, so the generated client catches any drift. System
roles' permissions live here; custom roles store theirs per organisation (`role_permissions`).
"""

from __future__ import annotations

from collections.abc import Iterable

PERMISSIONS: tuple[str, ...] = (
    "dashboard.view",
    "jobs.view",
    "jobs.create",
    "candidates.view",
    "candidates.manage",
    "candidates.requests.view",
    "candidates.requests.manage",
    "interviews.view",
    "interviews.manage",
    "interviews.templates.view",
    "interviews.templates.manage",
    "questions.view",
    "questions.manage",
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

# Every signed-in user may manage their own account, whatever their roles.
BASELINE_PERMISSIONS: tuple[str, ...] = ("account.manage",)

# What a custom role may hold: everything but the platform's own permissions.
ASSIGNABLE_PERMISSIONS: tuple[str, ...] = tuple(
    p for p in PERMISSIONS if not p.startswith("platform.")
)

SYSTEM_ROLES: dict[str, tuple[str, ...]] = {
    "super_admin": PERMISSIONS,
    "org_admin": tuple(p for p in PERMISSIONS if not p.startswith("platform.")),
    "recruiter": (
        "dashboard.view",
        "jobs.view",
        "jobs.create",
        "candidates.view",
        "candidates.manage",
        "candidates.requests.view",
        "candidates.requests.manage",
        "interviews.view",
        "interviews.manage",
        "interviews.templates.view",
        "interviews.templates.manage",
        "questions.view",
        "questions.manage",
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
        "candidates.requests.view",
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


def permissions_for(role_keys: Iterable[str], granted: Iterable[str] = ()) -> list[str]:
    """The baseline, the system roles' permissions and `granted` (custom roles'), in catalogue
    order. Unknown roles and names grant nothing, so a permission removed from the catalogue
    simply stops applying."""
    held = {*BASELINE_PERMISSIONS, *granted}
    held.update(p for key in role_keys for p in SYSTEM_ROLES.get(key, ()))
    return [p for p in PERMISSIONS if p in held]
