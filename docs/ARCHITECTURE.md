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
│   │   ├── admin.py          # Admin dashboard API (usage, config, system updates)
│   │   ├── generate.py       # Generation logic (submits prompts, handles uploads)
│   │   ├── status.py         # SSE connection for live queue and generation progress
│   │   └── workflows.py      # Retrieves available tools and aspect ratios
│   └── core/                 # Core utilities
│       ├── config.py         # In-memory config caching and workflow parsing
│       ├── database.py       # SQLite logic for usage logging
│       └── utils.py          # Image manipulation (metadata stripping)
│
├── static/                   # Frontend UI Files
│   ├── index.html            # Main User Generator Interface
│   ├── admin.html            # Admin Dashboard Interface
│   ├── app.js                # Frontend logic for the generator (SSE parsing, UI state)
│   ├── admin.js              # Frontend logic for the admin panel (Tool Editor, Analytics)
│   ├── styles.css            # Common styling (Glassmorphism, animations)
│   ├── tailwind.min.js       # Runtime Tailwind CSS configuration
│   └── lucide.min.js         # Icons
│
├── workflows/                # ComfyUI JSON Workflows & Configuration
│   ├── workflows-config.json # Master configuration (Tool definitions, node mappings)
│   └── *.json                # Individual ComfyUI API workflows
│
├── usage_logs.db             # SQLite database storing generation requests/IPs
├── run.bat                   # Windows startup & environment script
├── run.sh                    # Linux/Mac startup & environment script
└── requirements.txt          # Python dependencies
```

## Backend Breakdown

The backend is built using **FastAPI** to provide a fast, asynchronous middle-layer between the end-user and the ComfyUI server.

### 1. Generation Pipeline (`app/api/generate.py`)
- **Image Uploads:** Receives `image` or `image2` from the frontend and forwards them to ComfyUI's `/upload/image` endpoint using `httpx`.
- **Node Mapping:** Reads the `workflows-config.json` to map frontend inputs (prompt string, uploaded image names, calculated width/height from aspect ratio, and random seeds) directly into the parsed workflow JSON's node fields.
- **Queueing:** Submits the modified workflow to ComfyUI's `/prompt` endpoint.

### 2. Status & Progress Tracking (`app/api/status.py`)
- **Server-Sent Events (SSE):** Provides real-time updates to the frontend by multiplexing two sources:
  - **Queue Polling:** Regularly checks ComfyUI's `/queue` endpoint to determine the user's position before generation starts.
  - **WebSocket Listening:** Connects directly to ComfyUI's WebSocket to receive `execution_start`, `executing` (node transitions), `progress` events, and binary preview images.
- **Friendly Naming:** Maps technical ComfyUI node class names (e.g., `KSamplerAdvanced`, `AnimateDiffEvolve`) to user-friendly status strings (e.g., "Generating...", "Generating Video...").

### 3. Admin & Analytics (`app/api/admin.py`)
- **Security:** Protected by an `Authorization` header matched against `adminKey` in the config.
- **Usage Logging:** Reads from the local SQLite `usage_logs.db` to provide dashboard analytics (top tools, top IPs, timeline).
- **System Commands:** Can trigger `git pull` updates and forcefully restart the application server by creating a `RESTART_REQUIRED` lock file that the `run.bat` script watches for.

## Frontend Breakdown

The frontend uses Vanilla HTML/JS with **TailwindCSS** for rapid, responsive styling. It prioritizes a "glassmorphism" aesthetic with a dark theme.

### 1. The Generator (`static/index.html` & `static/app.js`)
- Dynamically generates UI inputs (prompt boxes, image dropzones, aspect ratio selectors) based on the currently selected tool's node mappings.
- Handles complex output types (Image, Video, Audio) and initializes appropriate players (e.g., `WaveSurfer.js` for audio visualization).
- Uses `EventSource` to listen to the SSE backend endpoint for live progress bars and preview image updates.

### 2. Admin Dashboard (`static/admin.html` & `static/admin.js`)
- **Tool Editor:** Provides a drag-and-drop interface for uploading `.json` workflows. It automatically detects and maps nodes like `CLIPTextEncode` or `EmptyLatentImage` to frontend UI elements.
- **Analytics:** Visualizes the `usage_logs.db` data with time-period filtering and CSV export capabilities.

## Data Flow: End-to-End Generation

1. **User Action:** The user selects a tool, enters a prompt, and clicks "Generate".
2. **Submission:** `app.js` sends a `multipart/form-data` request to `/api/generate`.
3. **Processing:** `generate.py` validates inputs, uploads any images to ComfyUI, patches the workflow JSON based on mapped nodes, and queues the job.
4. **Monitoring:** `app.js` opens an SSE connection to `/api/status`. `status.py` listens to ComfyUI's websocket and yields progress events back to the frontend.
5. **Retrieval:** Once completed, `app.js` requests the final output from `/api/output`, which fetches the file from ComfyUI, strips metadata (if it's an image), and serves it to the browser for display/download.
