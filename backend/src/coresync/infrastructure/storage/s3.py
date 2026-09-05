"""S3-compatible object storage for progress photos.

The same code runs against MinIO locally and against Azure Blob Storage's S3-compatible
endpoint in production, which is the point of the port: the most sensitive data in the
system should not have one storage path in development and a different, less-exercised
one in production.

**Bytes never pass through the API.** The client is handed a presigned URL scoped to one
object key and writes directly to storage; the API only ever sees metadata. That is what
keeps a 15 MB upload off the request path, but more importantly it means an API process
never holds an un-stripped photo in memory.

boto3 is synchronous. Presigning is pure local computation — an HMAC over a canonical
request, no network at all — so it is called directly. Everything that does I/O goes
through ``asyncio.to_thread``, because a blocking socket read inside the event loop
stalls every other request on the process.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from coresync.core.logging import get_logger
from coresync.domain.progress.repositories import StoredObject

logger = get_logger(__name__)

# Object keys that do not exist come back as one of these. Distinguished from a real
# failure so "the client never finished uploading" reads as None rather than an outage.
_MISSING_CODES = frozenset({"404", "NoSuchKey", "NotFound"})


class S3ObjectStorage:
    """An ``ObjectStoragePort`` over any S3-compatible endpoint."""

    def __init__(
        self,
        *,
        bucket: str,
        endpoint_url: str,
        region: str,
        access_key: str,
        secret_key: str,
    ) -> None:
        self._bucket = bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url or None,
            region_name=region,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            # SigV4 explicitly. MinIO accepts both, but a presigned URL signed with the
            # older algorithm is rejected by Azure's gateway, and the failure would only
            # appear in production.
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

    # ------------------------------------------------------------------ presigning

    async def create_upload_credential(
        self,
        *,
        path: str,
        expires_in_seconds: int,
        max_bytes: int,
        content_type: str | None = None,
    ) -> tuple[str, dict[str, str], datetime]:
        """A browser-form POST policy for exactly this object.

        A POST policy rather than a signed PUT, because the size limit has to be
        something *storage* enforces. `content-length-range` is a condition of the
        policy, so an oversized body comes back `EntityTooLarge` from the bucket and
        never reaches us. The PUT alternative signs the exact content length into the
        request, which no browser can satisfy — it sets `Content-Length` from the body
        and forbids script from overriding it — so every upload fails the signature
        check instead.

        Note what this does *not* grant: no list, no read, no delete, and no other key.
        A leaked credential can write one not-yet-processed photo belonging to the person
        it was issued to, and nothing else.

        The content type is pinned by the policy rather than chosen by the uploader, so
        the stored object cannot claim to be something it is not. What is actually in
        those bytes is still not trusted — the processor decodes the image and rejects
        anything that is not one.
        """
        fields: dict[str, str] = {}
        conditions: list[object] = [["content-length-range", 1, max_bytes]]
        if content_type:
            fields["Content-Type"] = content_type
            conditions.append({"Content-Type": content_type})

        def _sign() -> dict[str, object]:
            signed: dict[str, object] = self._client.generate_presigned_post(
                Bucket=self._bucket,
                Key=path,
                Fields=dict(fields),
                Conditions=conditions,
                ExpiresIn=expires_in_seconds,
            )
            return signed

        # Signing is local computation, but botocore builds a fresh request context for
        # a POST policy; kept off the loop for the same reason as the rest of this class.
        signed = await asyncio.to_thread(_sign)
        return (
            str(signed["url"]),
            {str(k): str(v) for k, v in dict(signed["fields"]).items()},
            datetime.now(UTC) + timedelta(seconds=expires_in_seconds),
        )

    async def create_read_url(self, *, path: str, expires_in_seconds: int) -> tuple[str, datetime]:
        """A short-lived read URL, served as an attachment.

        `attachment` rather than `inline` so a URL that escapes into a browser address
        bar downloads a file instead of rendering somebody's photo in a tab that may be
        screen-shared or in someone's history.
        """
        url = self._client.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": self._bucket,
                "Key": path,
                "ResponseContentDisposition": "attachment",
            },
            ExpiresIn=expires_in_seconds,
        )
        return url, datetime.now(UTC) + timedelta(seconds=expires_in_seconds)

    # ------------------------------------------------------------------------- i/o

    async def read_bytes(self, path: str) -> bytes | None:
        def _read() -> bytes | None:
            try:
                response = self._client.get_object(Bucket=self._bucket, Key=path)
            except ClientError as error:
                if _is_missing(error):
                    return None
                raise
            body: bytes = response["Body"].read()
            return body

        return await asyncio.to_thread(_read)

    async def write_bytes(self, *, path: str, data: bytes, content_type: str) -> None:
        def _write() -> None:
            self._client.put_object(
                Bucket=self._bucket,
                Key=path,
                Body=data,
                ContentType=content_type,
                # Belt and braces alongside a private bucket policy. A bucket that is
                # accidentally made public should still not expose these objects.
                ACL="private",
            )

        await asyncio.to_thread(_write)

    async def delete(self, path: str) -> None:
        def _delete() -> None:
            self._client.delete_object(Bucket=self._bucket, Key=path)

        await asyncio.to_thread(_delete)

    async def head(self, path: str) -> StoredObject | None:
        def _head() -> StoredObject | None:
            try:
                response = self._client.head_object(Bucket=self._bucket, Key=path)
            except ClientError as error:
                if _is_missing(error):
                    return None
                raise
            return StoredObject(
                path=path,
                content_type=response.get("ContentType", "application/octet-stream"),
                size_bytes=int(response.get("ContentLength", 0)),
            )

        return await asyncio.to_thread(_head)

    # ---------------------------------------------------------------------- setup

    async def ensure_bucket(self) -> None:
        """Create the bucket if it is missing.

        For local development against a fresh MinIO volume, where nothing else would
        create it. A production deployment provisions its container out of band and this
        is a no-op, which is why a failure here is logged rather than raised: an
        unprivileged production credential is *expected* to be refused.
        """

        def _ensure() -> None:
            try:
                self._client.head_bucket(Bucket=self._bucket)
                return
            except ClientError as error:
                if not _is_missing(error) and error.response.get("Error", {}).get("Code") != "403":
                    raise
            try:
                self._client.create_bucket(Bucket=self._bucket)
            except ClientError as error:  # pragma: no cover - depends on credentials
                logger.warning("bucket_not_created", bucket=self._bucket, error=str(error))

        await asyncio.to_thread(_ensure)


def _is_missing(error: ClientError) -> bool:
    code = str(error.response.get("Error", {}).get("Code", ""))
    status = error.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
    return code in _MISSING_CODES or status == 404
