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
- **First-Run Setup** — fresh installs connect ComfyUI, inspect the available GPU/VRAM, create an Admin password, detect local model storage when available, and install a known-good starter generator.
- **Curated Workflow Packs** — Orange ships tested Z-Image Turbo, Krea 2 Turbo, Klein 9B Turbo, and SeedVR2 7B Upscale packs with dependency manifests.
- **Hardware-Aware Model Selection** — curated packs prefer native INT8 ConvRot where the connected ComfyUI/GPU supports it, then choose FP8 or BF16/FP16 fallbacks according to the pack and available VRAM.
- **Add Tools Later** — the Admin General Settings page includes a Curated Tools installer, so users can start with Z-Image and add editing/upscaling/advanced T2I later.
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
5. Connect an existing local or remote ComfyUI instance. If Orange can access that backend's models directory, it can install curated workflow dependencies for you.

Manual installs do **not** require or recommend Pinokio. Orange works with any reachable ComfyUI backend.

The launcher hashes `requirements.txt`, so dependencies are resynchronized automatically after an Orange update changes them.

### Pinokio

A companion Pinokio installer is available at:

`https://beta.pinokio.co/apps/github-com-saintbrodie-orange-pinokio`

Pinokio offers two install modes:

- **Orange + ComfyUI (Recommended)** — installs a managed local ComfyUI and Orange. The browser setup wizard starts after ComfyUI is available, detects the actual hardware, and downloads the appropriate curated model files.
- **Orange Only** — installs only Orange for users who already have ComfyUI locally, through another manager, or on another machine.

Pinokio intentionally does not pre-download one fixed Z-Image precision anymore. Orange makes that decision after it can inspect the real backend.

Pinokio is an enhanced deployment option, not an Orange dependency.

## First-Run Setup

Fresh installs are redirected to `/setup`. The wizard:

1. Connects to ComfyUI and verifies `/object_info` is reachable.
2. Reads `/system_stats` to identify the available GPU, VRAM, ComfyUI version, and PyTorch information.
3. Offers the minimal **Z-Image Turbo** starter generator.
4. Optionally offers **Krea 2 Turbo**, **Klein 9B Turbo**, and **SeedVR2 7B Upscale**.
5. Selects the appropriate curated model precision for that backend.
6. Downloads required files when Orange has filesystem access to the selected ComfyUI model directory.
7. Materializes the workflow with the selected model filenames and runs Workflow Preflight.
8. Exposes an optional tool only if the selected backend is actually routable for it.
9. Requires a new Admin password.
10. Opens the normal Generate UI after the starter passes Preflight.

An optional-pack failure does not prevent the Z-Image starter from completing setup. The failed pack can be repaired later from Admin.

Existing Orange installations are automatically treated as already configured when they update, so they are **not** forced through the wizard and their active config is not replaced.

The historical `orangeadmin` value remains only in the tracked default template for compatibility. A genuinely fresh launch replaces it with a random temporary credential before setup and then stores the password chosen in the wizard.

First-run setup is restricted to the local machine by default. `ORANGE_ALLOW_REMOTE_SETUP=1` can be used when remote setup is intentionally required.

## Curated Workflow Packs

Fresh installs intentionally start small. The only tool enabled by default is:

- **Z-Image Turbo / Generate Image** — minimal general-purpose text-to-image using stock ComfyUI nodes.

Additional curated packs are optional:

- **Krea 2 Turbo** — advanced 8-step text-to-image. The Orange workflow intentionally uses `wan_2.1_vae.safetensors`; this is a deliberate quality choice rather than the VAE used by the upstream example workflow.
- **Klein 9B Turbo** — instruction-based image editing using the existing native-node Orange Klein workflow.
- **SeedVR2 7B Upscale** — 4× image upscaling using ComfyUI's current native SeedVR2 preprocess/conditioning/post-process nodes rather than the older custom-node implementation.

Workflow packs live under `workflow-packs/<pack-id>/manifest.json`. A pack declares:

- the curated API workflow
- the Orange tool mapping
- model dependency categories
- supported precision variants
- model-to-node filename bindings

Orange only rewrites declared model filenames when selecting a precision; it does not otherwise redesign the curated workflow.

### Model selection

The current policy is intentionally conservative:

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

## Adding Curated Tools Later

Open **Admin → General Settings → Curated Tools**.

Choose:

1. the target configured ComfyUI backend
2. a local/shared models path Orange can write to
3. **Install** on the desired pack

Orange then:

1. inspects that backend's hardware
2. chooses the pack's model variants
3. downloads only missing files
4. writes the selected filenames into the active workflow copy
5. runs Workflow Preflight against the chosen backend
6. adds the tool to Orange only if that backend is routable

The chosen models path is remembered on that server's Orange configuration. This is useful for normal local ComfyUI installs, Stability Matrix model locations, or a shared/network model directory.

If Orange is connected to a remote ComfyUI server without filesystem access to its model storage, Preflight can still detect missing models, but Orange will not pretend it can write files to that remote machine.

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
- curated workflow-pack installation/repair
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

The suite covers onboarding migration, hardware-aware workflow packs, Admin pack installation, routing, preflight, safe submission, route precedence, database migration/backup/restore, output handling, workflow assets, personalization, public config safety, LLM validation, and other operational behavior.

## Documentation

- [Architecture Overview](docs/ARCHITECTURE.md)
- [Adding Workflows](docs/adding_workflows.md)
- [Personalization & White-Label Branding](docs/PERSONALIZATION.md)
- [Personalization Test Checklist](docs/PERSONALIZATION_TESTING.md)

## Current Development Posture

Orange has reached the point where reliability should be driven primarily by **dogfooding real workflows** rather than broad feature expansion. If a new idea makes the Generate page more technical, first ask whether it can be solved once by the workflow engineer or Admin instead.
