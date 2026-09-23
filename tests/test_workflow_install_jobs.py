import json
import os
import tempfile
import unittest
from unittest import mock

from app.core import workflow_install_jobs as jobs


class WorkflowInstallJobTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.jobs_dir = os.path.join(self.tempdir.name, ".runtime")
        self.jobs_path = os.path.join(self.jobs_dir, "workflow-install-jobs.json")
        self.patch_dir = mock.patch.object(jobs, "JOBS_DIR", self.jobs_dir)
        self.patch_path = mock.patch.object(jobs, "JOBS_PATH", self.jobs_path)
        self.patch_dir.start()
        self.patch_path.start()
        jobs._jobs = {}
        jobs._loaded = False

    def tearDown(self):
        self.patch_path.stop()
        self.patch_dir.stop()
        self.tempdir.cleanup()
        jobs._jobs = {}
        jobs._loaded = False

    def test_duplicate_active_install_returns_existing_job(self):
        first, created_first = jobs.create_job("krea-2-turbo", "http://127.0.0.1:8188/", "/models")
        jobs.mark_running(first["id"], stage="downloading", message="Downloading")
        second, created_second = jobs.create_job("krea-2-turbo", "http://127.0.0.1:8188", "/models")

        self.assertTrue(created_first)
        self.assertFalse(created_second)
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(len(jobs.list_jobs()), 1)

    def test_file_progress_is_persisted(self):
        job, _ = jobs.create_job("z-image-turbo", "http://127.0.0.1:8188", "/models")
        jobs.set_download_plan(
            job["id"],
            [{"filename": "model.safetensors", "folder": "diffusion_models", "destination": "/models/model.safetensors"}],
        )
        jobs.update_file_progress(
            job["id"],
            "model.safetensors",
            state="downloading",
            bytes_downloaded=50,
            bytes_total=100,
            speed_bps=25,
        )

        with open(self.jobs_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        stored = payload["jobs"][0]["files"][0]
        self.assertEqual(stored["bytesDownloaded"], 50)
        self.assertEqual(stored["bytesTotal"], 100)
        self.assertEqual(stored["speedBps"], 25.0)

    def test_active_job_becomes_interrupted_after_process_reload(self):
        job, _ = jobs.create_job("seedvr2-7b-upscale", "http://127.0.0.1:8188", "/models")
        jobs.mark_running(job["id"], stage="downloading", message="Downloading")

        jobs._jobs = {}
        jobs._loaded = False
        recovered = jobs.get_job(job["id"])

        self.assertEqual(recovered["state"], "interrupted")
        self.assertEqual(recovered["stage"], "interrupted")
        self.assertIn("restarted", recovered["error"].lower())

    def test_retry_creates_new_job_after_failure(self):
        job, _ = jobs.create_job("klein-9b-edit", "http://127.0.0.1:8188", "/models")
        jobs.fail_job(job["id"], "network error", stage="downloading")

        retried, created = jobs.retry_job(job["id"])

        self.assertTrue(created)
        self.assertNotEqual(retried["id"], job["id"])
        self.assertEqual(retried["state"], "queued")
        self.assertEqual(retried["modelsRoot"], "/models")


if __name__ == "__main__":
    unittest.main()
