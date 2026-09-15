# Orange Architecture & Technical Breakdown

Orange is a deliberately small web frontend for **ComfyUI**. Its job is not to recreate the ComfyUI editor. It turns engineer-built API workflows into simple tools for people who should not need to understand nodes, models, samplers, or backend topology.

## Product Boundary

Orange separates **workflow engineering** from **generation UX**.

### Keep inside the ComfyUI workflow

- model/checkpoint choice
- sampler and scheduler
- steps, CFG/guidance, denoise
- LoRAs and strengths
- negative conditioning
- ControlNet/adapter internals
- custom-node tuning
- implementation-specific video/audio settings
- other values the workflow engineer can decide once

### Expose through Orange only when it is a real user decision

- prompt
- image/reference image
- second image when genuinely required
- curated aspect ratio/resolution
- Generate
- the appropriate output presentation

`nodeMapping` is a curated product API, not an unfinished generic schema.

> Smarter internals, simpler surface.

## High-Level Runtime

```text
Browser
  |
  | semantic inputs only
  v
FastAPI / Orange
  |
  +-- first-run onboarding
  +-- curated workflow packs
  +-- config + tool mapping
  +-- workflow assets
  +-- workflow compatibility cache
  +-- backend health/load routing
  +-- safe submission/failover
  +-- usage/job database
  |
  v
Selected ComfyUI backend
  |
  +-- /object_info
  +-- /system_stats
  +-- /upload/image
  +-- /prompt
  +-- /queue
  +-- /history
  +-- websocket progress
```

The selected backend is recorded with each generation so status and output retrieval continue talking to the machine that actually accepted the job.

## Project Structure

```text
Orange/
├── app/
│   ├── main.py
│   ├── api/
│   │   ├── setup.py              # first-run setup and pack onboarding
│   │   ├── generation_v2.py      # active safe /api/generate route
│   │   ├── outputs.py            # normalized output retrieval
│   │   ├── status.py             # queue/progress/status handling
│   │   ├── preflight.py          # workflow/backend compatibility API
│   │   ├── backend_status.py     # backend health surface
│   │   ├── workflow_assets.py    # fixed workflow asset API
│   │   ├── personalization.py    # theme/branding API
│   │   ├── llm_api.py            # hardened LLM/admin routes
│   │   ├── db_admin.py           # SQLite backup/restore
│   │   └── admin.py              # admin config/analytics/system/pack endpoints
│   └── core/
│       ├── onboarding.py          # fresh-install state and install-mode detection
│       ├── workflow_packs.py      # dependency manifests, hardware selection, materialization
│       ├── backends.py            # health, queue-aware selection, compatibility cache
│       ├── preflight.py           # workflow/object_info validation
│       ├── submission.py          # safe Comfy request classification
│       ├── workflow_assets.py     # managed fixed-image discovery/storage
│       ├── outputs.py             # output normalization helpers
│       ├── config.py              # config/default merging and workflow loading
│       ├── config_validation.py   # config validation
│       ├── database.py            # usage/job SQLite storage and migrations
│       ├── personalization.py     # personalization validation/persistence
│       ├── public_config.py       # safe public config projection
│       ├── llm.py                 # multi-provider async LLM client
│       └── rate_limit.py          # request limiting helpers
├── workflow-packs/                # curated pack manifests
├── static/
│   ├── setup.html / setup.js      # first-run browser wizard
│   ├── index.html / app.js
│   ├── admin.html / admin.js
│   ├── preflight.js
│   ├── backend-status.js
│   ├── workflow-assets.js
│   ├── personalization.js
│   ├── theme-runtime.js
│   ├── theme-effects.js
│   ├── themes/presets.json
│   └── theme-assets/
├── workflows/
│   ├── defaults/                  # tracked curated/default workflows
│   ├── prompts/
│   ├── branding/
│   ├── personalization.json
│   └── workflows-config.json      # active local configuration
├── tests/
├── run.bat
├── run.sh
└── requirements.txt
```

