"""`/platform/desktop-releases` and `/platform/desktop-channels`: the desktop release registry
the super admins keep (master plan §6.18; ADR-0021). Changes need a recent password and go into
the platform's audit chain."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import Request
from pydantic import BaseModel, ConfigDict, Field

from hirevion_api.access.deps import own_tenant
from hirevion_api.authz import Principal, requires
from hirevion_api.routing import api_router
from hirevion_core.desktop import releases
from hirevion_core.desktop.releases import NewRelease
from hirevion_core.models import DesktopChannel, DesktopRelease

router = api_router(tags=["platform"])

ReadsReleases = Annotated[Principal, requires("platform.desktop_releases.manage")]
ChangesReleases = Annotated[Principal, requires("platform.desktop_releases.manage", step_up=True)]
Channel = Literal["stable", "beta"]


class ReleaseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    version: str
    channel: Channel
    arch: Literal["x64", "arm64"]
    notes: str
    url: str
    signature: str
    status: Literal["draft", "published", "withdrawn"]
    rollout_percent: int
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ReleaseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = Field(max_length=40)
    channel: Channel = "stable"
    arch: Literal["x64", "arm64"] = "x64"
    url: str = Field(max_length=500)
    signature: str = Field(max_length=2000)
    notes: str = Field("", max_length=5000)
    rollout_percent: int = Field(100, ge=0, le=100)


class ReleaseUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["draft", "published", "withdrawn"] | None = None
    rollout_percent: int | None = Field(None, ge=0, le=100)
    notes: str | None = Field(None, max_length=5000)


class ChannelResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    channel: Channel
    minimum_version: str
    download_url: str
    updated_at: datetime


class ChannelUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    minimum_version: str | None = Field(None, max_length=40)
    download_url: str | None = Field(None, max_length=500)


class ReleaseRegistry(BaseModel):
    channels: list[ChannelResponse]
    releases: list[ReleaseResponse]


def _release(row: DesktopRelease) -> ReleaseResponse:
    return ReleaseResponse.model_validate(row)


@router.get("/platform/desktop-releases")
async def list_desktop_releases(request: Request, principal: ReadsReleases) -> ReleaseRegistry:
    """The channels with their minimum versions, and every release, newest first."""
    async with own_tenant(request, principal) as session:
        channels = [await releases.get_channel(session, name) for name in ("stable", "beta")]
        rows = await releases.list_releases(session)
        return ReleaseRegistry(
            channels=[ChannelResponse.model_validate(row) for row in channels],
            releases=[_release(row) for row in rows],
        )


@router.post("/platform/desktop-releases", status_code=201)
async def create_desktop_release(
    body: ReleaseCreate, request: Request, principal: ChangesReleases
) -> ReleaseResponse:
    """Registers a build as a draft; publish it to offer it."""
    async with own_tenant(request, principal) as session:
        row = await releases.create_release(
            session,
            principal.actor(request),
            NewRelease(
                version=body.version,
                channel=body.channel,
                arch=body.arch,
                url=body.url,
                signature=body.signature,
                notes=body.notes,
                rollout_percent=body.rollout_percent,
            ),
        )
        await session.flush()
        await session.refresh(row)
        return _release(row)


@router.patch("/platform/desktop-releases/{release_id}")
async def update_desktop_release(
    release_id: UUID, body: ReleaseUpdate, request: Request, principal: ChangesReleases
) -> ReleaseResponse:
    """Publishes or withdraws a release, or changes its rollout or notes."""
    async with own_tenant(request, principal) as session:
        row = await releases.update_release(
            session,
            principal.actor(request),
            release_id,
            status=body.status,
            rollout_percent=body.rollout_percent,
            notes=body.notes,
        )
        await session.flush()
        await session.refresh(row)
        return _release(row)


@router.put("/platform/desktop-channels/{channel}")
async def update_desktop_channel(
    channel: Channel, body: ChannelUpdate, request: Request, principal: ChangesReleases
) -> ChannelResponse:
    """Sets the oldest version a channel still lets sign in, and where to download the app."""
    async with own_tenant(request, principal) as session:
        row: DesktopChannel = await releases.set_channel(
            session,
            principal.actor(request),
            channel,
            minimum_version=body.minimum_version,
            download_url=body.download_url,
        )
        return ChannelResponse.model_validate(row)
