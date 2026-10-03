"""The storage service: server-side blob operations and signed URLs for clients.

Clients never get the account key. They get per-blob SAS URLs: write-only (create and write)
for 15 minutes to upload, and read-only for 5 minutes to download. URLs point at the public
endpoint (`https://storage.hirevion.localhost/<account>` locally, through Caddy); the server
talks to the internal one (`http://127.0.0.1:10000/<account>`, Azurite).
"""

from __future__ import annotations

from collections.abc import Sequence
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from urllib.parse import quote
from uuid import UUID

from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError
from azure.storage.blob import BlobSasPermissions, ContentSettings, CorsRule, generate_blob_sas
from azure.storage.blob.aio import BlobServiceClient, ContainerClient
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
