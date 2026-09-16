# Orange 😼

![Orange UI Screenshot](docs/Generate.jpg)

Orange is a minimalist web frontend for **ComfyUI**. It turns engineer-built API workflows into simple generation tools without exposing the node graph, model plumbing, or backend fleet to ordinary users.

## Design Philosophy

Orange is intentionally **not** a generic ComfyUI parameter editor.

The workflow author owns the complicated parts: models, samplers, steps, CFG/guidance, LoRAs, conditioning, custom nodes, and other implementation details. Orange should expose only the choices a user genuinely needs for that generation, typically:

- prompt
- image/reference image when required
- an intentionally curated aspect ratio/resolution
- Generate

`nodeMapping` is a curated product API, not a list of technical controls waiting to be generalized.

**The goal is smarter internals, not a more complicated frontend.**

See [Architecture Overview](docs/ARCHITECTURE.md) for the engineering boundary and current runtime design.

## Highlights

- **Simple Generator UI** — workflow complexity stays hidden behind a small semantic input surface.
- **First-Run Setup** — fresh installs connect ComfyUI, inspect the available GPU/VRAM, create an Admin password, and may finish with **zero curated tools installed**.
- **Existing-Model Discovery** — Orange scans ComfyUI's node/model inventory and can reuse compatible declared model variants that are already installed, including models stored in ComfyUI subfolders.
- **Curated Workflow Packs** — Orange ships tested Z-Image Turbo, Krea 2 Turbo, Klein 9B Turbo, and SeedVR2 7B Upscale packs with dependency manifests. Z-Image is recommended for newcomers, not required.
- **Hardware-Aware Model Selection** — when a dependency is missing, curated packs prefer native INT8 ConvRot where the connected ComfyUI/GPU supports it, then choose FP8 or BF16/FP16 fallbacks according to the pack and available VRAM.
- **Transparent Pack Installs** — **Admin → Tools → Curated Library** shows exactly which missing files Orange intends to download, their model category, precision, destination, and source before installation.
- **Add Tools Later** — curated packs can be added at any time, or skipped entirely by advanced users who want to import/build their own tools.
- **ComfyUI API Workflows** — add image, edit, upscale, video, audio, or text-producing tools without rebuilding their logic in Orange.
- **Multi-Backend Routing** — queue-aware selection across configured ComfyUI servers with priority, health tracking, and short-lived active-request reservations.
- **Workflow-Aware Compatibility** — Admin Preflight checks each backend for required nodes, mappings, model values, and workflow assets. A healthy machine missing a required model can be excluded from routing for that workflow without being marked globally down.
- **Safe Failover** — explicit workflow rejections and safe pre-submission failures can retry another backend while ambiguous post-submission failures avoid duplicate jobs.
- **Workflow Assets** — fixed reference images can be managed by Orange and staged automatically on whichever backend receives a job.
- **Real-Time Status** — queue/progress information is surfaced from ComfyUI while the generator stays backend-agnostic.
- **Normalized Outputs** — image, video, audio, and text output handling with backend ownership recorded per prompt.
- **Prompt Enhancement** — optional OpenAI/OpenAI-compatible, Ollama, Gemini, or Anthropic LLM expansion with local prompt overrides.
- **Personalization** — Classic, Cyber, Princess, Arcade, Adventure, Midnight, and Custom themes plus white-label app name/logo/icon/colors.
- **Responsive Admin** — tool editor, workflow preflight, backend health, curated packs, workflow assets, analytics, database backup/restore, and personalization.
- **Git-Safe Local State** — active config, prompt overrides, branding, and related deployment state are separated from tracked defaults.
- **Windows/Linux/macOS Launchers** — launchers create the venv, resync dependencies when `requirements.txt` changes, and support Admin-triggered restart.

## Requirements

For a manual/GitHub install:

