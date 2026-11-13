import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException, UploadFile
from PIL import Image
from starlette.requests import Request
from starlette.datastructures import Headers

from app.api import generation_v2
from app.core import workflow_packs
from app.core.config_validation import validate_config
from app.core.public_config import build_public_config
from app.core.video_controls import select_input_variant, tool_variants

ROOT = Path(__file__).resolve().parents[1]


class ReferenceControlTests(unittest.TestCase):
    def test_optional_reference_is_public_without_exposing_the_graph(self):
        for pack in ('klein-9b-edit', 'qwen-image-2.1-edit'):
            tool = workflow_packs.tool_config_for_pack(pack)
            self.assertEqual(validate_config({'tools': [tool]})['errors'], [])
            public = build_public_config({'tools': [tool]})['tools'][0]
            self.assertTrue(public['optionalReference'])
            self.assertNotIn('referenceVariant', public)
            self.assertNotIn('image2', select_input_variant(tool, True)['nodeMapping'])
            self.assertIn('image2', select_input_variant(tool, True, True)['nodeMapping'])
            self.assertEqual(len(tool_variants(tool)), 2)

    def test_reference_variant_requires_a_source_and_a_second_image_mapping(self):
        tool = workflow_packs.tool_config_for_pack('qwen-image-2.1-edit')
        del tool['referenceVariant']['nodeMapping']['image2']
        self.assertTrue(any(e['code'] == 'reference_variant_invalid' for e in validate_config({'tools': [tool]})['errors']))
        tool['referenceVariant']['referenceVariant'] = {}
        self.assertTrue(any(e['code'] == 'image_variant_invalid' for e in validate_config({'tools': [tool]})['errors']))

    def test_model_bindings_materialize_both_graphs(self):
        for pack in ('klein-9b-edit', 'qwen-image-2.1-edit'):
            manifest = workflow_packs.get_workflow_pack(pack)
            models = workflow_packs.select_model_dependencies(pack, {})
            for model in models:
                model['filename'] = 'organized/' + model['filename']
            by_id = {model['id']: model for model in models}
            with tempfile.TemporaryDirectory() as directory:
                with patch.object(workflow_packs, 'ACTIVE_WORKFLOWS_DIR', directory):
                    workflow_packs.materialize_workflow_pack(pack, models)
                for variant in tool_variants(manifest['tool']):
                    graph = json.loads((Path(directory) / variant['workflowFile']).read_text())
                    for binding in manifest['bindings']:
                        self.assertEqual(graph[binding['nodeId']]['inputs'][binding['field']], by_id[binding['modelId']]['filename'].rsplit('/', 1)[-1])


class ReferenceSubmissionTests(unittest.IsolatedAsyncioTestCase):
    def image(self):
        data = io.BytesIO()
        Image.new('RGB', (64, 64), 'orange').save(data, 'PNG')
        data.seek(0)
        return UploadFile(filename='test.png', file=data, headers=Headers({'content-type': 'image/png'}))

    async def submit(self, pack, second=False, source=True, required=False):
        tool = workflow_packs.tool_config_for_pack(pack)
        if required:
            tool = select_input_variant(tool, True, True)
        request = Request({'type': 'http', 'method': 'POST', 'path': '/api/generate', 'headers': [], 'client': ('127.0.0.1', 1)})
        submit = AsyncMock(return_value={'prompt_id': 'reference-test'})
        with (patch.object(generation_v2, 'get_tool_settings', return_value=tool),
              patch.object(generation_v2, 'get_base_workflow', side_effect=lambda name: json.loads((ROOT / 'workflows/defaults' / name).read_text())),
              patch.object(generation_v2, '_prepare_asset_payloads', return_value=([], {})),
              patch.object(generation_v2, '_stage_assets', new_callable=AsyncMock),
              patch.object(generation_v2, 'load_config', return_value={}),
              patch.object(generation_v2, 'get_best_backend', AsyncMock(return_value='http://comfy')),
              patch.object(generation_v2, 'get_backend_client', AsyncMock(return_value=object())),
              patch.object(generation_v2, 'backend_inventory', AsyncMock(return_value={})),
              patch.object(generation_v2, 'upload_image_bytes', AsyncMock(side_effect=['source.png', 'reference.png'])) as upload,
              patch.object(generation_v2, 'submit_prompt', submit),
              patch.object(generation_v2, 'get_comfy_servers', return_value=[]),
              patch.object(generation_v2, 'increment_active'), patch.object(generation_v2, 'decrement_active'),
              patch.object(generation_v2, 'report_backend_success'), patch.object(generation_v2, 'log_usage')):
            await generation_v2.generate_v2(request, tool_id=tool['id'], prompt='Apply the reference style', aspect_ratio=None,
                                          image=self.image() if source else None, image2=self.image() if second else None, duration=None)
        return submit.call_args.args[2]['prompt'], upload.await_count, tool

    async def test_both_tools_accept_one_image_or_use_two_uploaded_images(self):
        for pack in ('klein-9b-edit', 'qwen-image-2.1-edit'):
            for second in (False, True):
                with self.subTest(pack=pack, reference=second):
                    graph, count, tool = await self.submit(pack, second)
                    self.assertEqual(count, 2 if second else 1)
                    mapping = select_input_variant(tool, True, second)['nodeMapping']
                    self.assertEqual(graph[mapping['image']['nodeId']]['inputs'][mapping['image']['field']], 'source.png')
                    if second:
                        self.assertEqual(graph[mapping['image2']['nodeId']]['inputs'][mapping['image2']['field']], 'reference.png')
                    else:
                        self.assertEqual(sum(n['class_type'] == 'LoadImage' for n in graph.values()), 1)

    async def test_source_is_required_even_with_a_reference(self):
        with self.assertRaises(HTTPException) as caught:
            await self.submit('qwen-image-2.1-edit', second=True, source=False)
        self.assertEqual(caught.exception.status_code, 400)

    async def test_ordinary_two_image_tools_still_require_both(self):
        with self.assertRaises(HTTPException) as caught:
            await self.submit('qwen-image-2.1-edit', required=True)
        self.assertEqual(caught.exception.status_code, 400)
