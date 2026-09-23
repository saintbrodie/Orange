import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.core import managed_runtime
from app.core import workflow_install_jobs as jobs
from app.core import workflow_install_runner as runner
from app.core import workflow_install_support as support


class ReleasePolishTests(unittest.TestCase):
    def test_curated_manifests_point_to_real_local_thumbnails(self):
        root = Path(__file__).resolve().parents[1]
        expected = {
            "z-image-turbo": "z-image-turbo.webp",
            "seedvr2-7b-upscale": "seedvr2-7b-upscale.webp",
        }
        for pack_id, filename in expected.items():
            manifest = json.loads((root / "workflow-packs" / pack_id / "manifest.json").read_text())
            self.assertEqual(manifest["thumbnail"], f"/static/curated-thumbnails/{filename}")
            data = (root / "static" / "curated-thumbnails" / filename).read_bytes()
            self.assertGreater(len(data), 1000)
            self.assertEqual(data[:4], b"RIFF")
            self.assertEqual(data[8:12], b"WEBP")

    def test_download_summary_and_disk_guard(self):
        plan = [
            {"filename": "a.safetensors", "bytesTotal": 2_000_000_000},
            {"filename": "b.safetensors", "bytesTotal": 3_000_000_000},
        ]
        with mock.patch.object(
            support,
            "disk_space",
            return_value={"path": "/models", "totalBytes": 10_000_000_000, "usedBytes": 5_000_000_000, "freeBytes": 5_000_000_000},
        ):
            result = support.space_requirement(plan, "/models")
        self.assertEqual(result["downloadFileCount"], 2)
        self.assertEqual(result["downloadBytesTotal"], 5_000_000_000)
        self.assertTrue(result["downloadSizeComplete"])
        self.assertTrue(result["insufficientDiskSpace"])

    def test_cancel_retry_and_clear_history_preserve_active_jobs(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(jobs, "JOBS_DIR", tmp), mock.patch.object(jobs, "JOBS_PATH", os.path.join(tmp, "jobs.json")):
                jobs._jobs = {}
                jobs._loaded = True
                first, _ = jobs.create_job("z-image-turbo", "http://127.0.0.1:8188")
                second, _ = jobs.create_job("krea-2-turbo", "http://127.0.0.1:8188")
                jobs.mark_running(first["id"])
                requested = jobs.request_cancel(first["id"])
                self.assertTrue(requested["cancelRequested"])
                canceled = jobs.cancel_job(first["id"])
                self.assertEqual(canceled["state"], "canceled")
                retried, created = jobs.retry_job(first["id"])
                self.assertTrue(created)
                self.assertEqual(retried["state"], "queued")
                removed = jobs.clear_jobs("http://127.0.0.1:8188")
                self.assertEqual(removed, 1)
                remaining = {item["id"] for item in jobs.list_jobs()}
                self.assertIn(second["id"], remaining)
                self.assertIn(retried["id"], remaining)
            jobs._jobs = {}
            jobs._loaded = False

    def test_runner_honors_cancel_before_network_access(self):
        with mock.patch.object(runner, "is_cancel_requested", return_value=True), mock.patch("urllib.request.urlopen") as urlopen:
            with self.assertRaises(runner.InstallCancelled):
                runner._download_with_progress("https://example.test/model", "/tmp/model.safetensors", "job", "model.safetensors")
        urlopen.assert_not_called()

    def test_managed_runtime_status_exposes_dates_and_recovery_flags(self):
        manifest = {"comfyui": {"testedCommit": "tested-sha", "testedDate": "2026-09-17"}}
        state = {"previousCommit": "previous-sha", "channel": "latest", "validation": "failed", "tools": []}
        dates = {
            "current-sha": "2026-09-23T12:00:00+00:00",
            "tested-sha": "2026-09-17T12:00:00+00:00",
            "previous-sha": "2026-09-20T12:00:00+00:00",
        }
        with mock.patch.object(managed_runtime, "load_managed_runtime_manifest", return_value=manifest), \
             mock.patch.object(managed_runtime, "_comfyui_dir", return_value="/fake/comfy"), \
             mock.patch.object(managed_runtime, "_read_state", return_value=state), \
             mock.patch.object(managed_runtime, "_git_head", return_value="current-sha"), \
             mock.patch.object(managed_runtime, "_git_commit_date", side_effect=lambda _repo, ref: dates.get(ref)):
            status = managed_runtime.managed_runtime_status()
        self.assertEqual(status["channel"], "latest")
        self.assertEqual(status["currentCommitDate"], dates["current-sha"])
        self.assertTrue(status["canRollback"])
        self.assertTrue(status["returnToTestedAvailable"])


if __name__ == "__main__":
    unittest.main()
