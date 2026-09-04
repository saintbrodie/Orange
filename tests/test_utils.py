import io
import unittest

from PIL import Image

from app.core.utils import strip_metadata


class StripMetadataTests(unittest.TestCase):
    def test_png_transparency_is_preserved(self):
        source = io.BytesIO()
        Image.new("RGBA", (4, 4), (255, 0, 0, 64)).save(source, format="PNG", pnginfo=None)

        cleaned, media_type = strip_metadata(source.getvalue())

        self.assertEqual(media_type, "image/png")
        with Image.open(io.BytesIO(cleaned)) as image:
            self.assertEqual(image.format, "PNG")
            self.assertEqual(image.mode, "RGBA")
            self.assertEqual(image.getpixel((0, 0))[3], 64)

    def test_jpeg_remains_jpeg(self):
        source = io.BytesIO()
        Image.new("RGB", (4, 4), (20, 40, 60)).save(source, format="JPEG")

        cleaned, media_type = strip_metadata(source.getvalue())

        self.assertEqual(media_type, "image/jpeg")
        with Image.open(io.BytesIO(cleaned)) as image:
            self.assertEqual(image.format, "JPEG")


if __name__ == "__main__":
    unittest.main()
