"""The EXIF strip.

This is the test that the progress-photo feature exists or does not exist on. A progress
photo routinely carries the GPS coordinates of somebody's home; docs/11 §5 makes removing
that a precondition of the photo ever being readable, and the only way to know it happens
is to build a file that *has* the metadata and check it is gone afterwards.

Nothing here uses a fixture image on disk. The photos are generated with the exact tags
the test is about, so a reader can see what is being removed without opening a binary.
"""

from __future__ import annotations

import io

import pytest
from PIL import Image

from coresync.infrastructure.storage.images import (
    MAX_EDGE_PX,
    THUMBNAIL_EDGE_PX,
    PillowImageProcessor,
)

# EXIF tag numbers, spelled out rather than imported from a helper library so the test
# stays readable and adds no dependency of its own.
_MAKE = 0x010F
_MODEL = 0x0110
_ORIENTATION = 0x0112
_EXIF_IFD = 0x8769
_GPS_IFD = 0x8825
_DATETIME_ORIGINAL = 0x9003
_BODY_SERIAL = 0xA431
_GPS_LAT_REF = 1
_GPS_LAT = 2
_GPS_LON_REF = 3
_GPS_LON = 4


def _jpeg(
    width: int = 1200, height: int = 800, colour: tuple[int, int, int] = (120, 90, 60)
) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), colour).save(buffer, format="JPEG", quality=90)
    return buffer.getvalue()


def _photo_with_exif(*, orientation: int = 1, width: int = 1200, height: int = 800) -> bytes:
    """A JPEG carrying GPS, a device make/model and a capture time — a phone photo."""
    image = Image.new("RGB", (width, height), (120, 90, 60))

    exif = image.getexif()
    exif[_MAKE] = "Apple"
    exif[_MODEL] = "iPhone 17 Pro"
    exif[_ORIENTATION] = orientation

    exif.get_ifd(_EXIF_IFD)[_DATETIME_ORIGINAL] = "2026:08:27 07:41:03"
    exif.get_ifd(_EXIF_IFD)[_BODY_SERIAL] = "F2LX9K3QJ1M4"

    gps = exif.get_ifd(_GPS_IFD)
    gps[_GPS_LAT_REF] = "N"
    # 37° 58' 34" N, 23° 43' 58" E — central Athens. Degrees, minutes and seconds as
    # floats: Pillow turns each into a TIFF rational itself, and hands a raw tuple
    # straight to `abs()`, which fails.
    gps[_GPS_LAT] = (37.0, 58.0, 34.0)
    gps[_GPS_LON_REF] = "E"
    gps[_GPS_LON] = (23.0, 43.0, 58.0)

    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=90, exif=exif)
    return buffer.getvalue()


def _read_exif(data: bytes) -> dict:
    with Image.open(io.BytesIO(data)) as image:
        return dict(image.getexif())


class TestMetadataRemoval:
    def test_the_fixture_actually_has_metadata(self) -> None:
        """Guards the rest of this file.

        Every assertion below is 'the metadata is gone'. If the input never had any, all
        of them pass for the wrong reason and the strip could be a no-op forever.
        """
        raw = _photo_with_exif()
        assert _read_exif(raw), "test input carries no EXIF, so nothing below proves anything"
        assert b"iPhone 17 Pro" in raw

    def test_gps_is_gone(self) -> None:
        processed = PillowImageProcessor().process(_photo_with_exif())
        # The most important line in the suite. A progress photo with these coordinates
        # in it is the inside of somebody's home, published.
        assert b"GPS" not in processed.image
        assert not _read_exif(processed.image)

    def test_device_identifiers_are_gone(self) -> None:
        processed = PillowImageProcessor().process(_photo_with_exif())
        assert b"iPhone 17 Pro" not in processed.image
        assert b"F2LX9K3QJ1M4" not in processed.image
        assert b"Apple" not in processed.image

    def test_capture_timestamp_is_gone(self) -> None:
        processed = PillowImageProcessor().process(_photo_with_exif())
        assert b"2026:08:27" not in processed.image

    def test_the_thumbnail_is_stripped_too(self) -> None:
        """The thumbnail is a separate file and gets served separately.

        An easy thing to miss: strip the original, generate the thumbnail from the
        pre-strip image, and ship the coordinates in the small one instead.
        """
        processed = PillowImageProcessor().process(_photo_with_exif())
        assert not _read_exif(processed.thumbnail)
        assert b"GPS" not in processed.thumbnail

    def test_it_reports_that_there_was_something_to_remove(self) -> None:
        assert PillowImageProcessor().process(_photo_with_exif()).had_metadata is True

    def test_a_clean_photo_is_reported_as_clean(self) -> None:
        # Not an error, and not a reason to refuse the photo — plenty of images have no
        # EXIF at all. The flag exists to make the log line honest.
        assert PillowImageProcessor().process(_jpeg()).had_metadata is False

    def test_metadata_removed_is_always_true_on_success(self) -> None:
        # The use case only marks a photo readable on a successful return, so this flag
        # can never be False in a result that exists. It is asserted rather than assumed
        # because the domain's `exif_stripped_at` is set on the strength of it.
        assert PillowImageProcessor().process(_photo_with_exif()).metadata_removed is True

    def test_xmp_is_gone(self) -> None:
        """XMP is a second metadata container, and stripping EXIF alone leaves it.

        Written into the JPEG as an APP1 segment the way Adobe tools do.
        """
        base = _jpeg()
        xmp = (
            b'<?xpacket begin="\xef\xbb\xbf"?><x:xmpmeta xmlns:x="adobe:ns:meta/">'
            b'<rdf:RDF><rdf:Description photoshop:City="Athens"/></rdf:RDF>'
            b'</x:xmpmeta><?xpacket end="w"?>'
        )
        segment = (
            b"\xff\xe1"
            + (len(xmp) + 2 + 29).to_bytes(2, "big")
            + b"http://ns.adobe.com/xap/1.0/\x00"
            + xmp
        )
        with_xmp = base[:2] + segment + base[2:]

        processed = PillowImageProcessor().process(with_xmp)
        assert b"Athens" not in processed.image
        assert b"adobe:ns:meta" not in processed.image


