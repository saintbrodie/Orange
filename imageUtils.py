import io
from PIL import Image

def strip_metadata(image_bytes: bytes) -> bytes:
    """
    Strips all metadata, EXIF, and PNG text chunks (where ComfyUI stores workflow/prompt data).
    By loading the image and re-resaving without passing `exif` or `pnginfo`, Pillow automatically omits it.
    """
    img = Image.open(io.BytesIO(image_bytes))
    
    # We enforce conversion to RGB just to be safe if we want a clean output, 
    # but maintaining RGBA for transparency is better unless requested otherwise.
    # We will just save as PNG.
    out_io = io.BytesIO()
    img.save(out_io, format="PNG")
    
    return out_io.getvalue()
