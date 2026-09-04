# Orange Architecture & Technical Breakdown

Orange is a minimalist, dynamic web frontend wrapper around **ComfyUI**. It aims to replace the complex node-graph interface with a user-friendly, responsive experience that allows anyone to generate, edit, and upscale media via a local ComfyUI instance without understanding the underlying nodes.

## Core Product Boundary

Orange intentionally separates **workflow engineering** from **generation UX**.

The user-facing Orange interface should expose only the decisions that a normal user genuinely needs to make for each generation. The ComfyUI workflow author should absorb the technical complexity inside the workflow itself.

### Belongs in the ComfyUI workflow

Examples include:
- Model and checkpoint selection
- Sampler and scheduler choices
- Steps, CFG, denoise, guidance, and other tuning values
- LoRAs and their strengths
- Negative prompts and conditioning logic
- ControlNet / adapter internals
- Node-specific implementation details
- Internal resolution transforms
- Video/audio implementation settings that do not need user choice
- Custom-node complexity

### Belongs in Orange

Orange should expose semantic, user-facing choices such as:
- Prompt
- Image / reference image
- A second reference image when the tool genuinely requires it
- Aspect ratio or an intentionally curated resolution choice
- Generate
- Output display appropriate to the tool (image, video, audio, or text)

A new frontend mapping is **not** automatically desirable just because a ComfyUI node has another configurable value. New mappings should be rare and should represent a real, recurring user decision that cannot reasonably be fixed or automated by the workflow engineer.

This constraint is intentional. Orange is not trying to become a generic ComfyUI form builder, parameter editor, or replacement for ComfyUI itself.

## Engineering Principle: Smarter Internals, Simple Surface

Orange can become significantly more capable without adding more controls to the Generate page.

Preferred areas for complexity include:
- Workflow validation and preflight checks
- Automatic mapping assistance for the administrator
- Backend health monitoring and routing
- Queue recovery and transient-error handling
- Model/custom-node dependency diagnostics
- Better error translation from ComfyUI into useful user messages
- Persistent job/history reliability
- Multi-backend scheduling
- Admin-side workflow diagnostics

These improvements should primarily help the **workflow engineer or administrator**. The end user should continue seeing a deliberately small interface.

A useful architectural test for new features is:

> Does the user actually need to decide this every generation, or can the workflow engineer decide it once inside ComfyUI?

If the engineer can decide it, it normally should not become an Orange control.

When extending `nodeMapping`, treat the existing mapping names as a curated product API rather than an open-ended list. Add a new mapping type only when a new first-class user interaction is intentionally being added to Orange.

## Project Structure

The project has recently been refactored into a more professional, modular layout:

```
Orange/
│
├── app/                      # Backend FastAPI Application
│   ├── main.py               # Application entry point, mounts static, registers routers
│   ├── api/                  # API Route Handlers
│   │   ├── admin.py          # Admin dashboard API (usage, config, system updates, prompt/LLM management)
│   │   ├── generate.py       # Generation logic (submits prompts, handles uploads, prompt enhancement)
│   │   ├── status.py         # SSE connection for live queue and generation progress
│   │   └── workflows.py      # Retrieves available tools and aspect ratios
│   └── core/                 # Core utilities
│       ├── config.py         # In-memory config caching, prompt resolution, and workflow parsing
│       ├── database.py       # SQLite logic for usage logging
│       ├── llm.py            # Asynchronous multi-provider LLM connector
│       └── utils.py          # Image manipulation (metadata stripping)
│
├── static/                   # Frontend UI Files
│   ├── index.html            # Main User Generator Interface (with Prompt Enhancement)
│   ├── admin.html            # Admin Dashboard Interface (with LLM Settings & Prompt Editor)
│   ├── app.js                # Frontend logic for the generator (SSE, prompt enhance animation)
│   ├── admin.js              # Frontend logic for the admin panel (Tool Settings, Prompts management)
│   ├── styles.css            # Common styling (Glassmorphism, custom scrollbars)
│   ├── tailwind.min.js       # Runtime Tailwind CSS configuration
│   └── lucide.min.js         # Icons
│
├── workflows/                # User Configuration & Workflows
│   ├── defaults/             # Tracked default workflows, configs, and prompts
│   │   ├── prompts/          # Tracked default system prompts (.txt files)
│   │   ├── workflows-config.json
│   │   └── *.json
│   ├── prompts/              # User's local system prompt overrides (gitignored)
│   ├── workflows-config.json # User's local override configuration
│   └── *.json                # User's local workflows
│
├── usage_logs.db             # SQLite database storing generation requests/IPs
├── run.bat                   # Windows startup & environment script
├── run.sh                    # Linux/Mac startup & environment script
└── requirements.txt          # Python dependencies
```

