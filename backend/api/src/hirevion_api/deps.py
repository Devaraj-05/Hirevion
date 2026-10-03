"""Dependencies for the shared resources the lifespan (or a test) puts on `app.state`."""

from __future__ import annotations

from typing import cast

from fastapi import Request
from redis.asyncio import Redis

from hirevion_core.db.session import Database
from hirevion_core.documents.intake import BlobStore


def get_db(request: Request) -> Database:
    db = request.app.state.db
    if db is None:
        raise RuntimeError("The API has no database; start it through its lifespan.")
    return cast(Database, db)


def get_redis(request: Request) -> Redis:
    redis = request.app.state.redis
    if redis is None:
        raise RuntimeError("The API has no Valkey client; start it through its lifespan.")
    return cast(Redis, redis)


def client_ip(request: Request) -> str:
    """The caller's address; X-Forwarded-For counts only from `HV_API_TRUSTED_PROXIES`."""
    return request.client.host if request.client else "unknown"


def get_storage(request: Request) -> BlobStore:
    storage = getattr(request.app.state, "storage", None)
    if storage is None:
        raise RuntimeError("The API has no blob storage; start it through its lifespan.")
    return cast(BlobStore, storage)