Some older route implementations remain for compatibility, but `app/main.py` deliberately registers the hardened routes first. Route-precedence regression tests protect the active generation, output, LLM, and database paths from accidentally falling back to legacy implementations.

## First-Run Onboarding

A genuinely fresh install is marked setup-pending and redirects `/` and `/admin` to `/setup`.

Existing installations are migrated as already configured so upgrading Orange does not unexpectedly replace active configuration or force the administrator through onboarding again.

Fresh setup is localhost-only by default. `ORANGE_ALLOW_REMOTE_SETUP=1` can explicitly allow remote first-run setup when required.

The wizard:

1. connects to ComfyUI
2. verifies `/object_info`
3. reads `/system_stats`
4. detects/accepts a writable model location when available
5. installs the Z-Image starter and any selected optional curated packs
6. materializes hardware-selected model filenames into active workflow copies
7. runs Workflow Preflight
8. only exposes packs that are routable
9. creates the administrator password
10. enters the normal Generate UI

A fresh process initially receives a random bootstrap Admin credential, so new deployments do not expose the historical tracked `orangeadmin` template value as a usable first-run secret.

## Curated Workflow Packs

Orange's curated packs package known-good ComfyUI API workflows together with their Orange mapping and model dependency metadata.

Current curated packs are:

- **Z-Image Turbo** — default starter text-to-image
- **Krea 2 Turbo** — advanced text-to-image; intentionally keeps `wan_2.1_vae.safetensors`
- **Klein 9B Turbo** — instruction-based image editing
- **SeedVR2 7B Upscale** — native-node SeedVR2 image upscaling

The pack system does not make Orange a generic model manager. It only installs the dependencies declared by curated Orange tools when Orange has filesystem access to that backend's model storage.

### Hardware-aware model selection

During browser onboarding and Admin pack installation, `app/core/workflow_packs.py` reads normalized information from ComfyUI `/system_stats`, including device name/type, VRAM, ComfyUI version, and PyTorch version.

The current policy is conservative:

- supported modern NVIDIA/CUDA + ComfyUI builds prefer published **INT8 ConvRot** variants
- larger models fall back to tested **FP8** variants when INT8 is not selected
- **BF16/FP16** is used where the pack provides it and available memory makes the higher-precision option reasonable
- AMD/ROCm currently avoids automatic INT8 ConvRot selection and uses the pack's tested FP8/BF16/FP16 fallback

Variant selection is per dependency; not every model family publishes every precision.

Orange rewrites only model filename fields explicitly declared by the pack manifest. Known-good graph decisions remain intact.

See [WORKFLOW_PACKS.md](WORKFLOW_PACKS.md) for the pack format and maintainer workflow.

## Per-Backend Model Storage

A configured ComfyUI server may include an optional `modelsRoot` path.

This path means Orange can write model files for that backend. It can point at:

- local `ComfyUI/models`
- Stability Matrix model storage
- a Pinokio-managed ComfyUI model directory
- a writable network/shared model directory

Remote backends without an accessible filesystem path remain fully usable for health checks, Preflight, routing, and generation. Orange simply does not claim it can install missing models there.

## Generation Pipeline

The active submission path is `app/api/generation_v2.py`.

### 1. Resolve tool and workflow

Orange loads the tool configuration, API workflow, and `nodeMapping`. It calculates a **workflow compatibility key** from the workflow filename, workflow JSON, and mapping. Changing the workflow or mapping changes the key.

### 2. Validate/read user inputs once

Uploaded images are validated for type/size/content and read into bytes before backend selection. A retry therefore does not depend on an already-consumed upload stream.

A random seed is also generated once per Orange request. If failover occurs, the retry keeps the same seed rather than silently becoming a different creative request.

### 3. Select a backend

`app/core/backends.py` maintains lightweight state for configured ComfyUI servers:

- health
- running and pending queue counts
- probe latency
- configured priority
- short-lived Orange active-request reservations
- consecutive failures/circuit state
- per-workflow compatibility learned from Preflight

Healthy compatible candidates are scored primarily by effective queue depth, then configured priority, latency, and URL for deterministic tie-breaking.

The short-lived `active_requests` reservation bridges the gap between Orange accepting a request and ComfyUI's next `/queue` response, reducing burst pileups on one apparently empty backend.

### 4. Stage fixed and user media

Orange starts every backend attempt from a fresh deep copy of the base workflow.

- **Workflow Assets** are Orange-managed fixed files required by unmapped image nodes. They are uploaded to the backend chosen for the attempt.
- **User images** are uploaded to that same backend.
- The workflow is rewritten with backend-side filenames.

Backend-specific filenames from a failed attempt never leak into the next attempt.

### 5. Apply semantic mappings

Orange patches only supported semantic inputs: prompt, image(s), dimensions, seed, and similar first-class concepts.

### 6. Submit safely

`app/core/submission.py` classifies failures based on whether retrying can be done without risking duplicate work.

Examples:

- connection failure before submission: retryable, backend health failure
- backend HTTP 5xx: retryable, backend health failure
- explicit workflow rejection/4xx: retryable on another backend, does **not** make the server globally unhealthy
- read timeout after a request may have been accepted: not blindly retried because a second submission could duplicate the generation

A successful response must contain a `prompt_id`.

### 7. Persist backend ownership

The accepted `prompt_id` and final backend URL are written to SQLite. Later status/output calls use that association instead of assuming the first configured ComfyUI server owns the job.

## Workflow Preflight and Compatibility Routing

`app/core/preflight.py` validates Orange's local workflow/mapping and queries each reachable backend's `object_info` to compare the workflow with actual backend capabilities.

It detects issues such as:

- UI-format JSON instead of API-format JSON
- mapped node IDs/fields that do not exist
- missing custom-node classes
- missing required inputs
- enumerated values/models unavailable on a backend
- unmanaged image inputs
- managed Workflow Assets that Orange will supply

### UI severity is not routing eligibility

A backend can be healthy but unable to run one workflow.

For example, `value_unavailable` such as a missing checkpoint remains a **yellow Admin warning** because the server itself is not broken. The compatibility cache still excludes that backend when routing that workflow.

```text
Backend 1: healthy, missing model X  -> warning, not routable for Workflow A
Backend 2: healthy, has model X      -> routable for Workflow A
```

Backend 1 can still run other workflows.

Curated pack installers use this same Preflight gate before adding a pack as an active tool.

## Backend Health vs Workflow Failure

These concepts remain separate:

- **Health failure** — server/network appears unavailable or failing generally
- **Workflow incompatibility** — backend cannot satisfy one workflow
- **Submission rejection** — may reveal incompatibility not known from cached Preflight data

A workflow-specific rejection can fail over without poisoning the backend's global health state.

## Status and Output Handling

`app/api/status.py` combines ComfyUI queue/history/websocket information into user-facing generation status.

The output layer normalizes image, video, audio, and text results. Image metadata stripping is performed before serving user-facing images where applicable.

Because Orange stores the backend that accepted each prompt, status and output retrieval can target the correct ComfyUI machine in a multi-backend deployment.

## Workflow Assets

Fixed reference images are deployment-owned assets, not fake user uploads.

The subsystem namespaces files by workflow so identically named assets from different tools do not collide. During submission, Orange discovers managed asset references, uploads each file once per backend attempt, and rewrites every matching workflow input.

Mapped user-image nodes are excluded from static-asset discovery.

## Configuration and User-Owned State

Tracked defaults live in `workflows/defaults/`. Active local configuration lives in `workflows/` and remains separate so updates do not overwrite deployment-specific state.

Examples include:

- `workflows/workflows-config.json`
- active materialized workflow copies
- `workflows/prompts/`
- `workflows/personalization.json`
- `workflows/branding/`
- Workflow Assets