## Backend Breakdown

The backend is built using **FastAPI** to provide a fast, asynchronous middle-layer between the end-user and the ComfyUI server.

### 1. Generation Pipeline (`app/api/generate.py`)
- **Configuration Merging:** `app/core/config.py` intelligently loads `workflows/defaults/workflows-config.json` and then merges `workflows/workflows-config.json` on top. This allows the backend to automatically receive new default features while preserving user modifications (such as custom `tools` or `adminKey`).
- **Image Uploads:** Receives `image` or `image2` from the frontend and forwards them to ComfyUI's `/upload/image` endpoint using `httpx`.
- **Node Mapping:** Reads the merged config to map Orange's small semantic input set (prompt string, uploaded image names, calculated width/height from aspect ratio, and random seeds) directly into the parsed workflow JSON's node fields.
- **Queueing:** Submits the modified workflow to ComfyUI's `/prompt` endpoint.
- **Prompt Enhancement Endpoint (`/api/enhance-prompt`):** Resolves the target system prompt for the specified tool and invokes the configured LLM provider asynchronously to expand user descriptions before generation.

The constrained mapping layer is a product boundary, not an incomplete generic schema. Workflow-specific parameters should normally remain fixed or automated inside the ComfyUI graph.

### 2. Status & Progress Tracking (`app/api/status.py`)
- **Server-Sent Events (SSE):** Provides real-time updates to the frontend by multiplexing two sources:
  - **Queue Polling:** Regularly checks ComfyUI's `/queue` endpoint to determine the user's position before generation starts.
  - **WebSocket Listening:** Connects directly to ComfyUI's WebSocket to receive `execution_start`, `executing` (node transitions), `progress` events, and binary preview images.
- **Friendly Naming:** Maps technical ComfyUI node class names (e.g., `KSamplerAdvanced`, `AnimateDiffEvolve`) to user-friendly status strings (e.g., "Generating...", "Generating Video...").

### 3. Admin & Analytics (`app/api/admin.py`)
- **Security:** Protected by an `Authorization` header matched against `adminKey` in the config.
- **Usage Logging:** Reads from the local SQLite `usage_logs.db` to provide dashboard analytics (top tools, top IPs, timeline).
- **System Commands:** Can trigger git updates and restart the application server through a `RESTART_REQUIRED` lock file watched by the launcher scripts.
- **LLM Config & Prompt Admin:** Handles LLM model list retrieval from providers (`POST /api/admin/llm/models`) and prompt management endpoints (`GET /api/admin/prompts/{tool_id}` and `POST /api/admin/prompts/{tool_id}`) ensuring safety using path-traversal prevention.

The Admin area is the preferred place for engineering-facing diagnostics. Workflow preflight, mapping validation, missing-node warnings, backend compatibility, and dependency checks should live here rather than appearing as extra controls on the Generate page.

### 4. Asynchronous LLM Client & Prompt Management (`app/core/llm.py`, `app/core/config.py`)
- **Multi-Provider LLM Client:** `app/core/llm.py` provides an asynchronous connection layer (`call_llm`) supporting OpenAI (and OpenAI-compatible local APIs like LM Studio, llama.cpp, OpenRouter), Ollama, Gemini, and Anthropic.
- **API Key Precedence:** Supports setting API keys directly via environmental variables (`OPENAI_API_KEY`, `GEMINI_API_KEY`, `ANTHROPIC_API_KEY`) or via the Admin settings panel in the frontend. Environment variables always take precedence.
- **Git-Safe System Prompts:** To ensure user modifications to system prompts are not overwritten by git updates, prompts are split:
  - `workflows/defaults/prompts/`: Houses the original system prompts tracked in the repository (e.g., `global.txt`, `z-image.txt`, `qwen-2512.txt`).
  - `workflows/prompts/`: Holds user-modified system prompts. This directory is gitignored to protect user configurations from being overwritten. On startup or when "Restore Defaults" is clicked, any missing prompts are copied from `defaults/prompts/` to `prompts/`.
- **System Prompt Resolution Order:** When fetching the system prompt for a tool:
  1. Active tool-specific prompt override (`workflows/prompts/{tool_id}.txt`).
  2. Default tool-specific prompt override (`workflows/defaults/prompts/{tool_id}.txt`).
  3. Active global prompt override (`workflows/prompts/global.txt`).
  4. Default global prompt override (`workflows/defaults/prompts/global.txt`).
  5. Hardcoded fallback global prompt.