- Python 3
- One or more running [ComfyUI](https://github.com/comfyanonymous/ComfyUI) instances

The companion Pinokio launcher can instead install Orange and a managed local ComfyUI together.

## Installation

### Manual / GitHub

1. Clone this repository.
2. Start Orange:
   - Windows: run `run.bat`
   - Linux/macOS: run `./run.sh`
3. Open `http://localhost:7070/`.
4. On a genuinely fresh install, Orange opens its first-run setup wizard instead of the normal Generate page.
5. Connect an existing local or remote ComfyUI instance. Orange scans its nodes and model dropdown inventory before offering any curated-tool downloads.

Manual installs do **not** require or recommend Pinokio. Orange works with any reachable ComfyUI backend.

The launcher hashes `requirements.txt`, so dependencies are resynchronized automatically after an Orange update changes them.

### Pinokio

A companion Pinokio installer is available at:

`https://beta.pinokio.co/apps/github-com-saintbrodie-orange-pinokio`

Pinokio offers two install modes:

- **Orange + ComfyUI (Recommended)** — installs a managed local ComfyUI and Orange. The browser setup wizard starts after ComfyUI is available and lets the user choose whether to add any curated tools.
- **Orange Only** — installs only Orange for users who already have ComfyUI locally, through another manager, or on another machine.

Pinokio intentionally does not pre-download Z-Image or any other workflow model. Curated tools are optional and Orange only downloads missing dependencies after inspecting the connected backend.

Pinokio is an enhanced deployment option, not an Orange dependency.

## First-Run Setup

Fresh installs are redirected to `/setup`. The wizard:

1. Connects to ComfyUI and reads `/object_info` plus `/system_stats`.
2. Identifies the available GPU, VRAM, ComfyUI version, PyTorch information, workflow nodes, and model dropdown inventory.
3. Shows all curated packs as **optional**. Z-Image Turbo is marked Recommended for newcomers but is not selected or required.
4. Reports which packs are already runnable using compatible declared model variants found on that ComfyUI backend.
5. For packs with missing dependencies, shows exactly which model files Orange would download and where they would go.
6. Reuses existing compatible variants even when they differ from Orange's preferred fresh-download precision.
7. Downloads only missing files when Orange has filesystem access to the selected ComfyUI model directory.
8. Materializes selected workflows with the actual model filenames reported by ComfyUI, including subfolder paths, then runs Workflow Preflight.
9. Requires a new Admin password.
10. Allows setup to finish with **no curated workflows installed**; in that case Orange opens Admin so advanced users can import/configure their own tools.

A failed optional pack does not block first-run setup. It can be repaired later from **Admin → Tools → Curated Library**.

Existing Orange installations are automatically treated as already configured when they update, so they are **not** forced through the wizard and their active config is not replaced.

The historical `orangeadmin` value remains only in the tracked default template for compatibility. A genuinely fresh launch replaces it with a random temporary credential before setup and then stores the password chosen in the wizard.

First-run setup is restricted to the local machine by default. `ORANGE_ALLOW_REMOTE_SETUP=1` can be used when remote setup is intentionally required.

## Curated Workflow Packs

Fresh installs do not enable any curated tool by default. Available Orange-tested packs are:

- **Z-Image Turbo / Generate Image** — minimal general-purpose text-to-image using stock ComfyUI nodes. Recommended as an easy first generator, but completely optional.
- **Krea 2 Turbo** — advanced 8-step text-to-image. The Orange workflow intentionally uses `wan_2.1_vae.safetensors`; this is a deliberate quality choice rather than the VAE used by the upstream example workflow.
- **Klein 9B Turbo** — instruction-based image editing using the existing native-node Orange Klein workflow.
- **SeedVR2 7B Upscale** — 4× image upscaling using ComfyUI's current native SeedVR2 preprocess/conditioning/post-process nodes rather than the older custom-node implementation.

Workflow packs live under `workflow-packs/<pack-id>/manifest.json`. A pack declares:

- the curated API workflow
- the Orange tool mapping
- model dependency categories
- supported precision variants
- model-to-node filename bindings

Orange only rewrites declared model filenames when selecting or reusing a compatible variant; it does not otherwise redesign the curated workflow.

### Existing model discovery

For a connected ComfyUI backend, Orange inspects the model choices exposed by the workflow's loader nodes in `/object_info`.

If every declared dependency already has a compatible variant available, Curated Library shows **Add to Orange** instead of Install. No model filesystem path is required, so this also works with remote ComfyUI servers that Orange cannot write to directly.

Orange matches declared models by filename while preserving the exact option string reported by ComfyUI. For example, a model exposed as `z-image/z_image_turbo_bf16.safetensors` can be recognized and bound with that subfolder path.

If only some dependencies are present, Orange keeps those existing variants and downloads only the missing dependencies rather than replacing the whole stack with its preferred precision set.

### Model selection

When a dependency actually needs to be downloaded, the current policy is intentionally conservative:

- modern NVIDIA/CUDA + ComfyUI with native INT8 ConvRot support → prefer **INT8 ConvRot** when the pack publishes it
- systems where INT8 is not selected → prefer **FP8** for larger models when available
- sufficiently high-VRAM systems → use **BF16/FP16** where the pack provides it and the extra memory cost is reasonable
- AMD/ROCm currently avoids automatic INT8 ConvRot selection and uses the pack's FP8/BF16 fallback because INT8 diffusion support is not yet equally reliable there

Not every model family publishes every precision. For example, the Z-Image curated pack has an official INT8/BF16 diffusion choice and an FP8/BF16 text-encoder choice.

Most dependencies are downloaded from current **Comfy-Org** Hugging Face repacks. Klein is the exception: Comfy-Org redistributes its text encoder and VAE, while the licensed FLUX.2 Klein 9B diffusion checkpoint is downloaded from Black Forest Labs.

The command-line dependency installer remains available:

```bash
python scripts/download_models.py --pack z-image-turbo --models-root /path/to/ComfyUI/models
```

Without live `/system_stats`, the CLI uses conservative pack fallbacks. The browser first-run/Admin installers are preferred when automatic hardware selection matters.

See [Curated Workflow Packs](docs/WORKFLOW_PACKS.md) for the pack format, hardware-selection policy, and maintainer workflow.

## Adding Curated Tools Later

Open **Admin → Tools → Curated Library** and choose a target ComfyUI backend.

Orange scans the backend before presenting an action:

- **Add to Orange** — all required declared model variants are already available. Orange binds those existing filenames and runs Preflight; no download path is required.
- **Install missing models** — one or more dependencies are absent. The card shows each file Orange plans to download, its model category, selected precision, source, and destination before installation.
- **Missing nodes / unverifiable inventory** — Orange explains what prevents safe installation rather than blindly downloading files.

A local/shared models path is required only when Orange actually needs to download something. That path can be a normal ComfyUI models directory, Stability Matrix storage, Pinokio-managed storage, or a writable network share.

While a curated workflow is being installed, its card keeps the active install state and exact file list when navigating to another Admin screen and back.

If Orange is connected to a remote ComfyUI server without filesystem access to its model storage, it can still scan the backend and add a curated workflow when all required compatible models are already present. If dependencies are missing, Orange reports them rather than pretending it can write to that machine.

## Adding Your Own Tool

1. Build and test the workflow in ComfyUI.
2. Export it using **Save (API format)**.
3. Upload it in Orange's Admin **Tools** tab.
4. Map only the semantic fields Orange should expose.
5. Add any fixed reference images as **Workflow Assets** rather than relying on backend-local filenames.
6. Run **Workflow Preflight**.
7. Confirm at least one backend is routable for the workflow.

See [Adding Workflows](docs/adding_workflows.md) for the full guide.

## Workflow Preflight and Routing

Preflight validates the local workflow/mapping and compares it with each configured backend's ComfyUI `object_info`.

It can detect:

- wrong/UI workflow format
- missing mapped nodes or fields
- missing custom nodes
- required inputs Orange cannot supply
- unavailable enumerated values such as checkpoint/model names
- unmanaged image inputs
- Orange-managed fixed workflow assets

A useful distinction is **backend health vs workflow compatibility**. If a server is online but lacks `model-x.safetensors`, Orange can keep the Admin result yellow while marking that backend not routable for the workflow that requires Model X. Other tools can continue using the same server normally.

After Preflight, the compatibility result is cached using a fingerprint of the workflow and node mapping. Rerun Preflight after materially changing the workflow/dependencies so routing learns the new placement information.

## Backend Failover

Orange records which backend actually accepted each prompt and uses that machine for later status/output access.

Safe submission behavior includes:

- connection failure before a job is accepted → another backend may be tried
- backend server error → another backend may be tried and health state updated
- explicit workflow rejection/4xx → another backend may be tried without marking the first server globally unhealthy
- ambiguous timeout after submission may have reached ComfyUI → Orange does **not** blindly retry and risk creating a duplicate generation

The regression suite includes a two-backend generation test for this behavior.

## Admin Dashboard

<table border="0">
  <tr>
    <td align="center" valign="center"><img src="docs/General_Settings.jpg" width="100%" alt="General Settings" /></td>
    <td align="center" valign="center"><img src="docs/Tool_Editor.jpg" width="100%" alt="Tool Editor" /></td>
    <td align="center" valign="center"><img src="docs/Analytics.jpg" width="100%" alt="Analytics Dashboard" /></td>
  </tr>
  <tr>
    <td align="center"><b>General Settings</b></td>
    <td align="center"><b>Tool Editor</b></td>
    <td align="center"><b>Analytics</b></td>
  </tr>
</table>

Admin capabilities include:

- ComfyUI backend configuration and health visibility
- curated workflow-pack discovery/installation/repair
- workflow upload/editing and semantic node mappings
- workflow Preflight and per-backend compatibility
- fixed Workflow Assets
- tool-specific aspect ratio overrides
- prompt enhancement configuration
- system-prompt editing
- usage analytics/gallery
- WAL-safe database backup/restore
- themes and white-label personalization

## Prompt Enhancement

Prompt enhancement is optional. In **General Settings**, enable it and choose a provider:

- **OpenAI** — also supports compatible Base URLs such as LM Studio, llama.cpp, or OpenRouter.
- **Ollama** — local Ollama endpoint.
- **Gemini** — Google Gemini API.
- **Anthropic** — Anthropic API.

Environment variables can be used instead of storing cloud API keys in Orange config:

- `OPENAI_API_KEY`
- `GEMINI_API_KEY`
- `ANTHROPIC_API_KEY`

Environment variables take precedence over UI-configured keys.

System prompt overrides under `workflows/prompts/` are local/user-owned and are not overwritten by normal Git updates.

## Personalization

Orange includes preset themes plus Custom/white-label branding. Built-in themed mascot variants are normal editable SVG assets under `static/theme-assets/logos/`, so vector edits do not need to preserve internal SVG IDs or generated class names.

User-owned personalization and uploaded branding live under `workflows/` and remain separate from tracked theme/runtime files.

See [Personalization](docs/PERSONALIZATION.md).

## Local State and Updates

Orange separates tracked defaults from active deployment state. Normal Git updates should not overwrite local prompts, branding, personalization, workflow assets, or other user-owned configuration under the designated `workflows/` locations.

The Admin update action uses a fast-forward-only Git pull and the launcher restart sentinel rather than attempting to overwrite local history.

## Testing

CI validates Python 3.10 and 3.12, compiles Python sources, syntax-checks tracked JavaScript modules, validates every theme/workflow-pack manifest, and runs the unit/regression suite.

The suite covers onboarding migration, hardware-aware workflow packs, existing-model discovery, Admin pack installation/activation, routing, preflight, safe submission, route precedence, database migration/backup/restore, output handling, workflow assets, personalization, public config safety, LLM validation, and other operational behavior.

## Documentation

- [Architecture Overview](docs/ARCHITECTURE.md)
- [Curated Workflow Packs](docs/WORKFLOW_PACKS.md)
- [Adding Workflows](docs/adding_workflows.md)
- [Personalization & White-Label Branding](docs/PERSONALIZATION.md)
- [Personalization Test Checklist](docs/PERSONALIZATION_TESTING.md)

## Current Development Posture

Orange has reached the point where reliability should be driven primarily by **dogfooding real workflows** rather than broad feature expansion. If a new idea makes the Generate page more technical, first ask whether it can be solved once by the workflow engineer or Admin instead.
