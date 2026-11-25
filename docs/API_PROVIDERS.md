# Native API media generation

To add a preset, open **Admin → Tools → Curated Library → API**. Nano Banana
2.1 uses a Google key, and GPT Image 2.6 Flare uses an OpenAI key. Use
the preset's **Open API Keys** link to configure the key and enable media
generation, then return and select **Add to Orange**. In Generate, enter a
prompt to create an image, or attach an optional reference image to edit it.
Both presets work on cloud-only installations.

Orange can run ComfyUI tools, direct cloud API tools, or both. People using
Generate still see a curated tool, prompt, optional reference images, and the
format choices selected by the administrator.

## Setup

1. Start Orange normally. On a fresh install, choose **Use cloud APIs only** to
   finish setup without connecting ComfyUI. Create the Admin password as usual.
2. Open **Admin → General Settings → API Keys**.
   Expand the provider you want to configure.
3. Save a Google, OpenAI, OpenRouter, Venice, xAI, Runway, or fal.ai credential and enable media generation.
   **Test connection** lists the account's available models without generating
   paid media and shows the compatible media models it found. It does not test
   individual models. A successful listing does not guarantee billing,
   quota, regional availability, or permission to generate with that model.
4. Open **Admin → Tools → Create API Tool**. Give the tool a name, select the
   provider and one of its discovered models, and curate aspect ratios, resolutions, reference inputs,
   and (for video) durations. Choose required image input for editing tools;
   Venice editing models require it automatically.
5. Save the tool and use the normal Generate page. Images and videos appear in
   the same result view, download controls, and Admin Gallery as ComfyUI results.

Existing installations keep their workflows and ComfyUI routing. A tool without
a `provider` field remains a ComfyUI tool. You can add cloud tools without
changing or removing any ComfyUI configuration; an unavailable ComfyUI backend
does not disable a selected API tool. Cloud-only setup suppresses the historical
localhost ComfyUI fallback, while explicitly added servers remain usable.

### Credentials

Credentials are stored in the server account's native operating system credential
store, using the same native-backend policy as Orange's Hugging Face credentials:
Windows Credential Manager, macOS Keychain, or Linux Secret Service. Orange does
not fall back to plaintext files. Install `requirements.txt` and unlock the
credential store under the account running Orange.

For a headless server, set environment variables before launching Orange:

| Provider | Environment variables, in precedence order |
| --- | --- |
| Google | `ORANGE_GOOGLE_API_KEY`, `GEMINI_API_KEY`, `GOOGLE_API_KEY` |
| OpenAI | `ORANGE_OPENAI_API_KEY`, `OPENAI_API_KEY` |
| OpenRouter | `ORANGE_OPENROUTER_API_KEY`, `OPENROUTER_API_KEY` |
| Venice | `ORANGE_VENICE_API_KEY`, `VENICE_API_KEY` |
| xAI | `ORANGE_XAI_API_KEY`, `XAI_API_KEY` |
| Runway | `ORANGE_RUNWAY_API_KEY`, `RUNWAYML_API_SECRET`, `RUNWAY_API_KEY` |
| fal.ai | `ORANGE_FAL_API_KEY`, `FAL_KEY`, `FAL_API_KEY` |
| Anthropic (prompt enhancement) | `ORANGE_ANTHROPIC_API_KEY`, `ANTHROPIC_API_KEY` |

Environment credentials override saved credentials. Removing a saved credential
does not unset an environment variable. Admin only receives configured/source
status; saved keys never return through configuration/status APIs. Key input
fields clear after submission and show a masked placeholder when configured. Use HTTPS when accessing Admin over a network.

Non-secret provider enablement, cached model discovery live in
`workflows/.runtime/api-providers.json`. They are separate from tool configuration
and excluded from Git. Do not place media API credentials in tool definitions or
prompt-enhancer settings.

