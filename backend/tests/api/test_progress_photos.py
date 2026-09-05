"""Progress photos, end to end.

The whole feature is built around one rule: a photo must not be readable until its
metadata has been proven gone. Most of what is below is that rule seen from different
angles — a pending photo has no URL, a failed photo has no URL, a photo belonging to
someone else is not found at all.

The bytes never go through the API, so the tests do what the client does: ask for a
credential, write the object into storage directly, then call `complete`. The storage
double is in `tests/fakes.py`; the image processor is the real one, because the EXIF
strip is the one thing here that must never be a double.
"""

from __future__ import annotations

import io
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from PIL import Image

from tests.api.conftest import auth_header, register_and_verify
from tests.fakes import CapturingEmailSender, InMemoryObjectStorage

pytestmark = pytest.mark.integration


@pytest.fixture
async def headers(client: AsyncClient, email_sender: CapturingEmailSender) -> dict[str, str]:
    return auth_header(await register_and_verify(client, email_sender))


def days_ago(count: int) -> str:
    return (datetime.now(UTC).date() - timedelta(days=count)).isoformat()


def photo_bytes(*, width: int = 900, height: int = 1200, with_gps: bool = True) -> bytes:
    """A JPEG that carries GPS coordinates, the way a phone leaves one."""
    image = Image.new("RGB", (width, height), (140, 110, 90))
    exif = image.getexif()
    exif[0x0110] = "iPhone 17 Pro"
    if with_gps:
        gps = exif.get_ifd(0x8825)
        gps[1] = "N"
        gps[2] = (37.0, 58.0, 34.0)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=90, exif=exif)
    return buffer.getvalue()


async def upload(
    client: AsyncClient,
    headers: dict[str, str],
    storage: InMemoryObjectStorage,
    *,
    data: bytes | None = None,
    complete: bool = True,
    **body,
) -> dict:
    """The three-step client flow, as one helper."""
    payload = {"contentType": "image/jpeg", **body}
    intent = await client.post("/v1/progress/photos/upload-intent", json=payload, headers=headers)
    assert intent.status_code == 201, intent.text
    reserved = intent.json()

    # What the direct upload would have written. The path is derived the same way the
    # server derives it, which is also a check that the key is user-partitioned.
    path = next(key for key in _pending_paths(storage, reserved["photoId"]))
    storage.put(path, data if data is not None else photo_bytes())

    if not complete:
        return reserved

    finished = await client.post(
        f"/v1/progress/photos/{reserved['photoId']}/complete", headers=headers
    )
    assert finished.status_code == 200, finished.text
    return finished.json()


def _pending_paths(storage: InMemoryObjectStorage, photo_id: str) -> list[str]:
    """The object key the upload URL was issued for."""
    return [
        url.split("/upload/")[1].split("?")[0] for url in storage.upload_urls if photo_id in url
    ]


