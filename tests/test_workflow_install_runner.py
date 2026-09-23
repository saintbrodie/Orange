import io
import os
import tempfile
import unittest
from unittest import mock

from app.core import workflow_install_runner as runner


class _Response(io.BytesIO):
    def __init__(self, data: bytes):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False


class WorkflowInstallRunnerTests(unittest.TestCase):
    def test_download_reports_bytes_and_completes_atomically(self):
        payload = b"x" * (2 * 1024 * 1024 + 17)
        with tempfile.TemporaryDirectory() as root:
            selected = [
                {
                    "id": "diffusion",
                    "folder": "diffusion_models",
                    "filename": "model.safetensors",
                    "url": "https://example.test/model.safetensors",
                    "precision": "fp8",
                }
            ]
            progress = []

            def record(_job_id, filename, **kwargs):
                progress.append((filename, kwargs))
                return {}

            with mock.patch.object(runner.urllib.request, "urlopen", return_value=_Response(payload)), mock.patch.object(
                runner, "update_file_progress", side_effect=record
            ), mock.patch.object(runner, "get_workflow_pack", return_value={"id": "pack"}), mock.patch.object(
                runner, "materialize_workflow_pack", return_value="/workflow.json"
            ):
                result = runner.install_workflow_pack_job("job-1", "pack", root, {}, selected)

            destination = os.path.join(root, "diffusion_models", "model.safetensors")
            self.assertTrue(os.path.isfile(destination))
            self.assertFalse(os.path.exists(destination + ".part"))
            self.assertEqual(os.path.getsize(destination), len(payload))
            self.assertEqual(result["installed"], [destination])
            self.assertEqual(progress[-1][1]["state"], "completed")
            self.assertEqual(progress[-1][1]["bytesDownloaded"], len(payload))
            self.assertEqual(progress[-1][1]["bytesTotal"], len(payload))


if __name__ == "__main__":
    unittest.main()