Model selection happens only when creating or editing a tool. There is no second
model enablement checklist in provider settings. Connection testing uses Google's
[paginated model list](https://ai.google.dev/api/models) or OpenAI's
[model list](https://developers.openai.com/api/reference/resources/models/methods/list),
then matches those IDs against Orange's supported media capabilities. Text-only
or unsupported models are not offered as media tools. Orange retains capability
definitions internally so each selected model gets the correct controls and API
request shape. Changing the saved credential clears cached discovery; test again
to refresh it. Existing tools remain editable and runnable without rediscovery.

OpenRouter and Venice use capability-driven discovery instead of a fixed model
list. Orange caches sanitized model IDs, display names, and supported controls;
provider descriptions, pricing, and arbitrary catalog fields are not stored.
Test the connection again to refresh model availability. Previously discovered
definitions remain available to existing tools if a model disappears from the
latest catalog, while new tools only offer the latest discovered selection.

## Verified provider contracts

Model IDs and REST contracts were checked against official documentation on
**November 16, 2026**. Model access and pricing depend on the provider account.
Orange deliberately exposes a smaller supported subset than each model's full
capabilities.

| Model | API model ID | Initial Orange controls |
| --- | --- | --- |
| Google Nano Banana 2.1 | `gemini-nano-banana-2.1` | Generate/edit, up to two references, five curated ratios, 1K/2K/4K |
| Google Nano Banana 2 | `gemini-3.1-flash-image` | Same curated image controls |
| Google Nano Banana Pro | `gemini-3-pro-image` | Same curated image controls |
| OpenAI GPT Image 2.6 Sunburst | `gpt-image-2.6-sunburst` | Generate/edit, up to two references, square/landscape/portrait |
| OpenAI GPT Image 2.6 Flare | `gpt-image-2.6-flare` | Generate/edit, up to two references, square/landscape/portrait |
| OpenAI GPT Image 2.5 | `gpt-image-2.5-sunburst`, `gpt-image-2.5-flare` | Same curated image controls |
| OpenAI GPT Image 2 / 1.5 / 1 Mini | `gpt-image-2`, `gpt-image-1.5`, `gpt-image-1-mini` | Same curated image controls |
| OpenRouter image catalog | Discovered from `/images/models` | Supported curated ratios/resolution tiers, up to two references when advertised |
| Venice image/edit catalogs | Discovered from `/models?type=image` and `type=inpaint` | Supported ratios/resolution tiers; one required reference for editing models |
| xAI Grok Imagine Image 2.0 | `grok-imagine-image-2.0` | Generate/edit, one optional or required reference, five curated ratios, 1K/2K |
| xAI Grok Imagine Video 1.5 / Lite | `grok-imagine-video-1.5`, `grok-imagine-video-1.5-lite` | Text or starting-image video, 720p/1080p, 5/10/15 seconds |
| Runway Gen-4 Image / Turbo | `gen4_image`, `gen4_image_turbo` | Five curated image sizes, up to two references; Turbo requires a reference |
| Runway Gen-4.5 / Gen-4 Turbo | `gen4.5`, `gen4_turbo` | 16:9/9:16, 720p, 5/10 seconds; Turbo requires a starting image |
| fal FLUX.2 Pro / Edit | `fal-ai/flux-2-pro`, `fal-ai/flux-2-pro/edit` | Five curated sizes; Edit requires one or two references |
| fal Kling 4.0 Flash | `kling/v4/flash/text-to-video`, `kling/v4/flash/image-to-video` | 720p, 5/10/15 seconds; image-to-video requires a starting image |
| Google Omni 1.2 Flash | `gemini-omni-1.2-flash` | Text/reference-to-video, up to two references, 16:9/9:16, 720p/1080p, 5/10/15 seconds |

GPT Image 2.6 is exposed through the documented Sunburst and Flare variants;
`gpt-image-2.6` is not used as an invented model ID. The initial OpenAI sizes are
1024×1024, 1536×1024, and 1024×1536. The single `standard` resolution option is
hidden in Generate; raw quality/size parameters remain provider internals.
Omni generates native audio. Video editing/extension, masks, search grounding,
additional references, streaming previews, and multi-turn provider conversations
are outside the initial tool surface.

The OpenRouter and Venice integrations initially cover raster image generation and editing,
plus text models for prompt enhancement. They do not add aggregator video, audio,
SVG/vector output, masks, or multi-image compositing. Model access varies by
account and region; discovery indicates API compatibility, not guaranteed quota.
Examples documented by the providers include Seedream and FLUX on OpenRouter,
and Z-Image Turbo, Qwen Image, Nano Banana, GPT Image, FLUX, and Seedream on Venice.
Orange reads the actual IDs and capabilities from the provider instead of
hardcoding these changing selections. Auto-only aspect-ratio models are omitted
until Orange can represent their behavior accurately.

### xAI, Runway, and fal.ai

These providers use the same API Keys cards, tool creation, Generate page, local
output endpoints, metadata setting, and usage history. Enable media generation,
test the connection, then select a model when creating a tool. Tests do not
generate paid media. xAI also appears in Prompt Enhancement and reuses its saved
key; Runway and fal are media integrations in this release.

- **xAI:** authenticated `/v1/models` discovery filters the curated catalog above.
  Images use `/v1/images/generations` or `/v1/images/edits`, base64 output, and
  lowercase resolution tiers. Video uses `/v1/videos/generations` followed by
  `/v1/videos/{request_id}` polling. Image-to-video preserves the starting
  image's aspect ratio. In tool creation choose zero references for text-to-video,
  or one required reference for image-to-video; the latter hides format choices.
  Video 1.5 renders 1080p natively; Lite's 1080p is upscaled. Image generation is
  synchronous; video job handles resume after an Orange restart.
- **Runway:** connection testing authenticates through `GET /v1/organization`.
  Runway has no documented account model-list endpoint, so Orange offers its
  curated models after authentication and checks access when generating. All
  requests use `X-Runway-Version: 2024-11-06`. Images use `/v1/text_to_image`;
  videos use `/v1/text_to_video` or `/v1/image_to_video`. Task polling uses
  `/v1/tasks/{id}`. Tool instructions and user prompt together must fit within
  1,000 UTF-16 code units. Base64 reference data URLs are limited to 5 MB;
  resize larger inputs before uploading. Both image and video tasks can resume.
- **fal.ai:** use a key that permits inference and reading your own request
  metadata (the documented API preset). Testing checks an authenticated request
  listing with a one-item limit, discards it, then queries `/v1/models` for the
  curated endpoint IDs. The catalog alone is public and cannot verify a key.
  Discovery does not expose every fal endpoint: each supported request contract
  is explicitly mapped. Jobs use `queue.fal.run`, save only the model and request
  ID, and reconstruct status/result paths from the registered model. No public
  webhook or cloud file upload is required; references use data URLs. The queue
  receives `X-Fal-No-Retry: 1`; Orange's existing safe HTTP retry policy applies.
  Kling image-to-video follows the starting image's aspect ratio and hides
  format choices. Both image and video request handles resume after restart.

Official contracts checked November 16, 2026:

- xAI [images REST](https://docs.x.ai/developers/rest-api-reference/inference/images),
  [video generation](https://docs.x.ai/developers/model-capabilities/video/generation),
  and [model discovery](https://docs.x.ai/developers/rest-api-reference/inference/models).
- Runway [API reference](https://docs.dev.runwayml.com/api/),
  [official generated image schema](https://github.com/runwayml/sdk-python/blob/main/src/runwayml/types/text_to_image_create_params.py),
  [video schema](https://github.com/runwayml/sdk-python/blob/main/src/runwayml/types/text_to_video_create_params.py),
  and [output delivery](https://docs.dev.runwayml.com/assets/outputs/).
- fal [model discovery](https://fal.ai/docs/platform-apis/v1/models),
  [authenticated request listing](https://fal.ai/docs/platform-apis/v1/models/requests/by-endpoint),
  [queue API](https://fal.ai/docs/documentation/model-apis/inference/queue),
  [FLUX generation](https://fal.ai/models/fal-ai/flux-2-pro/api),
  [FLUX editing](https://fal.ai/models/fal-ai/flux-2-pro/edit/api), and Kling Flash
  [text-to-video](https://fal.ai/models/kling/v4/flash/text-to-video/api) /
  [image-to-video](https://fal.ai/models/kling/v4/flash/image-to-video/api).

The adapters use Orange's existing **httpx** dependency. No additional provider SDK
is installed or required. Official Google/OpenAI SDK examples use `openai` and `google-genai`
respectively, but the documented REST endpoints provide every feature used here:

- [Google image generation](https://ai.google.dev/gemini-api/docs/image-generation):
  `POST /v1beta/interactions`, `Api-Revision: 2026-05-20`, typed image inputs and
  `response_format` image sizing. REST outputs are read from `steps` of type
  `model_output`; SDK convenience fields such as `output_image` are not REST
  fields.
- [OpenAI image generation](https://developers.openai.com/api/reference/resources/images/methods/generate):
  `POST /v1/images/generations`, base64 raster output. GPT Image models do not use
  the legacy `response_format` parameter.
- [OpenAI image editing](https://developers.openai.com/api/reference/resources/images/methods/edit):
  `POST /v1/images/edits`, JSON `images` with base64 data URLs. No intermediate
  cloud file upload is needed.
- [Google Omni video](https://ai.google.dev/gemini-api/docs/omni):
  `POST /v1beta/interactions`, video `response_format`, `duration` such as `15s`,
  and `delivery: uri`. Orange polls `GET /v1beta/files/{id}` until `ACTIVE`, then
  downloads `/v1beta/files/{id}:download?alt=media`.
- [Google Interactions retention](https://aistudio.google.com/docs/interactions-overview):
  Orange sends `store: false` and does not use provider conversation history or
  background interactions. Returned video files still use Google's temporary
  file-processing/delivery service.
- [OpenRouter image API](https://openrouter.ai/docs/guides/overview/multimodal/image-generation):
  discover `/api/v1/images/models`, generate through `POST /api/v1/images`, and
  send optional data URL references through `input_references`. Orange verifies
  the credential first with the authenticated
  [current-key endpoint](https://openrouter.ai/docs/api/api-reference/api-keys/get-current-key)
  because the image catalog is public. Orange uses the catalog's `input_references`
  range to decide whether to offer references and caps the count at two. Retest
  the connection to refresh cached capabilities, then review any existing tools
  whose reference settings no longer match the model.
- [Venice model discovery](https://docs.venice.ai/api-reference/endpoint/models/list),
  [generation](https://docs.venice.ai/api-reference/endpoint/image/generate), and
  [editing](https://docs.venice.ai/api-reference/endpoint/image/edit): generators
  use `/api/v1/image/generate` with base64 output; editors use
  `/api/v1/image/edit` with one base64 input and a binary raster response.
  Tiered models use advertised aspect ratios and resolutions. Pixel-sized models
  use a curated 1024×1024, 1152×768, or 768×1152 size. Editing references must meet
  Venice's pixel and file-size limits; prompt limits come from model metadata.

Cloud tools send prompts and supplied reference images to the chosen provider.
Local-first means Orange owns its configuration, job ledger, and downloaded
results; it does not mean cloud inference happens offline. Provider data and
retention policies still apply.

## Jobs, retries, and local outputs

API jobs receive an Orange UUID immediately. Work runs independently of the
browser's status stream, with two active cloud jobs and a maximum of 32 queued
or active jobs per process. Existing ComfyUI jobs retain their queue-aware
routing, workflow mapping, asset upload, and safe failover engine behind the
ComfyUI adapter.

The API lifecycle is `queued → submitting → processing/downloading → completed`,
with separate `failed`, `delivery_failed`, `timed_out`, and `interrupted` states. Status uses the existing
`/api/status` SSE contract. Processing stages are reported honestly; the adapters
do not invent a numerical percentage when the provider supplies none.

- Image jobs have a 15-minute overall deadline; video jobs have 30 minutes,
  including local queue time. Individual cloud requests have a 10-minute read
  timeout and a 15-second connection timeout.
- Polls run every five seconds. Connection establishment failures and explicit
  HTTP 429 rejections can retry up to three total attempts with bounded backoff.
  Safe GET polls/downloads also retry transient failures.
- A paid POST is **never** automatically repeated after a read/write failure or
  HTTP 5xx response. Orange cannot prove whether the provider accepted it.
  Errors tell the administrator/user to check provider usage before regenerating.
- At restart, known Google video, xAI video, Runway task, and fal request handles
  resume through GET-only polling and downloads.
  A job still in the local queue can be generated again. If Orange was already
  submitting the job and no handle was saved, check the provider's usage before
  generating again. The submission may have been accepted.
- When fetching a completed result fails, use **Retry download** in Generate.
  Jobs that timed out with a saved handle offer the same action. Orange polls the
  existing provider job and saves the recovered result under the same local job
  ID. The provider must still retain the job and its output. This action is also
  available via `POST /api/jobs/{job_id}/retry-download`.
- Provider exception bodies, arbitrary response fields, and credentials are not
  written to job errors or usage logs. API redirects are rejected. Media delivery
  accepts only explicitly trusted provider/CDN HTTPS hosts, revalidates redirects,
  strips API headers and cookies, and enforces a 256 MiB streaming download limit.
  Signed output URLs are not persisted in the job ledger or usage history.

Local mode exposes configured cloud tools on the Orange host. Open LAN mode
requires the owner's `ORANGE_LAN_TOOLS` list to include a cloud tool before guests
can run it using the connected account's API key. Use provider-side spending
limits where available. The Orange queue limit controls concurrent work.

In Team mode, the owner sets a USD estimate per cloud generation tool and a
monthly workspace limit. Orange reserves the estimate against the workspace
and submitting account before scheduling work. OpenRouter image generation can
provide a reported USD charge for reconciliation. Other cloud media jobs use the
configured estimate when the provider omits a reported charge. If the provider
may have accepted a failed or interrupted request, Orange keeps the estimate
against the budget. Delivery retries reuse the original reservation.

SQLite's `media_jobs` table stores the lifecycle, remote file handle, deadline,
and local output manifest. Media is saved atomically under `runtime/media/`,
which is excluded from Git and is not mounted as a public static directory.
Images are decoded and re-encoded as PNG to remove prompt/EXIF metadata. Video
outputs are validated as MP4. Each output is limited to 256 MiB.

The existing `/api/outputs`, `/api/output`, `/api/media`, and `/api/image`
endpoints dispatch to local output files for API jobs, including indexed result
downloads. Admin Gallery includes local API media and its usage record. Deleting
completed API media removes its local files and records without contacting
ComfyUI. Active jobs cannot be deleted while writing output.

Database backups include job manifests and usage records, **not media bytes or
OS credentials**. Back up `runtime/media/` separately alongside the database for
a full move/restore. Missing local files return 404 rather than contacting a
provider to regenerate. Run one Orange application worker; this is a local job
manager, not a distributed queue service.

## Usage tracking

Accepted API jobs record provider, model, generation status, and numeric token
usage. Analytics and CSV export include provider, model, and status. Cost
estimation has been removed. Legacy database columns remain for compatibility
with existing databases and backups, but new jobs do not populate them.

## Extending providers

- Add curated model capabilities to `MODELS` in `app/core/media_providers.py`,
  or return sanitized `ModelDiscovery` definitions from a capability-aware
  adapter such as those in `media_aggregators.py`. Tool validation and Admin's
  model/input choices derive from `provider_models`, shared by both paths.
- Add an adapter with `test`, `submit`, and optional `poll` methods. Return
  `ProviderResult` containing media bytes or an opaque resumable handle; raise
  `ProviderError` using safe, constant messages. Register it in `ADAPTERS`.
- Add server-side credential/environment configuration and its Admin projection
  in `media_provider_config.py`. Keep secrets outside tool configuration.
- For a new resumable handle type, explicitly implement safe startup recovery in
  `MediaJobManager.start`; never turn an uncertain job into a fresh paid POST.
- Add transport-contract, validation, redaction, and lifecycle tests before
  enabling the provider in the catalog.

Validation: `python -X utf8 -m unittest discover -s tests` and JavaScript syntax
checks. Provider tests use `httpx.MockTransport`; browser verification uses an
isolated configuration and deterministic mocked image generation. Live paid
generation requires administrator credentials and is not part of offline tests.

### Metadata and tool instructions

**General Settings** has one app-wide **Remove metadata from generated media**
switch, enabled by default, covering API jobs and served ComfyUI images. Image outputs are re-encoded without metadata; MP4 user metadata boxes
are blanked without changing media offsets. Disabling the switch preserves the
provider's original output bytes. This does not remove visible watermarks or
watermarks embedded in image/video content. Input references are still normalized
before transmission. API terminal events report generation, metadata removal,
and completion independently of browser connections.

API tools use readable IDs such as `api-image`, `api-video`, and numbered variants
when needed. Image input can be optional or required for editing; the distinction
is necessary because generation models also accept optional references. An
optional private **System prompt** provides instructions prepended to every user
prompt for that tool. It is not exposed through public tool configuration.

## General Settings and shared API keys

General Settings uses Generation, Backends, Prompt Enhancement, API Keys, and
System tabs. Switching tabs preserves unsaved fields; Save Settings applies all
general settings together. Credentials have their own Save/Remove actions.

API Keys groups cloud credentials, Hugging Face read tokens, and Civitai
API keys. Existing Hugging Face credentials keep their native storage identity.
Civitai keys use the native OS credential store, with `CIVITAI_API_KEY` then
`CIVITAI_TOKEN` as environment overrides. Civitai keys authenticate supported
workflow model downloads and connection testing. This does not add a model
browser or a purchase flow.

Prompt Enhancement uses centralized API Keys for direct cloud providers. See
Direct cloud prompt enhancement below for the separate local/compatible option.

Civitai uses the documented Bearer header for authentication:
[official authentication documentation](https://github.com/civitai/civitai-developer-docs/blob/main/site/guide/authentication.md).
Download redirects retain credentials only on the same trusted HTTPS origin;
keys never enter download query strings or storage/CDN headers.

### Direct cloud prompt enhancement

API Keys groups Google, OpenAI, OpenRouter, Venice, xAI, Runway, fal.ai, and Anthropic under Cloud Providers, and Hugging
Face plus Civitai under Model Providers (download credentials only). Anthropic
credentials use the same native vault policy with `ORANGE_ANTHROPIC_API_KEY` or
`ANTHROPIC_API_KEY` as environment overrides.

Prompt Enhancement offers direct Google, OpenAI, OpenRouter, Venice, xAI, and Anthropic choices.
These use fixed provider endpoints and keys from API Keys, without editable URL
or key fields in Prompt Enhancement. Fetch Models lists text-model choices for
the selected provider. The separate OpenAI-compatible option defaults to
`http://127.0.0.1:11434/v1` for Ollama and retains a custom URL and optional key
for other local/compatible servers. It does not inherit cloud credentials.
Existing Ollama and custom OpenAI-compatible configurations are recognized in
the editor and retain their connection details when saved. Legacy prompt-only
cloud keys should be saved under API Keys before saving the new cloud selection.
OpenRouter and Venice use their official `/api/v1/chat/completions` endpoints;
Fetch Models lists text-output models only (Venice requests `type=text`). The
media enablement switch does not prevent using the same saved key for prompt
enhancement. No additional provider SDK is required.
xAI uses `api.x.ai/v1/chat/completions`, with text models fetched from the
authenticated `/v1/language-models` endpoint. It also ignores stale custom URLs
and keys when selected as a direct provider.