## Frontend Breakdown

The frontend uses Vanilla HTML/JS with **TailwindCSS** for rapid, responsive styling. It prioritizes a "glassmorphism" aesthetic with a dark theme.

### 1. The Generator (`static/index.html` & `static/app.js`)
- Dynamically generates the deliberately small set of Orange inputs (prompt boxes, image dropzones, aspect ratio selectors) based on the currently selected tool's node mappings.
- Handles complex output types (Image, Video, Audio) and initializes appropriate players (e.g., `WaveSurfer.js` for audio visualization).
- Uses `EventSource` to listen to the SSE backend endpoint for live progress bars and preview image updates.
- **Enhance Prompt UI:** Features an interactive "Enhance Prompt" button next to the prompt input. Animates during expansion, allows undoing the enhancement, and automatically resizes the input box dynamically based on text size and available screen height without triggering global page scrollbars.

The generator should remain intentionally simple even as backend/admin capabilities grow.

### 2. Admin Dashboard (`static/admin.html` & `static/admin.js`)
- **Tool Editor:** Provides a drag-and-drop interface for uploading `.json` workflows. It automatically detects and maps nodes like `CLIPTextEncode` or `EmptyLatentImage` to Orange's supported semantic frontend inputs.
- **Analytics:** Visualizes the `usage_logs.db` data with time-period filtering and CSV export capabilities.
- **LLM Settings Panel:** Allows administrators to enable prompt enhancement, choose an LLM provider, enter API keys and custom base URLs, test connections, fetch available models, and edit system prompts per-tool or globally.

## Workflow Preflight Direction

A future workflow-preflight system should help the engineer answer questions such as:

```text
Workflow: Klein Edit

✓ Prompt mapping -> node 756 / text
✓ Image mapping -> node 734 / image
✓ Seed mapping -> node 748 / noise_seed

✓ Required node types available on Server 1
⚠ Server 2 missing: SeedVR2VideoUpscaler

Ready on 1 of 2 backends
```

Preflight should validate and explain the workflow. It should **not** expose the missing technical parameters to the end user.

Useful checks include:
- Mapped node IDs exist in the workflow
- Mapped fields exist on those nodes
- Referenced workflow files are valid API workflows
- Required node classes are installed on each configured ComfyUI backend
- A workflow is compatible with at least one configured backend
- Required models/custom nodes can be identified when ComfyUI exposes enough metadata
- Friendly warnings are shown to the administrator before a broken tool reaches users

## Data Flow: End-to-End Generation

1. **User Action:** The user selects a tool and provides only the semantic inputs that tool intentionally exposes.
2. **Prompt Enhancement (Optional):** The user clicks the "Enhance" (✨) button. The frontend calls `POST /api/enhance-prompt` with the current prompt and tool ID. The backend resolves the system prompt, invokes `llm.py` asynchronously to generate the expanded prompt, and returns it to the generator textarea with an option to undo.
3. **Submission:** The user clicks "Generate", and `app.js` sends a `multipart/form-data` request to `/api/generate` (with the raw or enhanced prompt and any intentionally exposed media inputs).
4. **Processing:** `generate.py` validates inputs, uploads any images to ComfyUI, patches the workflow JSON based on mapped nodes, and queues the job.
5. **Monitoring:** `app.js` opens an SSE connection to `/api/status`. `status.py` listens to ComfyUI's websocket and yields progress events back to the frontend.
6. **Retrieval:** Once completed, `app.js` requests the final output from `/api/output`, which fetches the file from ComfyUI, strips metadata when configured, and serves it to the browser for display/download.

## Direction for Future Development

Future work should favor operational intelligence over frontend configuration depth.

### Preferred
- Admin workflow preflight and compatibility diagnostics
- Better backend health monitoring and routing
- Persistent job/history reliability
- Better recovery from ComfyUI disconnects
- Clearer end-user error messages derived from technical backend failures
- Dependency/model/custom-node diagnostics for workflow engineers
- Better auto-mapping assistance for the existing semantic input types

### Generally avoid
- A generic arbitrary-control schema
- Automatically exposing every configurable workflow value
- Sampler/model/CFG/steps/LoRA dropdowns on the Generate page
- Recreating ComfyUI's advanced controls in Orange
- Adding a user-facing mapping merely because a node supports a parameter

When a truly new user interaction is needed (for example, a mask for an inpainting tool or duration for a tool where duration is central to the user's intent), it can be added deliberately as a first-class Orange concept rather than opening the entire node graph to the frontend.
