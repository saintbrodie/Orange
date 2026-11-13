# Changelog

## v1.1.0 - 2026-11-13

### Curated workflows

- Adds LTX 2.5 Video with synchronized audio, 2–12-second lengths, and an optional first-frame image in one tool. Final output defaults are 1152x768 or 1344x768, with portrait support.
- Adds Qwen Image 2.1 Turbo Edit with the native eight-step schedule, madebyollin texture-fix VAE, and an optional second reference image.
- Adds MOSS-Image SFT text-to-image generation with three aspect ratios and text-focused poster examples.
- Combines Klein image modification and multi-image reference editing through an optional second upload.
- Moves prompt enhancement into Orange, with model-specific instructions for LTX, Qwen Edit, and MOSS instead of extra ComfyUI refiner nodes.
- Adds All, Image, Edit, Video, and Tools library filters. Image is reserved for text-to-image workflows; new manifest tags become filters automatically.
- Refreshes Z-Image, Krea, MOSS, and Qwen thumbnails and describes editing/video model strengths in plain language.

### Tool configuration

- Reorganizes the editor into Overview, Inputs & workflow, and Check & save, with a generator preview and Tool ID directly below Display Name.
- Keeps forms and workflow connections open. Both optional-input workflows and their image mappings are visible together, with node and field dropdowns populated from each graph.
- Exposes optional-image behavior, alternate workflow uploads/mappings, duration and frame timing, aspect ratios, output scaling, fixed assets, and prompt enhancement for ordinary imported tools as well as curated tools.
- Checks both workflow modes using unsaved editor values, with one Check Workflow button and a separate Save Tool action.

### Model locations and backend compatibility

- Resolves model locations per backend on a temporary submission copy, keeping shared workflow files portable.
- Reuses exact paths or unique exact filenames across ComfyUI subfolders and configured model paths, without guessing a different model or precision.
- Adds backend-specific Save model binding controls for duplicate filenames in Preflight and library results. Unique matches resolve automatically; workflow files are never rewritten by binding saves.
- Shares resolution rules across Preflight, library readiness, and generation, including installed tools and optional-input variants.
- Refreshes model inventory during scans and expires cached incompatibility. Explicit queue rejections allow one same-backend retry only when a fresh inventory changes the resolved model paths.
- Supports typed COMBO inventories and native expandable image conditioning slots in Preflight.

### Downloads and reliability

- Adds optional Hugging Face download credentials for gated models, with HF_TOKEN support and separate save/remove actions.
- Stores saved tokens in Windows Credential Manager, macOS Keychain, or Linux Secret Service under the Orange server account, with no plaintext fallback. Existing plaintext credentials migrate only after protected storage is verified.
- Keeps authorization on the exact HTTPS huggingface.co origin and strips it from external download redirects.
- Improves MP4 gallery handling and scrolling for longer generation forms.

### Upgrading

- Restart through the launcher to install updated dependencies. Existing local tools, workflows, prompts, branding, assets, and model bindings remain deployment-owned; reviewing or reinstalling a curated pack is a separate action.
- Run Check Workflow after upgrading. Different backend folders resolve automatically when model filenames match uniquely. See [the workflow guide](docs/adding_workflows.md) and [portable model locations](docs/WORKFLOW_PACKS.md#portable-model-locations).

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
