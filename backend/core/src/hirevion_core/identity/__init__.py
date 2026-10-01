"""Recruiter-side identity: accounts, passwords, sessions and roles (SP-02, ADR-0013)."""

from uuid import UUID

# The reserved organisation that holds the super admins; its audit chain is the platform log.
PLATFORM_ORGANIZATION_ID = UUID("00000000-0000-7000-8000-000000000001")
PLATFORM_ORGANIZATION_SLUG = "platform"
