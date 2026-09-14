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

`nodeMapping` is therefore a curated product API, not an unfinished generic schema.

> Smarter internals, simpler surface.

## High-Level Runtime

```text
Browser
  |
  |  semantic inputs only
  v
FastAPI / Orange
  |
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
  +-- /upload/image
  +-- /prompt
  +-- /queue
  +-- /history
  +-- websocket progress
```

The selected backend is recorded with the generation so status and output retrieval continue talking to the machine that actually accepted the job.

## Project Structure

```text
Orange/
├── app/
│   ├── main.py
│   ├── api/
│   │   ├── generation_v2.py      # active safe /api/generate route
│   │   ├── outputs.py            # normalized output retrieval
│   │   ├── status.py             # queue/progress/status handling
│   │   ├── preflight.py          # admin workflow/backend compatibility API
│   │   ├── backend_status.py     # admin backend health surface
│   │   ├── workflow_assets.py    # fixed workflow asset API
│   │   ├── personalization.py    # theme/branding API
│   │   ├── llm_api.py            # hardened LLM/admin routes
│   │   ├── db_admin.py           # SQLite backup/restore
│   │   └── admin.py              # admin config/analytics/system endpoints
│   └── core/
│       ├── backends.py            # health state, queue-aware selection, compatibility cache
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
├── static/
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
│   ├── defaults/
│   ├── prompts/
│   ├── branding/
│   ├── personalization.json
│   └── workflows-config.json
├── tests/
├── run.bat
├── run.sh
└── requirements.txt
```

Some older route implementations remain in the repository for compatibility, but `app/main.py` deliberately registers the hardened routes first. Route-precedence regression tests protect the active generation, output, LLM, and database paths from accidentally falling back to their legacy implementations.

## Generation Pipeline

The active submission path is `app/api/generation_v2.py`.

### 1. Resolve tool and workflow

Orange loads the tool configuration, its API workflow, and `nodeMapping`. It calculates a **workflow compatibility key** from the workflow filename, workflow JSON, and mapping. Changing the workflow or mapping changes the key.

### 2. Validate/read user inputs once

Uploaded images are validated for type/size/content and read into bytes before backend selection. This matters because a retry cannot safely depend on an already-consumed upload stream.

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

The short-lived `active_requests` reservation bridges the gap between Orange accepting a request and ComfyUI's next `/queue` response, reducing the chance that a burst of simultaneous jobs all choose the same apparently-empty backend.

### 4. Stage fixed and user media

Orange starts every backend attempt from a fresh deep copy of the base workflow.

- **Workflow Assets** are Orange-managed fixed files required by unmapped image nodes. They are uploaded to the backend chosen for this attempt.
- **User images** are uploaded to that same backend.
- The workflow is rewritten with the backend-side filenames.

Backend-specific filenames from a failed attempt never leak into the next backend attempt.

### 5. Apply semantic mappings

Orange patches only its supported semantic inputs: prompt, image(s), dimensions, seed, and similar first-class concepts.

### 6. Submit safely

`app/core/submission.py` classifies failures based on whether retrying can be done without risking duplicate work.

Examples:

- connection failure before submission: retryable, backend health failure
- backend HTTP 5xx: retryable, backend health failure
- explicit workflow rejection/4xx: retryable on another backend, **does not** make the server globally unhealthy
- read timeout after the request may have been accepted: not automatically retried, because a second submission could duplicate the generation

A successful response must contain a `prompt_id`.

### 7. Persist backend ownership

The accepted `prompt_id` and final backend URL are written to SQLite. Later status/output calls use that association instead of assuming the first configured ComfyUI server owns the job.

## Workflow Preflight and Compatibility Routing

Preflight is implemented, not a future concept.

`app/core/preflight.py` validates Orange's local workflow/mapping and queries each reachable ComfyUI backend's `object_info` to compare the workflow with that backend's actual capabilities.

It detects issues such as:

- UI-format JSON instead of API-format JSON
- mapped node IDs that do not exist
- mapped fields that do not exist
- missing custom-node classes
- missing required inputs
- enumerated values/models unavailable on a backend
- unmanaged image inputs
- managed workflow assets that Orange will supply

### UI severity is not the same as routing eligibility

A backend can be healthy but unable to run one workflow.

For example, `value_unavailable` (such as a missing checkpoint) remains a **yellow Admin warning** because the server itself is not broken. The preflight API separately marks that backend `routing_compatible: false`, and the compatibility cache excludes it when routing that workflow.

