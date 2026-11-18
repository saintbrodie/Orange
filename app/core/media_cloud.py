"""Native xAI, Runway, and fal REST adapters. Contracts: docs/API_PROVIDERS.md."""
import base64
from io import BytesIO
import json
import re

from PIL import Image

from app.core.media_downloads import download_media
from app.core.media_providers import (
    MODELS, Media, ProviderResult, ProviderError, _request, _json, _decode, _usage, model_for,
)


def data_url(image):
    _, data, mime = image
    return f'data:{mime};base64,{base64.b64encode(data).decode("ascii")}'


def job_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,200}', value):
        raise ProviderError('Provider returned an invalid job identifier.')
    return value


def handle(kind, value):
    return f'{kind}:{job_id(value)}'


def unpack_handle(value):
    if not isinstance(value, str) or ':' not in value:
        raise ProviderError('Stored provider job is invalid.')
    kind, value = value.split(':', 1)
    if kind not in {'image', 'video'}:
        raise ProviderError('Stored provider job is invalid.')
    return kind, job_id(value)


def validate_request(provider, request):
    model = model_for(provider, request.model)
    if not request.prompt.strip() or len(request.prompt) > model.prompt_limit:
        raise ProviderError(f'Prompt must contain between 1 and {model.prompt_limit} characters for this model, including tool instructions.')
    ratios = ('source',) if model.reference_aspect and request.images else model.ratios
    if request.aspect_ratio not in ratios or request.resolution not in model.resolutions:
        raise ProviderError('Choose a supported aspect ratio and resolution.')
    if len(request.images) > model.references or (model.requires_image and not request.images):
        raise ProviderError('Choose the required reference images for this model.')
    if model.output == 'video' and request.duration not in model.durations:
        raise ProviderError('Choose a supported video duration.')
    return model


class XAIAdapter:
    id = 'xai'
    base = 'https://api.x.ai/v1'

    def headers(self, key):
        return {'Authorization': f'Bearer {key}'}

    async def test(self, client, key):
        payload = _json(await _request(client, 'GET', f'{self.base}/models', headers=self.headers(key)))
        if not isinstance(payload.get('data'), list):
            raise ProviderError('xAI returned an invalid model catalog.')
        return [m['id'] for m in payload['data'] if isinstance(m, dict) and isinstance(m.get('id'), str)]

    async def submit(self, client, key, request):
        model = validate_request(self.id, request)
        body = {'model': model.id, 'prompt': request.prompt,
                'resolution': request.resolution.lower()}
        if request.aspect_ratio != 'source':
            body['aspect_ratio'] = request.aspect_ratio
        if model.output == 'video':
            body['duration'] = request.duration
            if request.images:
                body['image'] = {'url': data_url(request.images[0])}
            payload = _json(await _request(client, 'POST', f'{self.base}/videos/generations', headers=self.headers(key), json=body))
            return ProviderResult(remote_id=handle('video', payload.get('request_id')))
        body.update(n=1, response_format='b64_json')
        endpoint = 'generations'
        if request.images:
            endpoint = 'edits'
            body['image'] = {'url': data_url(request.images[0]), 'type': 'image_url'}
        payload = _json(await _request(client, 'POST', f'{self.base}/images/{endpoint}', headers=self.headers(key), json=body))
        items = payload.get('data')
        if not isinstance(items, list) or not 1 <= len(items) <= 8:
            raise ProviderError('xAI returned no image. The request may have been filtered.')
        media = []
        for item in items:
            if not isinstance(item, dict) or not item.get('b64_json'):
                raise ProviderError('xAI returned an invalid image response.')
            media.append(Media(_decode(item['b64_json']), 'image/jpeg'))
        return ProviderResult(media=media, usage=_usage(payload.get('usage')))

    async def poll(self, client, key, remote_id):
        kind, identifier = unpack_handle(remote_id)
        if kind != 'video':
            raise ProviderError('Stored xAI job is invalid.')
        payload = _json(await _request(client, 'GET', f'{self.base}/videos/{identifier}', headers=self.headers(key)))
        if payload.get('status') == 'pending':
            return ProviderResult(remote_id=remote_id)
        if payload.get('status') != 'done':
            raise ProviderError('xAI could not complete this generation. Check the job in your provider account.')
        video = payload.get('video')
        if not isinstance(video, dict) or video.get('respect_moderation') is False:
            raise ProviderError('xAI did not return usable video. The request may have been filtered.')
        return ProviderResult(media=[await download_media(client, self.id, video.get('url'), 'video')])


