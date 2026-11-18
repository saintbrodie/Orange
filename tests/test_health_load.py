import unittest
from unittest.mock import AsyncMock, patch

import httpx

from app.api import status


class HealthLoadTests(unittest.IsolatedAsyncioTestCase):
    async def health(self, pending, unavailable=()):
        def transport(request):
            host = request.url.host
            if host in unavailable:
                return httpx.Response(503)
            if request.url.path == '/system_stats':
                return httpx.Response(200, json={'devices': [{'vram_total': 100, 'vram_free': 0}]})
            value = pending[host]
            if value is None:
                raise httpx.ReadTimeout('Queue unavailable')
            return httpx.Response(200, json={'queue_pending': value, 'queue_running': [['active-job']]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            with patch.object(status, 'get_comfy_servers', return_value=[{'url': f'http://{host}'} for host in pending]), patch.object(status, 'get_backend_client', AsyncMock(return_value=client)):
                return await status.get_health()

    async def test_full_vram_and_running_job_without_backlog_do_not_warn(self):
        result = await self.health({'one': []})
        self.assertFalse(result['busy'])
        self.assertFalse(result['vram_warning'])

    async def test_single_pending_job_does_not_trigger_heavy_queue_warning(self):
        self.assertFalse((await self.health({'one': [['job']]}))['busy'])

    async def test_all_ready_backends_need_a_backlog(self):
        self.assertTrue((await self.health({'one': [[], []], 'two': [[], [], []]}))['busy'])
        self.assertFalse((await self.health({'one': [[], []], 'two': []}))['busy'])

    async def test_missing_telemetry_does_not_mean_overload(self):
        self.assertFalse((await self.health({'one': None}))['busy'])
        self.assertFalse((await self.health({'one': 'malformed'}))['busy'])

    async def test_offline_backends_do_not_mask_a_real_backlog(self):
        self.assertTrue((await self.health({'one': [[], []], 'two': []}, unavailable={'two'}))['busy'])

    async def test_api_tools_do_not_check_local_load(self):
        with patch.object(status, 'get_tool_settings', return_value={'provider': 'xai', 'model': 'model'}), patch('app.core.media_provider_config.ready', return_value=True), patch.object(status, 'get_backend_client', AsyncMock()) as backend:
            result = await status.get_health('api-image')
            self.assertFalse(result.get('busy', False))
            backend.assert_not_called()
