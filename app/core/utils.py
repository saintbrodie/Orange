import io
from PIL import Image

def strip_metadata(image_bytes: bytes) -> bytes:
    """
    Strips all metadata, EXIF, and embedded workflow data by re-saving as JPEG.
    RGB conversion drops any alpha channel. JPEG doesn't support metadata chunks
    so the output is always clean.
    """
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    out_io = io.BytesIO()
    img.save(out_io, format="JPEG", quality=92)
    return out_io.getvalue()
