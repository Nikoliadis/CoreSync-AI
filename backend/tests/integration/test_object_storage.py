"""The storage adapter against a real S3-compatible server.

This file exists because of a bug that every other test in the suite was structurally
incapable of catching. The upload credential was first written as a presigned **PUT**
with the size limit signed in as `ContentLength`. It passed unit tests, type checking and
the whole API suite — all of which run against an in-memory double that returns whatever
string it is asked for — and it could never have worked:

- `Content-Length` becomes part of the signature, so the body must be *exactly* the
  maximum size, not at most it.
- A browser sets `Content-Length` from the body and refuses to let script override it.

Against MinIO the result was `403 SignatureDoesNotMatch` on every single upload. A fake
cannot tell you that. The rule this encodes: **the boundary is the thing that has to be
exercised for real.**

Skipped when no storage is configured, so a machine without the compose stack running
does not fail the suite — but it is skipped loudly rather than passing quietly.
"""

from __future__ import annotations

import asyncio
import io
from uuid import uuid4

import httpx
import pytest
from PIL import Image

from coresync.core.config import get_settings
from coresync.domain.progress.photos import MAX_UPLOAD_BYTES
from coresync.infrastructure.storage.s3 import S3ObjectStorage

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def storage() -> S3ObjectStorage:
    settings = get_settings()
    if not settings.photos_enabled:
        pytest.skip(
            "no object storage configured — set STORAGE_BACKEND=s3compat and run "
            "`docker compose up -d minio`"
        )
    return S3ObjectStorage(
        bucket=settings.s3_bucket,
        endpoint_url=settings.s3_endpoint_url,
        region=settings.s3_region,
        access_key=settings.s3_access_key,
        secret_key=settings.s3_secret_key,
    )


@pytest.fixture
def key() -> str:
    return f"tests/{uuid4()}.jpg"


def jpeg(size_px: int = 60) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (size_px, size_px), (10, 20, 30)).save(buffer, format="JPEG")
    return buffer.getvalue()


class TestUploadCredential:
    async def test_a_client_can_actually_upload_with_it(
        self, storage: S3ObjectStorage, key: str
    ) -> None:
        """The test the original design would have failed.

        Posted the way a browser posts a form: the policy fields verbatim, then the file.
        Nothing here sets a `Content-Length` by hand, because nothing can.
        """
        await storage.ensure_bucket()
        url, fields, _ = await storage.create_upload_credential(
            path=key,
            expires_in_seconds=300,
            max_bytes=MAX_UPLOAD_BYTES,
            content_type="image/jpeg",
        )

        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                url, data=fields, files={"file": ("photo.jpg", jpeg(), "image/jpeg")}
            )

        assert response.status_code in (200, 204), response.text
        stored = await storage.head(key)
        assert stored is not None
        assert stored.size_bytes == len(jpeg())

        await storage.delete(key)

    async def test_storage_itself_refuses_an_oversized_body(
        self, storage: S3ObjectStorage, key: str
    ) -> None:
        """The size limit has to be enforced by the bucket, not by us afterwards.

        `content-length-range` is a condition of the signed policy, so the bytes are
        rejected at the door. Checking the size after the upload would mean a 5 GB body
        had already been accepted and paid for.
        """
        await storage.ensure_bucket()
        url, fields, _ = await storage.create_upload_credential(
            path=key, expires_in_seconds=300, max_bytes=1024, content_type="image/jpeg"
        )

        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                url, data=fields, files={"file": ("big.jpg", b"x" * 4096, "image/jpeg")}
            )

        assert response.status_code == 400
        assert "EntityTooLarge" in response.text
        assert await storage.head(key) is None

    async def test_the_credential_is_scoped_to_one_key(
        self, storage: S3ObjectStorage, key: str
    ) -> None:
        """A leaked credential must not be usable against a different object.

        The key is signed into the policy, so substituting another one is refused. This
        is what keeps one user's upload URL from reaching another user's photo.
        """
        await storage.ensure_bucket()
        url, fields, _ = await storage.create_upload_credential(
            path=key,
            expires_in_seconds=300,
            max_bytes=MAX_UPLOAD_BYTES,
            content_type="image/jpeg",
        )
        tampered = {**fields, "key": "tests/somebody-elses-photo.jpg"}

        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                url, data=tampered, files={"file": ("photo.jpg", jpeg(), "image/jpeg")}
            )

        assert response.status_code >= 400
        assert await storage.head("tests/somebody-elses-photo.jpg") is None


class TestObjectLifecycle:
    async def test_write_read_head_delete(self, storage: S3ObjectStorage, key: str) -> None:
        await storage.ensure_bucket()

        assert await storage.head(key) is None, "a key that was never written must be None"

        await storage.write_bytes(path=key, data=jpeg(), content_type="image/jpeg")
        assert await storage.read_bytes(key) == jpeg()

        stored = await storage.head(key)
        assert stored is not None
        assert stored.content_type == "image/jpeg"

        await storage.delete(key)
        # Not an error — the caller asked for a photo that is gone, which is a fact and
        # not a failure.
        assert await storage.read_bytes(key) is None

    async def test_deleting_twice_is_not_an_error(self, storage: S3ObjectStorage, key: str) -> None:
        # The delete use case removes the thumbnail too, and a photo that failed
        # processing never had one.
        await storage.delete(key)
        await storage.delete(key)

    async def test_a_read_url_actually_serves_the_object(
        self, storage: S3ObjectStorage, key: str
    ) -> None:
        await storage.ensure_bucket()
        await storage.write_bytes(path=key, data=jpeg(), content_type="image/jpeg")

        url, _ = await storage.create_read_url(path=key, expires_in_seconds=120)
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(url)

        assert response.status_code == 200
        assert response.content == jpeg()
        # Served as an attachment, so a URL that escapes into an address bar downloads a
        # file rather than rendering somebody's photo in a tab.
        assert "attachment" in response.headers.get("content-disposition", "")

        await storage.delete(key)

    async def test_an_expired_read_url_is_refused(self, storage: S3ObjectStorage, key: str) -> None:
        """The property the whole read path depends on.

        If a signed URL outlived its expiry, every photo URL ever handed out would still
        work — and the short TTL that makes it safe to put one in a response body would
        be decoration.
        """
        await storage.ensure_bucket()
        await storage.write_bytes(path=key, data=jpeg(), content_type="image/jpeg")

        # One second, then let it lapse. Faster than waiting out a realistic TTL and it
        # exercises the same check in the same server.
        url, _ = await storage.create_read_url(path=key, expires_in_seconds=1)
        await asyncio.sleep(2)

        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(url)

        assert response.status_code == 403
        await storage.delete(key)

    async def test_the_bucket_is_not_public(self, storage: S3ObjectStorage, key: str) -> None:
        """Unsigned access must fail.

        A public bucket would make every signed URL pointless, and the failure is silent:
        everything works, and the photos are also readable by anyone who guesses a key.
        """
        await storage.ensure_bucket()
        await storage.write_bytes(path=key, data=jpeg(), content_type="image/jpeg")

        settings = get_settings()
        unsigned = f"{settings.s3_endpoint_url}/{settings.s3_bucket}/{key}"
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(unsigned)

        assert response.status_code in (401, 403), (
            f"the bucket is publicly readable at {unsigned} — every progress photo in it "
            "is world-readable to anyone who guesses a key"
        )
        await storage.delete(key)