Configuration validation rejects malformed backend URLs, unsafe workflow paths, duplicate tool IDs, invalid mappings, and other broken shapes.

## Database Reliability

Orange uses SQLite for generation/usage records.

The active database uses WAL mode and additive schema migrations. Backup uses SQLite's backup API to produce a transactionally consistent, self-contained file rather than copying a live WAL-backed database blindly.

Restore validates the uploaded database, restores through SQLite, and immediately reapplies current additive migrations so older Orange backups remain usable.

Optional usage retention can be controlled with `ORANGE_USAGE_RETENTION_DAYS`; `0` keeps records indefinitely.

## LLM Prompt Enhancement

Prompt enhancement is optional and intentionally separate from generation routing.

`app/core/llm.py` supports OpenAI/OpenAI-compatible endpoints, Ollama, Gemini, and Anthropic. Provider validation prevents unsafe/malformed base URLs and avoids leaking keys in provider errors. Environment variables can override configured cloud API keys.

Tool-specific and global prompt files use a tracked-default/local-override pattern so Git updates do not overwrite deployment-specific prompts.

## Personalization

Personalization changes presentation without changing the generation contract.

Built-in themes are defined in `static/themes/presets.json`. Mascot/head variants are explicit editable SVG files under `static/theme-assets/logos/`.

White-label state is stored under `workflows/personalization.json` and `workflows/branding/` so application updates do not overwrite deployment branding.

A small pre-paint bootstrap prevents a flash of Classic styling when reloading under another theme.

See [PERSONALIZATION.md](PERSONALIZATION.md).

## Frontend

The user interface remains vanilla HTML/JavaScript with a bundled Tailwind browser runtime and local Lucide bundle. Tailwind's browser-build warning remains known console noise; replacing it with compiled CSS would be a separate frontend build-system migration.

The generator remains intentionally small even as Admin/operations code grows.

## Deployment

### Manual/GitHub

`run.bat` and `run.sh`:

1. ensure Python/venv availability
2. create the Orange virtual environment on first run
3. hash `requirements.txt`
4. resync dependencies only when that hash changes
5. launch Uvicorn on port `7070`
6. watch `RESTART_REQUIRED` so an Admin-triggered restart can relaunch cleanly

They no longer run a separate terminal model-downloader prompt. Fresh model/tool onboarding happens in the browser wizard.

Set `ORANGE_VERBOSE_LOGS=1` to enable normal Uvicorn access logging during troubleshooting.

### Pinokio

The companion `orange-pinokio` repository supports:

- **Orange + ComfyUI** — installs a managed local ComfyUI and starts both processes together
- **Orange Only** — installs Orange for an existing ComfyUI deployment

The managed installer passes known ComfyUI/model paths to Orange but intentionally does not pre-download one fixed Z-Image model precision. Orange starts ComfyUI, reads `/system_stats`, and uses the same hardware-aware pack selection as manual installs.

Pinokio is an enhanced deployment mode, not an Orange runtime dependency.

## Testing Strategy

CI runs on Python 3.10 and 3.12 and checks:

- Python compilation
- JavaScript syntax
- theme and every workflow-pack manifest JSON
- unit/regression tests

Coverage includes onboarding migration/security, workflow-pack catalog and precision selection, pack materialization, Admin pack installation, Krea's intentional Wan VAE, SeedVR2 native nodes, configuration safety, SQLite backup/restore, output normalization, LLM validation, personalization, Preflight semantics, workflow assets, backend scoring/compatibility, route precedence, submission retry safety, and two-backend generation failover.

## Development Direction

Orange should continue to be dogfooded before broadening the feature set.

Favor:

- better onboarding and Admin diagnostics
- clearer dependency explanations
- operational reliability
- status/history correctness
- targeted compatibility improvements

Avoid turning Orange into a generic node-control or model-management surface. The fastest way to make the product harder to operate is to push workflow-engineering decisions back onto ordinary users.