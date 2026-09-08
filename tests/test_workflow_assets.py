import os
import tempfile
import unittest
from unittest.mock import patch

from app.core import workflow_assets


class WorkflowAssetTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.assets_patch = patch.object(workflow_assets, "ASSETS_ROOT", self.tempdir.name)
        self.assets_patch.start()

    def tearDown(self):
        self.assets_patch.stop()
        self.tempdir.cleanup()

    def _make_asset(self, workflow_file: str, name: str) -> str:
        directory = workflow_assets.asset_directory(workflow_file, create=True)
        path = os.path.join(directory, name)
        with open(path, "wb") as handle:
            handle.write(b"fake-image-bytes")
        return path

    def test_asset_namespaces_do_not_collide_for_different_workflows(self):
        first = workflow_assets.asset_namespace("Foo Bar.json")
        second = workflow_assets.asset_namespace("Foo-Bar.json")
        self.assertNotEqual(first, second)

    def test_asset_name_rejects_path_traversal(self):
        with self.assertRaises(ValueError):
            workflow_assets.safe_asset_name("../reference.png")

    def test_asset_name_rejects_unsupported_extension(self):
        with self.assertRaises(ValueError):
            workflow_assets.safe_asset_name("reference.txt")

    def test_unmapped_static_image_reference_is_discovered(self):
        path = self._make_asset("tool.json", "reference.png")
        workflow = {
            "12": {
                "class_type": "LoadImage",
                "inputs": {"image": "reference.png"},
            }
        }

        refs = workflow_assets.find_managed_asset_references(workflow, {}, "tool.json")

        self.assertEqual(refs, [("12", "image", "reference.png", path)])

    def test_mapped_image_reference_is_not_treated_as_static_asset(self):
        self._make_asset("tool.json", "placeholder.png")
        workflow = {
            "12": {
                "class_type": "LoadImage",
                "inputs": {"image": "placeholder.png"},
            }
        }
        mapping = {"image": {"nodeId": "12", "field": "image"}}

        refs = workflow_assets.find_managed_asset_references(workflow, mapping, "tool.json")

        self.assertEqual(refs, [])

    def test_same_asset_can_feed_multiple_unmapped_nodes(self):
        path = self._make_asset("tool.json", "style.jpg")
        workflow = {
            "1": {"class_type": "LoadImage", "inputs": {"image": "style.jpg"}},
            "2": {"class_type": "LoadImage", "inputs": {"image": "style.jpg"}},
        }

        refs = workflow_assets.find_managed_asset_references(workflow, {}, "tool.json")

        self.assertEqual(
            refs,
            [
                ("1", "image", "style.jpg", path),
                ("2", "image", "style.jpg", path),
            ],
        )


if __name__ == "__main__":
    unittest.main()