class RunwayAdapter:
    id = 'runway'
    base = 'https://api.dev.runwayml.com/v1'
    image_ratios = {'1:1': '1024:1024', '16:9': '1280:720', '9:16': '720:1280', '4:3': '960:720', '3:4': '720:960'}

    def headers(self, key):
        return {'Authorization': f'Bearer {key}', 'X-Runway-Version': '2024-11-06'}

    async def test(self, client, key):
        # Runway documents organization authentication, but no model-list API.
        payload = _json(await _request(client, 'GET', f'{self.base}/organization', headers=self.headers(key)))
        if 'tier' not in payload:
            raise ProviderError('Runway returned an invalid organization response.')
        return [model.id for model in MODELS[self.id]]

    async def submit(self, client, key, request):
        model = validate_request(self.id, request)
        if len(request.prompt.encode('utf-16-le')) // 2 > 1000:
            raise ProviderError('Runway prompts must fit within 1,000 UTF-16 characters, including tool instructions.')
        images = [data_url(image) for image in request.images]
        if any(len(value.encode('ascii')) > 5_000_000 for value in images):
            raise ProviderError('Runway reference images must fit within its 5 MB data URL limit. Resize the image before uploading.')
        body = {'model': model.id, 'promptText': request.prompt, 'ratio': self.image_ratios[request.aspect_ratio]}
        if model.output == 'image':
            endpoint = 'text_to_image'
            if images:
                body['referenceImages'] = [{'uri': value, 'tag': f'reference{index + 1}'} for index, value in enumerate(images)]
        else:
            endpoint = 'image_to_video' if images else 'text_to_video'
            body['duration'] = request.duration
            if images:
                body['promptImage'] = images[0]
        payload = _json(await _request(client, 'POST', f'{self.base}/{endpoint}', headers=self.headers(key), json=body))
        return ProviderResult(remote_id=handle(model.output, payload.get('id')))

    async def poll(self, client, key, remote_id):
        kind, identifier = unpack_handle(remote_id)
        payload = _json(await _request(client, 'GET', f'{self.base}/tasks/{identifier}', headers=self.headers(key)))
        if payload.get('status') in {'PENDING', 'THROTTLED', 'RUNNING'}:
            return ProviderResult(remote_id=remote_id)
        if payload.get('status') != 'SUCCEEDED':
            raise ProviderError('Runway could not complete this generation. Check the task in your provider account.')
        urls = payload.get('output')
        if not isinstance(urls, list) or not 1 <= len(urls) <= 8:
            raise ProviderError('Runway returned no usable output.')
        return ProviderResult(media=[await download_media(client, self.id, url, kind) for url in urls])


class FalAdapter:
    id = 'fal'
    base = 'https://queue.fal.run'
    image_sizes = {'1:1': 'square_hd', '16:9': 'landscape_16_9', '9:16': 'portrait_16_9', '4:3': 'landscape_4_3', '3:4': 'portrait_4_3'}

    def headers(self, key):
        return {'Authorization': f'Key {key}'}

    async def test(self, client, key):
        # Catalog discovery is public. Check an authenticated, read-only API first.
        await _request(client, 'GET', 'https://api.fal.ai/v1/models/requests/by-endpoint',
                       params={'endpoint_id': MODELS[self.id][0].id, 'limit': 1}, headers=self.headers(key))
        payload = _json(await _request(client, 'GET', 'https://api.fal.ai/v1/models',
            params=[('endpoint_id', model.id) for model in MODELS[self.id]], headers=self.headers(key)))
        if not isinstance(payload.get('models'), list):
            raise ProviderError('fal returned an invalid model catalog.')
        return [item['endpoint_id'] for item in payload['models'] if isinstance(item, dict) and isinstance(item.get('endpoint_id'), str)]

    async def submit(self, client, key, request):
        model = validate_request(self.id, request)
        body = {'prompt': request.prompt}
        if model.output == 'image':
            body.update(image_size=self.image_sizes[request.aspect_ratio], output_format='png')
            if model.requires_image:
                body['image_urls'] = [data_url(image) for image in request.images]
        else:
            body.update(duration=request.duration, resolution=request.resolution)
            if model.requires_image:
                with Image.open(BytesIO(request.images[0][1])) as image:
                    if min(image.size) < 300 or not .4 <= image.width / image.height <= 2.5:
                        raise ProviderError('Kling needs a reference at least 300 pixels on each side with an aspect ratio between 0.4 and 2.5.')
                body['start_image_url'] = data_url(request.images[0])
            else:
                body['aspect_ratio'] = request.aspect_ratio
        payload = _json(await _request(client, 'POST', f'{self.base}/{model.id}', json=body,
                                      headers={**self.headers(key), 'X-Fal-No-Retry': '1'}))
        return ProviderResult(remote_id=json.dumps({'model': model.id, 'id': job_id(payload.get('request_id'))}))

    async def poll(self, client, key, remote_id):
        try:
            value = json.loads(remote_id)
            model = model_for(self.id, value['model'])
            identifier = job_id(value['id'])
        except (TypeError, ValueError, KeyError):
            raise ProviderError('Stored fal job is invalid.') from None
        # Endpoint paths are excluded from request status/result paths by fal.
        app = '/'.join(model.id.split('/')[:2])
        url = f'{self.base}/{app}/requests/{identifier}'
        payload = _json(await _request(client, 'GET', f'{url}/status', headers=self.headers(key)))
        if payload.get('status') in {'IN_QUEUE', 'IN_PROGRESS'}:
            return ProviderResult(remote_id=remote_id)
        if payload.get('status') != 'COMPLETED':
            raise ProviderError('fal could not complete this generation. Check the request in your provider account.')
        result = _json(await _request(client, 'GET', url, headers=self.headers(key)))
        if model.output == 'image':
            items = result.get('images')
        else:
            items = [result.get('video')]
        if not isinstance(items, list) or not 1 <= len(items) <= 8 or any(not isinstance(item, dict) for item in items):
            raise ProviderError('fal returned no usable output. The request may have been filtered.')
        return ProviderResult(media=[await download_media(client, self.id, item.get('url'), model.output) for item in items])
