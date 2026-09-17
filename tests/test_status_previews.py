import struct
import unittest

from app.api.status import _parse_binary_preview


class StatusPreviewTests(unittest.TestCase):
    def test_legacy_jpeg_preview(self):
        image = b"\xff\xd8\xffjpeg"
        frame = struct.pack(">II", 1, 1) + image
        self.assertEqual(_parse_binary_preview(frame), (image, "image/jpeg"))

    def test_legacy_png_preview(self):
        image = b"\x89PNG\r\n\x1a\nrest"
        frame = struct.pack(">II", 1, 2) + image
        self.assertEqual(_parse_binary_preview(frame), (image, "image/png"))

    def test_metadata_preview_strips_metadata_before_image(self):
        metadata = b'{"node_id":"756"}'
        image = b"\xff\xd8\xffjpeg"
        frame = struct.pack(">II", 4, len(metadata)) + metadata + image
        self.assertEqual(_parse_binary_preview(frame), (image, "image/jpeg"))

    def test_non_preview_binary_event_is_ignored(self):
        frame = struct.pack(">II", 3, 4) + b"text"
        self.assertIsNone(_parse_binary_preview(frame))

    def test_malformed_metadata_preview_is_ignored(self):
        frame = struct.pack(">II", 4, 999) + b'{}'
        self.assertIsNone(_parse_binary_preview(frame))


if __name__ == "__main__":
    unittest.main()
