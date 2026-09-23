import unittest
from pathlib import Path

from app.core import workflow_packs


class CuratedThumbnailTests(unittest.TestCase):
    def test_declared_local_thumbnails_exist(self):
        root = Path(__file__).resolve().parents[1]
        thumbnail_packs = []

        for pack in workflow_packs.list_workflow_packs():
            thumbnail = str(pack.get("thumbnail") or "").strip()
            if not thumbnail:
                continue
            self.assertTrue(
                thumbnail.startswith("/static/"),
                f"{pack['id']} thumbnail should be served from Orange static assets",
            )
            local_path = root / thumbnail.removeprefix("/")
            self.assertTrue(local_path.is_file(), f"Missing thumbnail for {pack['id']}: {local_path}")
            self.assertGreater(local_path.stat().st_size, 0, f"Empty thumbnail for {pack['id']}")
            thumbnail_packs.append(pack["id"])

        self.assertEqual(set(thumbnail_packs), {"krea-2-turbo", "klein-9b-edit"})

    def test_imported_thumbnails_are_pngs(self):
        root = Path(__file__).resolve().parents[1]
        png_signature = b"\x89PNG\r\n\x1a\n"
        for filename in ("krea-2-turbo.png", "klein-9b-edit.png"):
            with (root / "static" / "curated-thumbnails" / filename).open("rb") as handle:
                self.assertEqual(handle.read(8), png_signature)


if __name__ == "__main__":
    unittest.main()