class TestUploadIntent:
    async def test_it_returns_a_credential_and_an_expiry(
        self, client: AsyncClient, headers: dict[str, str]
    ) -> None:
        response = await client.post(
            "/v1/progress/photos/upload-intent",
            json={"contentType": "image/jpeg", "pose": "front"},
            headers=headers,
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["uploadUrl"]
        assert body["maxBytes"] == 15 * 1024 * 1024
        assert body["requiredContentType"] == "image/jpeg"
        assert datetime.fromisoformat(body["expiresAt"]) > datetime.now(UTC)

        # A form POST rather than a PUT, so the size limit is a condition of the signed
        # policy and storage refuses an oversized body itself. Whether a real server
        # accepts these fields is proved in tests/integration/test_object_storage.py —
        # a double cannot answer that, and the first version of this endpoint was one
        # that no client could have used.
        assert body["fields"], "the credential must carry policy fields to post back"

    async def test_the_object_key_is_partitioned_by_user(
        self,
        client: AsyncClient,
        headers: dict[str, str],
        photo_storage: InMemoryObjectStorage,
        email_sender: CapturingEmailSender,
    ) -> None:
        """Two accounts must not be able to land in the same prefix.

        The user id leads the key so a storage-level prefix policy can scope access per
        account, and so an accidental listing cannot enumerate across them.
        """
        await client.post(
            "/v1/progress/photos/upload-intent",
            json={"contentType": "image/jpeg"},
            headers=headers,
        )
        other = auth_header(
            await register_and_verify(client, email_sender, email="second@example.com")
        )
        await client.post(
            "/v1/progress/photos/upload-intent", json={"contentType": "image/jpeg"}, headers=other
        )

        prefixes = {url.split("/upload/")[1].split("/")[1] for url in photo_storage.upload_urls}
        assert len(prefixes) == 2

    async def test_an_unsupported_type_is_refused(
        self, client: AsyncClient, headers: dict[str, str]
    ) -> None:
        response = await client.post(
            "/v1/progress/photos/upload-intent",
            json={"contentType": "application/pdf"},
            headers=headers,
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "validation_error"

    async def test_a_future_date_is_refused(
        self, client: AsyncClient, headers: dict[str, str]
    ) -> None:
        tomorrow = (datetime.now(UTC).date() + timedelta(days=1)).isoformat()
        response = await client.post(
            "/v1/progress/photos/upload-intent",
            json={"contentType": "image/jpeg", "localDate": tomorrow},
            headers=headers,
        )
        assert response.status_code == 400

    async def test_the_daily_cap_is_enforced(
        self, client: AsyncClient, headers: dict[str, str]
    ) -> None:
        # Twelve is generous for three poses morning and evening; forty in an afternoon
        # is a script, and every object is storage that is never reclaimed.
        for _ in range(12):
            response = await client.post(
                "/v1/progress/photos/upload-intent",
                json={"contentType": "image/jpeg"},
                headers=headers,
            )
            assert response.status_code == 201

        refused = await client.post(
            "/v1/progress/photos/upload-intent",
            json={"contentType": "image/jpeg"},
            headers=headers,
        )
        assert refused.status_code == 409

    async def test_it_snapshots_the_weight_for_that_day(
        self, client: AsyncClient, headers: dict[str, str], photo_storage: InMemoryObjectStorage
    ) -> None:
        """So a comparison can show 78.2 → 75.6 without a temporal join.

        Snapshotted rather than joined at read time, which also means correcting a weight
        log later does not silently rewrite what a photo was taken at.
        """
        await client.post("/v1/progress/weight", json={"weightKg": "81.40"}, headers=headers)
        photo = await upload(client, headers, photo_storage)
        assert photo["weightAtCaptureKg"] == "81.40"


class TestProcessing:
    async def test_a_completed_photo_is_readable_and_stripped(
        self, client: AsyncClient, headers: dict[str, str], photo_storage: InMemoryObjectStorage
    ) -> None:
        photo = await upload(client, headers, photo_storage)

        assert photo["isReady"] is True
        assert photo["processingStatus"] == "ready"
        assert photo["url"]

        stored, _ = photo_storage.objects[
            next(k for k in photo_storage.objects if not k.endswith("_thumb.jpg"))
        ]
        # The bytes in storage are the sanitised ones. The original, GPS and all, has
        # been overwritten rather than left beside the clean copy.
        assert b"iPhone 17 Pro" not in stored
        assert b"GPS" not in stored

    async def test_a_thumbnail_is_written(
        self, client: AsyncClient, headers: dict[str, str], photo_storage: InMemoryObjectStorage
    ) -> None:
        photo = await upload(client, headers, photo_storage)
        assert photo["thumbnailUrl"]
        assert any(key.endswith("_thumb.jpg") for key in photo_storage.objects)

    async def test_a_pending_photo_has_no_url(
        self, client: AsyncClient, headers: dict[str, str], photo_storage: InMemoryObjectStorage
    ) -> None:
        """The rule, stated directly.

        A photo that has not been through the strip still carries its original EXIF, so
        handing out a URL for it would publish the location it was taken.
        """
        await upload(client, headers, photo_storage, complete=False)

        listed = await client.get("/v1/progress/photos", headers=headers)
        assert listed.status_code == 200
        [photo] = listed.json()
        assert photo["processingStatus"] == "pending"
        assert photo["isReady"] is False
        assert photo["url"] is None
        assert photo["thumbnailUrl"] is None

    async def test_completing_twice_is_a_no_op(
        self, client: AsyncClient, headers: dict[str, str], photo_storage: InMemoryObjectStorage
    ) -> None:
        # A retried task and an impatient client both do this.
        first = await upload(client, headers, photo_storage)
        again = await client.post(f"/v1/progress/photos/{first['id']}/complete", headers=headers)
        assert again.status_code == 200
        assert again.json()["id"] == first["id"]
        assert again.json()["isReady"] is True

    async def test_completing_without_an_upload_is_a_conflict(
        self, client: AsyncClient, headers: dict[str, str]
    ) -> None:
        intent = await client.post(
            "/v1/progress/photos/upload-intent",
            json={"contentType": "image/jpeg"},
            headers=headers,
        )
        response = await client.post(
            f"/v1/progress/photos/{intent.json()['photoId']}/complete", headers=headers
        )
        assert response.status_code == 409

    async def test_a_corrupt_upload_leaves_the_photo_unreadable(
        self, client: AsyncClient, headers: dict[str, str], photo_storage: InMemoryObjectStorage
    ) -> None:
        """The fallback that matters.

        Whatever goes wrong in processing, the outcome must be "this photo never
        appears", never "this photo appears with its original EXIF".
        """
        reserved = await upload(
            client, headers, photo_storage, data=b"not an image at all", complete=False
        )
        failed = await client.post(
            f"/v1/progress/photos/{reserved['photoId']}/complete", headers=headers
        )
        assert failed.status_code == 400

        listed = await client.get("/v1/progress/photos", headers=headers)
        [photo] = listed.json()
        assert photo["processingStatus"] == "failed"
        assert photo["isReady"] is False
        assert photo["url"] is None

    async def test_a_photo_without_metadata_still_processes(
        self, client: AsyncClient, headers: dict[str, str], photo_storage: InMemoryObjectStorage
    ) -> None:
        # Plenty of images have no EXIF. That is not a reason to refuse them.
        photo = await upload(client, headers, photo_storage, data=photo_bytes(with_gps=False))
        assert photo["isReady"] is True


class TestTimeline:
    async def test_photos_are_listed_newest_first(
        self, client: AsyncClient, headers: dict[str, str], photo_storage: InMemoryObjectStorage
    ) -> None:
        await upload(client, headers, photo_storage, localDate=days_ago(10))
        await upload(client, headers, photo_storage, localDate=days_ago(2))

        listed = (await client.get("/v1/progress/photos", headers=headers)).json()
        assert [p["localDate"] for p in listed] == [days_ago(2), days_ago(10)]

    async def test_it_filters_by_pose(
        self, client: AsyncClient, headers: dict[str, str], photo_storage: InMemoryObjectStorage
    ) -> None:
        await upload(client, headers, photo_storage, pose="front")
        await upload(client, headers, photo_storage, pose="back")

        listed = (
            await client.get("/v1/progress/photos", params={"pose": "back"}, headers=headers)
        ).json()
        assert [p["pose"] for p in listed] == ["back"]

    async def test_read_urls_expire(
        self, client: AsyncClient, headers: dict[str, str], photo_storage: InMemoryObjectStorage
    ) -> None:
        """Minted per request, never stored.

        So a response body that ends up in a log or a cache stops being useful within
        minutes rather than staying a live link to somebody's photo.
        """
        await upload(client, headers, photo_storage)
        [photo] = (await client.get("/v1/progress/photos", headers=headers)).json()

        expires = datetime.fromisoformat(photo["urlExpiresAt"])
        assert expires > datetime.now(UTC)
        assert expires < datetime.now(UTC) + timedelta(hours=1)

    async def test_one_users_photos_are_invisible_to_another(
        self,
        client: AsyncClient,
        headers: dict[str, str],
        photo_storage: InMemoryObjectStorage,
        email_sender: CapturingEmailSender,
    ) -> None:
        """Cross-account access here is a page-immediately incident (docs/11 §7)."""
        mine = await upload(client, headers, photo_storage)

        intruder = auth_header(
            await register_and_verify(client, email_sender, email="intruder@example.com")
        )
        assert (await client.get("/v1/progress/photos", headers=intruder)).json() == []

        # Not 403, which would confirm the id exists. The repository has no method that
        # can return another user's row at all.
        stolen = await client.delete(f"/v1/progress/photos/{mine['id']}", headers=intruder)
        assert stolen.status_code == 404

    async def test_it_requires_authentication(self, client: AsyncClient) -> None:
        assert (await client.get("/v1/progress/photos")).status_code == 401


class TestComparison:
    async def test_it_returns_both_sides_with_the_days_between(
        self, client: AsyncClient, headers: dict[str, str], photo_storage: InMemoryObjectStorage
    ) -> None:
        earlier = await upload(client, headers, photo_storage, localDate=days_ago(30))
        later = await upload(client, headers, photo_storage, localDate=days_ago(2))

        response = await client.get(
            "/v1/progress/photos/compare",
            params={"first": earlier["id"], "second": later["id"]},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["daysBetween"] == 28
        assert body["earlier"]["url"] and body["later"]["url"]

    async def test_the_order_asked_for_does_not_matter(
        self, client: AsyncClient, headers: dict[str, str], photo_storage: InMemoryObjectStorage
    ) -> None:
        """A slider should always run the way time does."""
        earlier = await upload(client, headers, photo_storage, localDate=days_ago(30))
        later = await upload(client, headers, photo_storage, localDate=days_ago(2))

        response = await client.get(
            "/v1/progress/photos/compare",
            params={"first": later["id"], "second": earlier["id"]},
            headers=headers,
        )
        assert response.json()["earlier"]["id"] == earlier["id"]

    async def test_it_reports_a_pose_mismatch(
        self, client: AsyncClient, headers: dict[str, str], photo_storage: InMemoryObjectStorage
    ) -> None:
        # Comparing a front shot to a back shot tells the user nothing, so the client is
        # told rather than left to work it out.
        front = await upload(client, headers, photo_storage, pose="front", localDate=days_ago(9))
        back = await upload(client, headers, photo_storage, pose="back", localDate=days_ago(1))

        response = await client.get(
            "/v1/progress/photos/compare",
            params={"first": front["id"], "second": back["id"]},
            headers=headers,
        )
        assert response.json()["posesMatch"] is False

    async def test_it_carries_the_weight_delta(
        self, client: AsyncClient, headers: dict[str, str], photo_storage: InMemoryObjectStorage
    ) -> None:
        await client.post(
            "/v1/progress/weight",
            json={"weightKg": "82.00", "localDate": days_ago(30)},
            headers=headers,
        )
        earlier = await upload(client, headers, photo_storage, localDate=days_ago(30))
        await client.post(
            "/v1/progress/weight",
            json={"weightKg": "79.50", "localDate": days_ago(2)},
            headers=headers,
        )
        later = await upload(client, headers, photo_storage, localDate=days_ago(2))

        response = await client.get(
            "/v1/progress/photos/compare",
            params={"first": earlier["id"], "second": later["id"]},
            headers=headers,
        )
        assert response.json()["weightDeltaKg"] == "-2.50"

    async def test_comparing_a_photo_with_itself_is_refused(
        self, client: AsyncClient, headers: dict[str, str], photo_storage: InMemoryObjectStorage
    ) -> None:
        photo = await upload(client, headers, photo_storage)
        response = await client.get(
            "/v1/progress/photos/compare",
            params={"first": photo["id"], "second": photo["id"]},
            headers=headers,
        )
        assert response.status_code == 400

    async def test_comparing_a_pending_photo_is_refused(
        self, client: AsyncClient, headers: dict[str, str], photo_storage: InMemoryObjectStorage
    ) -> None:
        """Rather than returning one side with a URL and the other without.

        A half-rendered comparison is exactly where a client falls back to showing
        something it should not.
        """
        ready = await upload(client, headers, photo_storage, localDate=days_ago(5))
        pending = await upload(client, headers, photo_storage, complete=False)

        response = await client.get(
            "/v1/progress/photos/compare",
            params={"first": ready["id"], "second": pending["photoId"]},
            headers=headers,
        )
        assert response.status_code == 409


class TestDeletion:
    async def test_the_bytes_are_removed_from_storage(
        self, client: AsyncClient, headers: dict[str, str], photo_storage: InMemoryObjectStorage
    ) -> None:
        """'Delete my photo' has to mean the file is gone.

        The row is soft-deleted for the audit trail the schema assumes, but a soft delete
        that left the object retrievable by anyone holding a signed URL would not be a
        deletion in any sense the user means.
        """
        photo = await upload(client, headers, photo_storage)
        assert photo_storage.objects

        response = await client.delete(f"/v1/progress/photos/{photo['id']}", headers=headers)
        assert response.status_code == 204

        assert photo_storage.objects == {}
        assert len(photo_storage.deleted) == 2  # the image and its thumbnail

    async def test_a_deleted_photo_leaves_the_timeline(
        self, client: AsyncClient, headers: dict[str, str], photo_storage: InMemoryObjectStorage
    ) -> None:
        photo = await upload(client, headers, photo_storage)
        await client.delete(f"/v1/progress/photos/{photo['id']}", headers=headers)
        assert (await client.get("/v1/progress/photos", headers=headers)).json() == []

    async def test_deleting_a_photo_that_is_not_there(
        self, client: AsyncClient, headers: dict[str, str]
    ) -> None:
        response = await client.delete(
            "/v1/progress/photos/0199a0f0-0000-7000-8000-000000000000", headers=headers
        )
        assert response.status_code == 404