class TestOrientation:
    def test_a_rotated_photo_comes_back_upright(self) -> None:
        """Orientation is applied to the pixels, not preserved as a tag.

        Orientation 6 means "rotate 90° clockwise to display". Keeping the tag would mean
        the strip was not a strip; ignoring it would mean every portrait photo appears on
        its side. So the pixels are rotated and the tag is dropped, and the proof is that
        a landscape source comes back portrait.
        """
        raw = _photo_with_exif(orientation=6, width=1200, height=800)
        processed = PillowImageProcessor().process(raw)
        assert processed.height > processed.width
        assert not _read_exif(processed.image)


class TestResizing:
    def test_a_huge_photo_is_capped(self) -> None:
        processed = PillowImageProcessor().process(_jpeg(6000, 4000))
        assert max(processed.width, processed.height) == MAX_EDGE_PX
        # Aspect ratio preserved, not squashed to a square.
        assert processed.width / processed.height == pytest.approx(1.5, abs=0.01)

    def test_a_small_photo_is_left_alone(self) -> None:
        processed = PillowImageProcessor().process(_jpeg(400, 300))
        assert (processed.width, processed.height) == (400, 300)

    def test_the_thumbnail_is_small(self) -> None:
        processed = PillowImageProcessor().process(_jpeg(6000, 4000))
        with Image.open(io.BytesIO(processed.thumbnail)) as thumb:
            assert max(thumb.size) <= THUMBNAIL_EDGE_PX

    def test_an_extreme_aspect_ratio_does_not_collapse_to_zero(self) -> None:
        # 4000x8 scaled to a 400px thumbnail rounds the short edge to 0.8, and Pillow
        # raises on a zero-height image.
        processed = PillowImageProcessor().process(_jpeg(4000, 8))
        with Image.open(io.BytesIO(processed.thumbnail)) as thumb:
            assert thumb.size[1] >= 1


class TestFormats:
    def test_a_png_with_transparency_becomes_a_jpeg_on_white(self) -> None:
        buffer = io.BytesIO()
        Image.new("RGBA", (300, 300), (255, 0, 0, 0)).save(buffer, format="PNG")

        processed = PillowImageProcessor().process(buffer.getvalue())

        assert processed.content_type == "image/jpeg"
        with Image.open(io.BytesIO(processed.image)) as out:
            assert out.mode == "RGB"
            # Composited onto white rather than onto the default black, which would turn
            # a transparent background into a black rectangle.
            assert out.getpixel((150, 150)) == (255, 255, 255)

    def test_a_greyscale_image_is_handled(self) -> None:
        buffer = io.BytesIO()
        Image.new("L", (300, 300), 128).save(buffer, format="JPEG")
        processed = PillowImageProcessor().process(buffer.getvalue())
        assert processed.width == 300

    def test_garbage_is_rejected(self) -> None:
        # The caller turns any exception into a failed photo that never becomes
        # readable, so what matters here is only that it raises rather than returning
        # something that looks like a processed image.
        with pytest.raises(Exception):  # noqa: B017
            PillowImageProcessor().process(b"this is not an image")

    def test_a_truncated_file_is_rejected(self) -> None:
        raw = _jpeg()
        with pytest.raises(Exception):  # noqa: B017
            PillowImageProcessor().process(raw[: len(raw) // 3])


class TestDecompressionBomb:
    def test_a_bomb_is_refused(self) -> None:
        """A small file that decodes to an enormous bitmap.

        The bytes arrive from outside, so this is the one input where a few kilobytes
        can exhaust the process's memory. Pillow warns above its own threshold; the
        module lowers it and makes it fatal.
        """
        buffer = io.BytesIO()
        # 20000x20000 = 400 megapixels, well over the 64 MP ceiling, and it compresses
        # to almost nothing because it is a single flat colour.
        Image.new("RGB", (20000, 20000), (0, 0, 0)).save(buffer, format="JPEG", quality=10)

        with pytest.raises(Image.DecompressionBombError):
            PillowImageProcessor().process(buffer.getvalue())
