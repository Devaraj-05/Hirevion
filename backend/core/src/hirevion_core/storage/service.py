"""The storage service: server-side blob operations and signed URLs for clients.

Clients never get the account key. They get per-blob SAS URLs: write-only (create and write)
for 15 minutes to upload, and read-only for 5 minutes to download. URLs point at the public
endpoint (`https://storage.hirevion.localhost/<account>` locally, through Caddy); the server
talks to the internal one (`http://127.0.0.1:10000/<account>`, Azurite).
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import AsyncGenerator, Sequence
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import quote
from uuid import UUID

from azure.core import MatchConditions
from azure.core.exceptions import (
    ResourceExistsError,
    ResourceModifiedError,
    ResourceNotFoundError,
)
from azure.storage.blob import BlobSasPermissions, ContentSettings, CorsRule, generate_blob_sas
from azure.storage.blob.aio import BlobServiceClient, ContainerClient, StorageStreamDownloader
from pydantic import SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from hirevion_core.settings import repo_env_file
from hirevion_core.storage.paths import BlobPath, safe_filename

UPLOAD_TTL = timedelta(minutes=15)
DOWNLOAD_TTL = timedelta(minutes=5)
# Headers a browser sends when it PUTs a blob to a signed URL.
_CORS_HEADERS = [
    "content-type",
    "x-ms-blob-type",
    "x-ms-version",
    "x-ms-date",
    "x-ms-client-request-id",
]


class BlobTooLarge(ValueError):
    """A blob is bigger than its caller allows, so it wasn't read."""

    def __init__(self, message: str, size: int = 0) -> None:
        super().__init__(message)
        self.size = size


class BlobChanged(ValueError):
    """A blob was written again between checking its size and reading it."""


_FILE_CHUNK = 1024 * 1024


async def _file_chunks(source: Path) -> AsyncGenerator[bytes]:
    """A local file's bytes, read off the event loop."""
    handle = await asyncio.to_thread(source.open, "rb")
    try:
        while chunk := await asyncio.to_thread(handle.read, _FILE_CHUNK):
            yield chunk
    finally:
        await asyncio.to_thread(handle.close)


class StorageSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", hide_input_in_errors=True)

    azure_storage_account: str
    azure_storage_key: SecretStr
    azure_storage_container: str = "hirevion"
    # Where the server reaches storage, and where signed URLs point (default: the local stack).
    azure_storage_endpoint: str | None = None
    storage_public_endpoint: str | None = None

    @property
    def internal_endpoint(self) -> str:
        endpoint = (
            self.azure_storage_endpoint or f"http://127.0.0.1:10000/{self.azure_storage_account}"
        )
        return endpoint.rstrip("/")

    @property
    def public_endpoint(self) -> str:
        endpoint = (
            self.storage_public_endpoint
            or f"https://storage.hirevion.localhost/{self.azure_storage_account}"
        )
        return endpoint.rstrip("/")


def load_storage_settings() -> StorageSettings:
    return StorageSettings(_env_file=repo_env_file())  # type: ignore[call-arg]


def load_optional_storage() -> StorageService | None:
    """Blob storage when `AZURE_STORAGE_*` is configured; None where it isn't (CI's API-only
    jobs), so everything but file uploads keeps working."""
    try:
        return StorageService(load_storage_settings())
    except ValidationError:
        return None


def _client(settings: StorageSettings) -> BlobServiceClient:
    credential = {
        "account_name": settings.azure_storage_account,
        "account_key": settings.azure_storage_key.get_secret_value(),
    }
    return BlobServiceClient(account_url=settings.internal_endpoint, credential=credential)


async def ensure_storage(settings: StorageSettings, allowed_origins: Sequence[str]) -> None:
    """Create the (private) container and allow browser uploads from `allowed_origins`."""
    async with _client(settings) as client:
        with suppress(ResourceExistsError):
            await client.create_container(settings.azure_storage_container)
        rule = CorsRule(
            list(allowed_origins),
            ["GET", "HEAD", "PUT", "OPTIONS"],
            allowed_headers=_CORS_HEADERS,
            exposed_headers=["etag", "x-ms-request-id"],
            max_age_in_seconds=3600,
        )
        await client.set_service_properties(cors=[rule])


