import unittest
from unittest.mock import AsyncMock, Mock, patch

from app.api import admin


class VideoGalleryTests(unittest.IsolatedAsyncioTestCase):
    async def test_save_video_under_images_is_a_video_card(self):
        response = Mock(status_code=200)
        response.json.return_value = {"ltx-job": {"outputs": {
            "75": {"images": [{"filename": "ltx.mp4", "type": "output", "subfolder": "Orange"}]},
        }}}
        client = AsyncMock()
        client.__aenter__.return_value = client
        client.get.return_value = response
        with patch.object(admin, "get_comfy_servers", return_value=[{"url": "http://comfy"}]), \
             patch.object(admin.httpx, "AsyncClient", return_value=client), \
             patch.object(admin.sqlite3, "connect", side_effect=OSError("no usage database")):
            result = await admin.get_admin_media(_=True)
        self.assertEqual(result["media"], [{
            "prompt_id": "ltx-job", "filename": "ltx.mp4", "type": "video", "analytics": None,
        }])

    async def test_animated_image_is_not_duplicated_as_video(self):
        response = Mock(status_code=200)
        response.json.return_value = {"gif-job": {"outputs": {
            "1": {"gifs": [{"filename": "animation.gif"}]},
        }}}
        client = AsyncMock()
        client.__aenter__.return_value = client
        client.get.return_value = response
        with patch.object(admin, "get_comfy_servers", return_value=[{"url": "http://comfy"}]), \
             patch.object(admin.httpx, "AsyncClient", return_value=client), \
             patch.object(admin.sqlite3, "connect", side_effect=OSError("no usage database")):
            result = await admin.get_admin_media(_=True)
        self.assertEqual(len(result["media"]), 1)
        self.assertEqual(result["media"][0]["type"], "image")