This means:

```text
Backend 1: healthy, missing model X  -> warning, not routable for Workflow A
Backend 2: healthy, has model X      -> routable for Workflow A
```

Backend 1 can still run other workflows.

Preflight also returns `summary.routable_backends` so the Admin view can distinguish general reachability from actual workflow placement options.

## Backend Health vs Workflow Failure

These concepts intentionally remain separate:

- **Health failure** means the server/network appears unavailable or failing generally.
- **Workflow incompatibility** means that backend cannot satisfy this particular workflow.
- **Submission rejection** may reveal incompatibility that was not known from cached Preflight data.

A workflow-specific rejection can fail over to another backend without poisoning the first backend's global health state. Regression tests cover this two-backend path at the actual generation handler level.

## Status and Output Handling

`app/api/status.py` combines ComfyUI queue/history/websocket information into user-facing generation status.

The output layer normalizes ComfyUI outputs across image, video, audio, and text. Image metadata stripping is performed before serving user-facing images where applicable.

Because Orange stores the backend that accepted each prompt, status and output retrieval can target the correct ComfyUI machine in a multi-backend deployment.

## Workflow Assets

Fixed reference images are deployment-owned assets, not fake user uploads.

The workflow asset subsystem namespaces files by workflow so identically named assets from different tools do not collide. During submission, Orange discovers managed asset references, uploads each file once per backend attempt, and rewrites every matching workflow input.

Mapped user-image nodes are excluded from static-asset discovery.

## Configuration and User-Owned State

Tracked defaults live in `workflows/defaults/`. Active local configuration lives in `workflows/` and is kept separate so updates do not overwrite deployment-specific state.

Examples of user-owned state include:

- `workflows/workflows-config.json`
- `workflows/prompts/`
- `workflows/personalization.json`
- `workflows/branding/`
- workflow assets

Configuration validation rejects malformed backend URLs, unsafe workflow paths, duplicate tool IDs, invalid mappings, and other broken shapes before they can become runtime surprises.

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

Built-in themes are defined in `static/themes/presets.json`. Their mascot/head variants are explicit editable SVG files under `static/theme-assets/logos/`; CI verifies that these remain valid assets without depending on editor-specific SVG IDs.

White-label state is stored under `workflows/personalization.json` and `workflows/branding/` so application updates do not overwrite deployment branding.

A small pre-paint theme bootstrap prevents a flash of Classic styling when reloading under another theme. Runtime integrations use the explicit `orange:personalization-applied` event rather than a document-wide mutation observer.

See [PERSONALIZATION.md](PERSONALIZATION.md).

## Frontend

The user interface is intentionally vanilla HTML/JavaScript with a bundled Tailwind browser runtime and local Lucide bundle. The current styling system is stable and self-contained, but Tailwind's browser-build warning remains known console noise; replacing it with a compiled CSS toolchain would be a separate frontend build-system migration rather than part of runtime routing hardening.

The generator remains small even as Admin/operations code grows.

## Deployment

`run.bat` and `run.sh`:

1. ensure Python/venv availability
2. create the Orange virtual environment on first run
3. hash `requirements.txt`
4. resync Python dependencies only when that hash changes
5. optionally offer the default model downloader on a fresh install
6. run Uvicorn on port `7070`
7. watch the `RESTART_REQUIRED` sentinel so an Admin-triggered restart can relaunch cleanly

Set `ORANGE_VERBOSE_LOGS=1` to enable normal Uvicorn access logging during troubleshooting.

## Testing Strategy

CI runs on supported Python versions and checks:

- Python compilation
- JavaScript syntax for the tracked frontend modules
- theme manifest JSON validity
- unit/regression tests

Coverage includes configuration safety, SQLite backup/restore, output normalization, LLM validation, personalization persistence/assets, preflight semantics, workflow assets, backend scoring/compatibility, route precedence, submission retry safety, and a two-backend generation failover regression.

## Development Direction After Stable v1

Orange should now be **dogfooded before broadening the feature set**.

Good future work should be driven by failures observed in real use across actual ComfyUI machines. Favor:

- better Admin diagnostics
- clearer workflow dependency explanations
- operational reliability
- status/history correctness
- targeted compatibility improvements

Avoid turning Orange into a generic node-control surface. The fastest way to make the product harder to operate is to push workflow-engineering decisions back onto ordinary users.