class StorageService:
    def __init__(self, settings: StorageSettings) -> None:
        self.settings = settings
        self._service: BlobServiceClient | None = None

    @property
    def _container(self) -> ContainerClient:
        if self._service is None:
            self._service = _client(self.settings)
        return self._service.get_container_client(self.settings.azure_storage_container)

    async def aclose(self) -> None:
        if self._service is not None:
            await self._service.close()
            self._service = None

    async def put(self, path: BlobPath, data: bytes, content_type: str) -> None:
        await self._container.upload_blob(
            str(path),
            data,
            overwrite=True,
            content_settings=ContentSettings(content_type=content_type),
        )

    async def get(self, path: BlobPath) -> bytes:
        download = await self._container.download_blob(str(path))
        return await download.readall()

    async def exists(self, path: BlobPath) -> bool:
        return bool(await self._container.get_blob_client(str(path)).exists())

    async def _open(self, path: BlobPath, max_bytes: int | None) -> StorageStreamDownloader[bytes]:
        """Checks the blob's size from its properties before reading a byte, then reads exactly
        that version of it: FileNotFoundError, BlobTooLarge, or BlobChanged if it was written
        again in between."""
        blob = self._container.get_blob_client(str(path))
        try:
            properties = await blob.get_blob_properties()
        except ResourceNotFoundError as error:
            raise FileNotFoundError(str(path)) from error
        if max_bytes is not None and properties.size > max_bytes:
            raise BlobTooLarge(
                f"{path} is {properties.size} bytes, more than {max_bytes}", properties.size
            )
        try:
            return await blob.download_blob(
                etag=properties.etag, match_condition=MatchConditions.IfNotModified
            )
        except ResourceModifiedError as error:
            raise BlobChanged(str(path)) from error
        except ResourceNotFoundError as error:
            raise FileNotFoundError(str(path)) from error

    async def digest(self, path: BlobPath, max_bytes: int | None = None) -> tuple[int, str] | None:
        """The size and SHA-256 (hex) of a blob, read in chunks so a large one never sits in
        memory; None if there is no such blob. A blob larger than `max_bytes`, or written again
        while it was being checked, isn't read: it comes back with an empty hash, which matches
        nothing."""
        try:
            download = await self._open(path, max_bytes)
        except FileNotFoundError:
            return None
        except BlobTooLarge as error:
            return error.size, ""
        except BlobChanged:
            return 0, ""
        sha256 = hashlib.sha256()
        size = 0
        async for chunk in download.chunks():
            await asyncio.to_thread(sha256.update, chunk)
            size += len(chunk)
        return size, sha256.hexdigest()

    async def download_to(
        self, path: BlobPath, destination: Path, max_bytes: int | None = None
    ) -> None:
        """Streams a blob into a local file; FileNotFoundError if there is no such blob,
        BlobTooLarge (before reading it) if it is larger than `max_bytes`, and BlobChanged if it
        was written again while being read."""
        download = await self._open(path, max_bytes)
        with destination.open("wb") as handle:
            async for chunk in download.chunks():
                await asyncio.to_thread(handle.write, chunk)

    async def upload_file(self, path: BlobPath, source: Path, content_type: str) -> None:
        """Streams a local file into a blob (replacing it), reading the file off the event loop."""
        await self.upload_file_hashed(path, source, content_type)

    async def upload_file_hashed(
        self, path: BlobPath, source: Path, content_type: str
    ) -> tuple[int, str]:
        """`upload_file`, also returning the bytes sent and their SHA-256 (one read of the file)."""
        digest = hashlib.sha256()
        size = 0

        async def hashed() -> AsyncGenerator[bytes]:
            nonlocal size
            inner = _file_chunks(source)
            try:
                async for chunk in inner:
                    digest.update(chunk)
                    size += len(chunk)
                    yield chunk
            finally:
                await inner.aclose()

        chunks = hashed()
        try:
            await self._container.upload_blob(
                str(path),
                chunks,
                length=source.stat().st_size,
                overwrite=True,
                content_settings=ContentSettings(content_type=content_type),
            )
        finally:
            # The client stops reading at `length` without exhausting the generator, which
            # would keep the file open (and, on Windows, undeletable) until it is collected.
            await chunks.aclose()
        return size, digest.hexdigest()

    async def delete(self, path: BlobPath) -> None:
        with suppress(ResourceNotFoundError):
            await self._container.delete_blob(str(path))

    def upload_url(
        self, organization_id: UUID, path: BlobPath, expires: timedelta = UPLOAD_TTL
    ) -> str:
        """A URL that can create or overwrite this one blob, and nothing else, until `expires`."""
        permission = BlobSasPermissions(create=True, write=True)
        return self._signed_url(organization_id, path, permission, expires)

    def download_url(
        self,
        organization_id: UUID,
        path: BlobPath,
        expires: timedelta = DOWNLOAD_TTL,
        filename: str | None = None,
    ) -> str:
        """A URL that can read this one blob until `expires`; `filename` makes it a download."""
        disposition = (
            f'attachment; filename="{safe_filename(filename)}"' if filename is not None else None
        )
        return self._signed_url(
            organization_id,
            path,
            BlobSasPermissions(read=True),
            expires,
            content_disposition=disposition,
        )

    def _signed_url(
        self,
        organization_id: UUID,
        path: BlobPath,
        permission: BlobSasPermissions,
        expires: timedelta,
        content_disposition: str | None = None,
    ) -> str:
        if path.organization_id != organization_id:
            raise ValueError("this blob belongs to another organisation")
        public = self.settings.public_endpoint
        # The SAS protocol is checked by the storage service, so it must allow what the service
        # receives: plain HTTP locally, where Caddy terminates TLS in front of Azurite.
        https_only = self.settings.internal_endpoint.startswith("https://")
        token = generate_blob_sas(
            account_name=self.settings.azure_storage_account,
            container_name=self.settings.azure_storage_container,
            blob_name=str(path),
            account_key=self.settings.azure_storage_key.get_secret_value(),
            permission=permission,
            expiry=datetime.now(UTC) + expires,
            protocol="https" if https_only else "https,http",
            content_disposition=content_disposition,
        )
        return f"{public}/{self.settings.azure_storage_container}/{quote(str(path))}?{token}"
