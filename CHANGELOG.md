# Changelog

## v1.0.0 - 2026-10-01

First stable Orange release.

### Generator and workflow UX

- Turns ComfyUI API workflows into simple purpose-built tools without exposing the node graph.
- Supports image, video, audio, and text-producing workflows.
- Keeps the user-facing input surface intentionally small while workflow authors keep technical controls in ComfyUI.
- Supports fixed workflow assets, tool-specific aspect ratios, regeneration, result actions, and normalized multi-output handling.

### First-run setup and curated tools

- Adds a real first-run setup flow with Admin password creation and ComfyUI discovery.
- Adds optional curated workflow packs for Z-Image Turbo, Krea 2 Turbo, FLUX.2 Klein 9B editing, and SeedVR2 7B upscaling.
- Detects compatible models already installed in ComfyUI and reuses them when possible.
- Selects supported model precision based on backend hardware and ComfyUI capabilities when downloads are needed.
- Shows planned model downloads before installation and allows setup to finish with no curated packs installed.

### Multi-backend reliability

- Adds backend health monitoring and queue-aware routing across multiple ComfyUI servers.
- Adds Workflow Preflight for node, mapping, model, and workflow-asset compatibility.
- Separates backend health from workflow-specific routing compatibility.
- Adds safe failover behavior that retries only when doing so will not risk duplicate generations.
- Records the backend that accepted each prompt for later status and output retrieval.

### Admin and operations

- Adds responsive Admin navigation, backend status, tool editing, Curated Library, Preflight, Workflow Assets, analytics, and gallery views.
- Adds WAL-safe SQLite backup and restore with additive schema migration.
- Keeps deployment-owned config, prompts, branding, and workflow assets separate from tracked defaults.
- Adds quiet but useful terminal output with generation and prompt-enhancement activity, warnings, and failures.

### Prompt enhancement and personalization

- Supports OpenAI-compatible endpoints, Ollama, Gemini, Anthropic, and managed local prompt enhancement.
- Adds provider validation, safer public errors, rate limiting, and server-side redaction of sensitive provider responses.
- Adds built-in themes and white-label branding with offline vendored fonts.

### Packaging and documentation

- Adds Windows, Linux, and macOS launchers with dependency resync and restart handling.
- Adds a companion Pinokio launcher for either a managed Orange + ComfyUI stack or Orange Only against an existing ComfyUI.
- Adds maintained architecture, workflow-authoring, workflow-pack, managed-runtime, prompt-enhancement, and personalization documentation.
- Adds refreshed full-resolution README screenshots.

### License

- Orange is released under the MIT License.
- Third-party components and externally downloaded model weights retain their own licenses. See `THIRD_PARTY_NOTICES.md`.
