import asyncio
import unittest
from unittest import mock

from app.api import workflow_pack_admin


class WorkflowPackJobApiTests(unittest.TestCase):
    def test_start_job_schedules_new_background_install(self):
        payload = {
            "packId": "z-image-turbo",
            "serverUrl": "http://127.0.0.1:8188",
            "modelsRoot": "/models",
        }
        job = {
            "id": "job-1",
            "packId": "z-image-turbo",
            "serverUrl": "http://127.0.0.1:8188",
            "state": "queued",
        }

        async def run_test():
            with mock.patch.object(workflow_pack_admin, "get_workflow_pack", return_value={"id": "z-image-turbo"}), mock.patch.object(
                workflow_pack_admin, "load_config", return_value={"comfyServers": [{"url": "http://127.0.0.1:8188"}]}
            ), mock.patch.object(workflow_pack_admin, "create_job", return_value=(job, True)), mock.patch.object(
                workflow_pack_admin, "_schedule_install_job"
            ) as schedule:
                result = await workflow_pack_admin.start_install_job(payload, _=True)

            self.assertTrue(result["created"])
            self.assertEqual(result["job"]["id"], "job-1")
            schedule.assert_called_once_with("job-1")

        asyncio.run(run_test())

    def test_start_job_reuses_existing_active_job(self):
        payload = {"packId": "krea-2-turbo", "serverUrl": "http://127.0.0.1:8188"}
        job = {
            "id": "job-existing",
            "packId": "krea-2-turbo",
            "serverUrl": "http://127.0.0.1:8188",
            "state": "running",
        }

        async def run_test():
            with mock.patch.object(workflow_pack_admin, "get_workflow_pack", return_value={"id": "krea-2-turbo"}), mock.patch.object(
                workflow_pack_admin, "load_config", return_value={"comfyServers": [{"url": "http://127.0.0.1:8188"}]}
            ), mock.patch.object(workflow_pack_admin, "create_job", return_value=(job, False)), mock.patch.object(
                workflow_pack_admin, "_schedule_install_job"
            ) as schedule:
                result = await workflow_pack_admin.start_install_job(payload, _=True)

            self.assertFalse(result["created"])
            self.assertEqual(result["job"]["id"], "job-existing")
            schedule.assert_not_called()

        asyncio.run(run_test())


if __name__ == "__main__":
    unittest.main()
