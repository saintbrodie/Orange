import io
from typing import Tuple

from PIL import Image


def strip_metadata(image_bytes: bytes) -> Tuple[bytes, str]:
    """Strip metadata while preserving the source image format where practical.

    Returns a tuple of (clean_bytes, media_type).
    """
    with Image.open(io.BytesIO(image_bytes)) as img:
        source_format = (img.format or "PNG").upper()

        # Animated GIF/WebP outputs should be returned untouched rather than
        # accidentally collapsed to a single frame by metadata processing.
        if getattr(img, "is_animated", False) and getattr(img, "n_frames", 1) > 1:
            media_type = "image/gif" if source_format == "GIF" else "image/webp"
            return image_bytes, media_type

        out_io = io.BytesIO()

        if source_format == "JPEG":
            clean = img.convert("RGB")
            clean.save(out_io, format="JPEG", quality=95, optimize=True)
            return out_io.getvalue(), "image/jpeg"

        if source_format == "WEBP":
            clean = img.copy()
            clean.save(out_io, format="WEBP", lossless=True)
            return out_io.getvalue(), "image/webp"

        # Default to PNG so transparency and lossless pixel data are retained.
        clean = img.copy()
        clean.save(out_io, format="PNG")
        return out_io.getvalue(), "image/png"
