import unittest

from app.core.outputs import collect_media_outputs, extract_text_output, guess_media_type


class OutputHelpersTests(unittest.TestCase):
    def test_collects_multiple_images_in_stable_order(self):
        outputs = {
            "10": {
                "images": [
                    {"filename": "first.png", "subfolder": "", "type": "output"},
                    {"filename": "second.webp", "subfolder": "", "type": "output"},
                ]
            }
        }
        items = collect_media_outputs(outputs, "image")
        self.assertEqual([item["filename"] for item in items], ["first.png", "second.webp"])
        self.assertEqual([item["index"] for item in items], [0, 1])

    def test_video_does_not_fall_back_to_static_image(self):
        outputs = {
            "10": {"images": [{"filename": "preview.png", "type": "output"}]},
            "20": {"video": [{"filename": "final.mp4", "type": "output"}]},
        }
        items = collect_media_outputs(outputs, "video")
        self.assertEqual([item["filename"] for item in items], ["final.mp4"])

    def test_video_accepts_animated_gif_output(self):
        outputs = {"10": {"gifs": [{"filename": "animation.gif", "type": "output"}]}}
        items = collect_media_outputs(outputs, "video")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["media_type"], "image/gif")

    def test_duplicate_media_reference_is_returned_once(self):
        duplicate = {"filename": "same.png", "subfolder": "x", "type": "output"}
        outputs = {"10": {"images": [duplicate], "gifs": [dict(duplicate)]}}
        items = collect_media_outputs(outputs, "image")
        self.assertEqual(len(items), 1)

    def test_extracts_text_from_message_dict(self):
        outputs = {"10": {"messages": [{"content": "hello"}]}}
        self.assertEqual(extract_text_output(outputs), "hello")

    def test_media_type_uses_extension_override(self):
        self.assertEqual(guess_media_type("clip.mkv"), "video/x-matroska")
        self.assertEqual(guess_media_type("sound.m4a"), "audio/mp4")


if __name__ == "__main__":
    unittest.main()
