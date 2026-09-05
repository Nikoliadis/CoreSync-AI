"""Stripping metadata from an uploaded photo, and making a thumbnail.

A phone stamps a photo with the GPS coordinates it was taken at, the device serial, and
the exact second. For a progress photo that is the inside of someone's home. docs/11 §5
makes removing it a precondition of the photo ever being readable, and the domain
enforces that: ``ProgressPhoto.is_readable`` is false until ``exif_stripped_at`` is set.

**The strip is a re-encode, not a delete.** Pillow is asked to decode the pixels and
write a new file from them, so nothing from the container survives by default — not EXIF,
not XMP, not IPTC, not a maker note in a vendor-specific block, not an embedded thumbnail
that still carries its own EXIF. A field-by-field scrub would have to know every tag that
exists, and would miss whichever one a phone vendor adds next year.

The one thing worth keeping is orientation, and it is applied to the pixels rather than
preserved as a tag: without that a photo taken in portrait comes back rotated, and with
the tag kept the strip would not be a strip.
"""

from __future__ import annotations

import io

from PIL import Image, ImageOps

from coresync.domain.progress.repositories import ProcessedImage

# The longest edge of a stored photo. A progress photo is looked at side by side with
# another one on a phone screen; keeping a 48-megapixel original costs storage and
# bandwidth for detail nobody sees.
MAX_EDGE_PX = 2048
THUMBNAIL_EDGE_PX = 400

# Re-encode quality. High enough that a comparison a year apart is not judging JPEG
# artefacts, low enough that a photo a day does not become a storage problem.
JPEG_QUALITY = 88
THUMBNAIL_QUALITY = 78

# Anything the container carries besides pixels. Checked so the result can *record* that
# there was something to remove rather than assuming the strip did anything.
_METADATA_KEYS = ("exif", "XML:com.adobe.xmp", "icc_profile", "photoshop", "iptc", "comment")

# A decompression bomb is a small file that decodes to a huge bitmap. Pillow warns above
# its own threshold; this makes it an error, because the upload path is unauthenticated
# in the sense that matters here — the bytes come from outside.
Image.MAX_IMAGE_PIXELS = 64_000_000


class MetadataNotRemovedError(RuntimeError):
    """The re-encoded image still carries metadata.

    Raised rather than logged. A photo whose metadata could not be proven gone must not
    become readable, and the caller's failure path leaves it exactly that way.
    """


class PillowImageProcessor:
    """An ``ImageProcessorPort``. CPU-bound and synchronous, called from the worker."""

    def process(self, data: bytes) -> ProcessedImage:
        with Image.open(io.BytesIO(data)) as original:
            had_metadata = _has_metadata(original)

            # Applies the EXIF orientation to the pixels and drops the tag. Done first,
            # so every later step works on an upright image.
            upright = ImageOps.exif_transpose(original) or original

            # Alpha and palette modes cannot be written as JPEG. Composited onto white
            # rather than dropped, so a PNG with transparency does not come back with a
            # black background.
            rgb = _to_rgb(upright)

            full = _resized(rgb, MAX_EDGE_PX)
            thumb = _resized(rgb, THUMBNAIL_EDGE_PX)

            image_bytes = _encode(full, JPEG_QUALITY)
            thumb_bytes = _encode(thumb, THUMBNAIL_QUALITY)
            width, height = full.size

        # Verified, not assumed. If a future Pillow ever carried a tag through the
        # re-encode this is what would catch it, and the photo would stay unreadable.
        if _bytes_have_metadata(image_bytes) or _bytes_have_metadata(thumb_bytes):
            raise MetadataNotRemovedError("re-encoded image still carries metadata")

        return ProcessedImage(
            image=image_bytes,
            thumbnail=thumb_bytes,
            width=width,
            height=height,
            content_type="image/jpeg",
            had_metadata=had_metadata,
            metadata_removed=True,
        )


def _to_rgb(image: Image.Image) -> Image.Image:
    if image.mode == "RGB":
        return image
    if image.mode in ("RGBA", "LA", "P"):
        converted = image.convert("RGBA")
        background = Image.new("RGB", converted.size, (255, 255, 255))
        background.paste(converted, mask=converted.split()[-1])
        return background
    return image.convert("RGB")


def _resized(image: Image.Image, max_edge: int) -> Image.Image:
    width, height = image.size
    longest = max(width, height)
    if longest <= max_edge:
        return image.copy()
    scale = max_edge / longest
    # `max(1, ...)` because a very wide, very short image would otherwise round its
    # short edge to zero and Pillow would raise.
    return image.resize(
        (max(1, round(width * scale)), max(1, round(height * scale))),
        Image.Resampling.LANCZOS,
    )


def _encode(image: Image.Image, quality: int) -> bytes:
    buffer = io.BytesIO()
    # No `exif=` and no `icc_profile=` argument, so Pillow writes neither. This is the
    # strip: a JPEG saved from raw pixels has only what is passed here.
    image.save(buffer, format="JPEG", quality=quality, optimize=True, progressive=True)
    return buffer.getvalue()


def _has_metadata(image: Image.Image) -> bool:
    if getattr(image, "_exif", None):
        return True
    exif = image.getexif()
    if exif is not None and len(exif) > 0:
        return True
    info = getattr(image, "info", {}) or {}
    return any(info.get(key) for key in _METADATA_KEYS)


def _bytes_have_metadata(data: bytes) -> bool:
    with Image.open(io.BytesIO(data)) as image:
        return _has_metadata(image)


__all__ = ["MAX_EDGE_PX", "THUMBNAIL_EDGE_PX", "MetadataNotRemovedError", "PillowImageProcessor"]
