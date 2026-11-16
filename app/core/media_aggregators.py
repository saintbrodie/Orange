"""Capability-driven raster image adapters for OpenRouter and Venice."""
import base64
from io import BytesIO

from PIL import Image

from app.core.media_providers import Model, ModelDiscovery, Media, ProviderResult, ProviderError, _request, _json, _decode, _usage, model_for, valid_model_id

RATIOS = ("1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "4:5", "5:4", "21:9")
RESOLUTIONS = ("512", "768", "1K", "1.5K", "2K", "4K")


def choices(value, allowed):
    return tuple(dict.fromkeys(v for v in value if isinstance(v, str) and v in allowed)) if isinstance(value, list) else ()


def mapping(value):
    return value if isinstance(value, dict) else {}


def label(value, fallback, key):
    return ''.join(c for c in str(value or fallback) if c.isprintable()).replace(key, '[redacted]')[:100]


def raster_result(payload):
    media = []
    for item in payload.get('data', []):
        if isinstance(item, dict) and item.get('b64_json'):
            mime = item.get('media_type', 'image/png')
            if mime not in {'image/png', 'image/jpeg', 'image/webp'}:
                raise ProviderError('Provider returned an unsupported image format.')
            media.append(Media(_decode(item['b64_json']), mime))
    if not media:
        raise ProviderError('Provider returned no raster image. The request may have been filtered.')
    return ProviderResult(media=media, usage=_usage(payload.get('usage')))


class OpenRouterAdapter:
    id = 'openrouter'
    managed_jobs = True
    base = 'https://openrouter.ai/api/v1'

    def headers(self, key):
        return {'Authorization': f'Bearer {key}'}

    async def test(self, client, key):
        # The image catalog is public. Verify the key separately without inference.
        identity = _json(await _request(client, 'GET', f'{self.base}/key', headers=self.headers(key)))
        if not isinstance(identity.get('data'), dict):
            raise ProviderError('Provider returned an invalid credential response.')
        payload = _json(await _request(client, 'GET', f'{self.base}/images/models', headers=self.headers(key)))
        if not isinstance(payload.get('data'), list):
            raise ProviderError('Provider returned an invalid image model catalog.')
        models = []
        for item in payload['data'][:2000]:
            if not isinstance(item, dict) or not valid_model_id(item.get('id')) or key in item['id']:
                continue
            architecture = mapping(item.get('architecture'))
            if 'image' not in architecture.get('output_modalities', []) or any(word in item['id'].lower() for word in ('svg', 'vector')):
                continue
            parameters = item.get('supported_parameters') or {}
            if not isinstance(parameters, dict):
                continue
            ratio_values = mapping(parameters.get('aspect_ratio')).get('values')
            resolution_values = mapping(parameters.get('resolution')).get('values')
            ratios = choices(ratio_values, RATIOS)
            resolutions = choices(resolution_values, RESOLUTIONS)
            if (ratio_values and not ratios) or (resolution_values and not resolutions):
                continue
            references = 1 if 'image' in architecture.get('input_modalities', []) else 0
            models.append(Model(item['id'], label(item.get('name'), item['id'], key), ratios=ratios or ('1:1',), resolutions=resolutions or ('standard',), references=references, send_ratio=bool(ratios)))
        return ModelDiscovery(list({model.id: model for model in models}.values()))

    async def submit(self, client, key, request):
        model = model_for(self.id, request.model)
        if len(request.prompt) > model.prompt_limit:
            raise ProviderError('Prompt exceeds this model’s character limit.')
        body = {'model': request.model, 'prompt': request.prompt, 'n': 1}
        if model.send_ratio:
            body['aspect_ratio'] = request.aspect_ratio
        if request.resolution != 'standard':
            body['resolution'] = request.resolution
        if request.images:
            body['input_references'] = [{'type': 'image_url', 'image_url': {'url': f'data:{mime};base64,{base64.b64encode(data).decode("ascii")}'}} for _, data, mime in request.images]
        payload = _json(await _request(client, 'POST', f'{self.base}/images', json=body, headers=self.headers(key)))
        return raster_result(payload)


class VeniceAdapter(OpenRouterAdapter):
    id = 'venice'
    base = 'https://api.venice.ai/api/v1'

    async def test(self, client, key):
        models = []
        for kind in ('image', 'inpaint'):
            payload = _json(await _request(client, 'GET', f'{self.base}/models', params={'type': kind}, headers=self.headers(key)))
            if not isinstance(payload.get('data'), list):
                raise ProviderError('Provider returned an invalid image model catalog.')
            for item in payload['data'][:2000]:
                if not isinstance(item, dict) or not valid_model_id(item.get('id')) or key in item['id']:
                    continue
                if item.get('type', kind) != kind:
                    continue
                spec = mapping(item.get('model_spec'))
                if spec.get('offline'):
                    continue
                constraints = mapping(spec.get('constraints'))
                ratios = choices(constraints.get('aspectRatios'), RATIOS)
                resolutions = choices(constraints.get('resolutions'), RESOLUTIONS)
                edit = kind == 'inpaint'
                # Auto-only editing models cannot expose Orange's format choices.
                if edit and not ratios and constraints.get('aspectRatios'):
                    continue
                if (constraints.get('aspectRatios') and not ratios) or (constraints.get('resolutions') and not resolutions):
                    continue
                limit = constraints.get('promptCharacterLimit', 10000)
                limit = min(10000, max(1, limit)) if type(limit) is int else 10000
                models.append(Model(item['id'], label(spec.get('name'), item['id'], key), ratios=ratios or (('1:1',) if edit else ('1:1', '3:2', '2:3')), resolutions=resolutions or ('standard',), references=1 if edit else 0, requires_image=edit, send_ratio=bool(ratios), pixel_dimensions=not ratios and not edit, prompt_limit=limit))
        return ModelDiscovery(list({model.id: model for model in models}.values()))

    async def submit(self, client, key, request):
        model = model_for(self.id, request.model)
        if len(request.prompt) > model.prompt_limit:
            raise ProviderError('Prompt exceeds this model’s character limit.')
        body = {'model': request.model, 'prompt': request.prompt}
        if model.send_ratio:
            body['aspect_ratio'] = request.aspect_ratio
        if model.pixel_dimensions:
            body['width'], body['height'] = {'1:1': (1024, 1024), '3:2': (1152, 768), '2:3': (768, 1152)}[request.aspect_ratio]
        if request.resolution != 'standard':
            body['resolution'] = request.resolution
        if model.requires_image:
            if len(request.images) != 1:
                raise ProviderError('This editing model requires one reference image.')
            _, data, _ = request.images[0]
            with Image.open(BytesIO(data)) as image:
                if min(image.size) < 64 or image.width * image.height < 65536:
                    raise ProviderError('Venice editing requires an image with at least 65,536 pixels and sides of at least 64 pixels.')
                if image.width * image.height > 33_177_600 or len(data) >= 25_000_000:
                    raise ProviderError('The reference image exceeds Venice’s editing limit.')
            body.update(image=base64.b64encode(data).decode('ascii'), output_format='png')
            response = await _request(client, 'POST', f'{self.base}/image/edit', json=body, headers=self.headers(key))
            mime = response.headers.get('content-type', '').split(';')[0]
            if mime not in {'image/png', 'image/jpeg', 'image/webp'}:
                raise ProviderError('Venice returned an invalid editing response.')
            return ProviderResult(media=[Media(response.content, mime)])
        if request.images:
            raise ProviderError('Choose a Venice editing model to use a reference image.')
        body.update(format='png', return_binary=False, variants=1)
        payload = _json(await _request(client, 'POST', f'{self.base}/image/generate', json=body, headers=self.headers(key)))
        images = payload.get('images', [])
        if not isinstance(images, list) or not images:
            raise ProviderError('Venice returned no image. The request may have been filtered.')
        return ProviderResult(media=[Media(_decode(value), 'image/png') for value in images])
