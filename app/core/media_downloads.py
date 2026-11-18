"""Bounded downloads from provider-owned delivery hosts, without API credentials."""
import asyncio
from urllib.parse import urljoin, urlsplit

import httpx

from app.core.media_providers import DeliveryError, Media

MAX_DOWNLOAD_BYTES = 256 * 1024 * 1024
GOOGLE_API_HOST = 'generativelanguage.googleapis.com'
DELIVERY_HOSTS = {
    'xai': ('vidgen.x.ai', 'imgen.x.ai'),
    'runway': ('cloudfront.net', 'runwayapi.com', 'runwayml.com', 'runway.com'),
    'fal': ('fal.media', 'storage.googleapis.com'),
    'google': ('googleusercontent.com',),
}


def delivery_url(provider, value):
    try:
        if not isinstance(value, str) or len(value) > 16000 or any(ord(c) <= 32 for c in value) or '\\' in value:
            raise ValueError
        parsed = urlsplit(value)
        host = parsed.hostname or ''
        if parsed.scheme != 'https' or parsed.port not in (None, 443) or parsed.username or parsed.password or parsed.fragment:
            raise ValueError
        if provider == 'google' and host in {GOOGLE_API_HOST, 'storage.googleapis.com'}:
            return value
        if not any(host == domain or host.endswith('.' + domain) for domain in DELIVERY_HOSTS[provider]):
            raise ValueError
    except (ValueError, KeyError):
        raise DeliveryError('Provider returned an unsupported media location.') from None
    return value


async def download_media(client, provider, url, output_type, *, google_headers=None):
    """Stream allowed URLs. Only Google's exact API host receives its key."""
    url = delivery_url(provider, url)
    for _ in range(5):
        for attempt in range(3):
            response = None
            try:
                request = client.build_request('GET', url)
                for name in ('authorization', 'cookie', 'x-api-key', 'x-goog-api-key', 'x-runway-version'):
                    request.headers.pop(name, None)
                if provider == 'google' and request.url.host == GOOGLE_API_HOST and google_headers:
                    request.headers.update(google_headers)
                response = await client.send(request, stream=True, auth=None, follow_redirects=False)
                if response.is_redirect:
                    url = delivery_url(provider, urljoin(url, response.headers.get('location', '')))
                    break
                if response.status_code in {408, 429, 500, 502, 503, 504} and attempt < 2:
                    await response.aclose()
                    await asyncio.sleep(2 ** attempt)
                    continue
                if response.status_code != 200:
                    raise DeliveryError('Could not download the generated media. The provider may have charged for this generation.')
                mime = response.headers.get('content-type', '').split(';')[0].lower()
                allowed = {'image/png', 'image/jpeg', 'image/webp'} if output_type == 'image' else {'video/mp4'}
                if mime not in allowed | {'', 'application/octet-stream'}:
                    raise DeliveryError('Provider returned an unsupported media format.')
                length = response.headers.get('content-length')
                if length and (not length.isdigit() or int(length) > MAX_DOWNLOAD_BYTES):
                    raise DeliveryError('Provider output exceeds Orange’s local media limit.')
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(data) + len(chunk) > MAX_DOWNLOAD_BYTES:
                        raise DeliveryError('Provider output exceeds Orange’s local media limit.')
                    data.extend(chunk)
                if not data:
                    raise DeliveryError('Provider returned empty media.')
                return Media(bytes(data), mime if mime in allowed else 'image/png' if output_type == 'image' else 'video/mp4')
            except httpx.HTTPError:
                if attempt == 2:
                    raise DeliveryError('The generated media download was interrupted.') from None
                await asyncio.sleep(2 ** attempt)
            finally:
                if response is not None:
                    await response.aclose()
        else:
            raise DeliveryError('Could not download the generated media.')
    raise DeliveryError('Provider redirected the media download too many times.')
