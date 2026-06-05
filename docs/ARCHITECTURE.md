# Orange Architecture & Technical Breakdown

Orange is a minimalist, dynamic web frontend wrapper around **ComfyUI**. It aims to replace the complex node-graph interface with a user-friendly, responsive experience that allows anyone to generate, edit, and upscale media via a local ComfyUI instance without understanding the underlying nodes.

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
- **Node Mapping:** Reads the merged config to map frontend inputs (prompt string, uploaded image names, calculated width/height from aspect ratio, and random seeds) directly into the parsed workflow JSON's node fields.
- **Queueing:** Submits the modified workflow to ComfyUI's `/prompt` endpoint.
- **Prompt Enhancement Endpoint (`/api/enhance-prompt`):** Resolves the target system prompt for the specified tool and invokes the configured LLM provider asynchronously to expand user descriptions before generation.

### 2. Status & Progress Tracking (`app/api/status.py`)
- **Server-Sent Events (SSE):** Provides real-time updates to the frontend by multiplexing two sources:
  - **Queue Polling:** Regularly checks ComfyUI's `/queue` endpoint to determine the user's position before generation starts.
  - **WebSocket Listening:** Connects directly to ComfyUI's WebSocket to receive `execution_start`, `executing` (node transitions), `progress` events, and binary preview images.
- **Friendly Naming:** Maps technical ComfyUI node class names (e.g., `KSamplerAdvanced`, `AnimateDiffEvolve`) to user-friendly status strings (e.g., "Generating...", "Generating Video...").

### 3. Admin & Analytics (`app/api/admin.py`)
- **Security:** Protected by an `Authorization` header matched against `adminKey` in the config.
- **Usage Logging:** Reads from the local SQLite `usage_logs.db` to provide dashboard analytics (top tools, top IPs, timeline).
- **System Commands:** Can trigger `git pull` updates and forcefully restart the application server by creating a `RESTART_REQUIRED` lock file that the `run.bat` script watches for.
- **LLM Config & Prompt Admin:** Handles LLM model list retrieval from providers (`POST /api/admin/llm/models`) and prompt management endpoints (`GET /api/admin/prompts/{tool_id}` and `POST /api/admin/prompts/{tool_id}`) ensuring safety using path-traversal prevention.

### 4. Asynchronous LLM Client & Prompt Management (`app/core/llm.py`, `app/core/config.py`)
- **Multi-Provider LLM Client:** `app/core/llm.py` provides an asynchronous connection layer (`call_llm`) supporting OpenAI (and OpenAI-compatible local APIs like LM Studio, llama.cpp, OpenRouter), Ollama, Gemini, and Anthropic.
- **API Key Precedence:** Supports setting API keys directly via environmental variables (`OPENAI_API_KEY`, `GEMINI_API_KEY`, `ANTHROPIC_API_KEY`) or via the Admin settings panel in the frontend (stored securely in `workflows-config.json`). Environment variables always take precedence.
- **Git-Safe System Prompts:** To ensure user modifications to system prompts are not overwritten by `git pull` updates, prompts are split:
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
- Dynamically generates UI inputs (prompt boxes, image dropzones, aspect ratio selectors) based on the currently selected tool's node mappings.
- Handles complex output types (Image, Video, Audio) and initializes appropriate players (e.g., `WaveSurfer.js` for audio visualization).
- Uses `EventSource` to listen to the SSE backend endpoint for live progress bars and preview image updates.
- **Enhance Prompt UI:** Features an interactive "Enhance Prompt" button next to the prompt input. Animates during expansion, allows undoing the enhancement, and automatically resizes the input box dynamically based on text size and available screen height without triggering global page scrollbars.

### 2. Admin Dashboard (`static/admin.html` & `static/admin.js`)
- **Tool Editor:** Provides a drag-and-drop interface for uploading `.json` workflows. It automatically detects and maps nodes like `CLIPTextEncode` or `EmptyLatentImage` to frontend UI elements.
- **Analytics:** Visualizes the `usage_logs.db` data with time-period filtering and CSV export capabilities.
- **LLM Settings Panel:** Allows administrators to enable prompt enhancement, choose an LLM provider, enter API keys and custom base URLs, test connections, fetch available models, and edit system prompts per-tool or globally.

## Data Flow: End-to-End Generation

1. **User Action:** The user selects a tool, enters a prompt.
2. **Prompt Enhancement (Optional):** The user clicks the "Enhance" (✨) button. The frontend calls `POST /api/enhance-prompt` with the current prompt and tool ID. The backend resolves the system prompt, invokes `llm.py` asynchronously to generate the expanded prompt, and returns it to the generator textarea with an option to undo.
3. **Submission:** The user clicks "Generate", and `app.js` sends a `multipart/form-data` request to `/api/generate` (with the raw or enhanced prompt).
4. **Processing:** `generate.py` validates inputs, uploads any images to ComfyUI, patches the workflow JSON based on mapped nodes, and queues the job.
5. **Monitoring:** `app.js` opens an SSE connection to `/api/status`. `status.py` listens to ComfyUI's websocket and yields progress events back to the frontend.
6. **Retrieval:** Once completed, `app.js` requests the final output from `/api/output`, which fetches the file from ComfyUI, strips metadata (if it's an image), and serves it to the browser for display/download.
