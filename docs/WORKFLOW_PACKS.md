# Curated Workflow Packs

Orange workflow packs are curated, installable ComfyUI tools intended to give a deployment a known-good path from **install** to **Generate** without teaching the user how the node graph works.

They are different from arbitrary user-uploaded workflows:

- a pack has a tested ComfyUI API workflow
- a pack declares the Orange tool mapping
- a pack declares its model dependencies
- dependencies can publish multiple precision variants
- Orange can select model variants from the connected backend's hardware
- Orange rewrites only explicitly declared model filenames in the active workflow
- Orange runs Workflow Preflight before exposing the tool

The pack system is not a general ComfyUI model manager. It installs dependencies for Orange's curated tools when Orange has filesystem access to the target backend's model storage.

## Included Packs

### Z-Image Turbo

The default first-run starter.

- general text-to-image
- user inputs: prompt and aspect ratio
- stock/native ComfyUI nodes
- no realism LoRA or optional custom-node dependency
- hardware-aware diffusion/text-encoder selection

Fresh installs expose only this tool by default.

### Krea 2 Turbo

Advanced text-to-image generation.

Orange intentionally preserves the curated workflow's use of `wan_2.1_vae.safetensors`. This differs from the VAE used in the upstream ComfyUI example and is a deliberate workflow-quality choice. Orange may replace declared diffusion/text-encoder filenames for precision selection, but otherwise keeps the graph intact.

### Klein 9B Turbo

Instruction-based image editing using the existing native-node Orange Klein workflow.

Comfy-Org-hosted dependencies are used where available. The licensed FLUX.2 Klein 9B diffusion checkpoint remains sourced from Black Forest Labs when it is not redistributed by Comfy-Org.

### SeedVR2 7B Upscale

4× image upscaling using ComfyUI's current native SeedVR2 preprocess, conditioning, and post-processing nodes. This replaces the older custom-plugin implementation for the curated Orange pack.

## Pack Layout

Packs live under:

```text
workflow-packs/
  <pack-id>/
    manifest.json
```

The corresponding curated API workflow lives in `workflows/defaults/` and is materialized into the active workflow area as needed.

A pack manifest describes the stable parts Orange needs to know:

- pack ID/name/description
- curated workflow filename
- Orange tool definition and semantic mappings
- model dependencies and destination categories
- supported model variants
- workflow node/input bindings whose filenames may be replaced

Keep this schema intentionally small. The ComfyUI workflow should continue to own implementation details such as samplers, schedulers, steps, CFG/guidance, denoise, and LoRA choices.

## Model Dependencies

A dependency declares:

- destination model category such as `diffusion_models`, `text_encoders`, or `vae`
- one fixed file or multiple supported variants
- source URL/repository path
- optional workflow bindings describing which node/input contains that filename

Orange downloads only missing files into the resolved model folder for that category. Existing files are reused.

## Hardware-Aware Precision Selection

During browser first-run setup or Admin pack installation, Orange queries ComfyUI's `/system_stats` endpoint and normalizes useful backend information such as:

- GPU/device name
- CUDA/ROCm-style device type
- total VRAM
- ComfyUI version
- PyTorch version

The current policy is conservative:

1. On supported modern NVIDIA/CUDA + ComfyUI installations, prefer a published **INT8 ConvRot** variant.
2. When INT8 is not selected, prefer **FP8** for larger model families when a tested FP8 variant is available.
3. Use **BF16/FP16** where the pack provides it and the backend has enough memory for the higher-precision option.
4. AMD/ROCm currently avoids automatic INT8 ConvRot selection and uses the pack's tested FP8/BF16/FP16 fallback.

Not every dependency publishes every precision, so selection happens independently for each declared model dependency.

Normal users should not be asked to choose INT8, FP8, or BF16. That is an implementation decision Orange is intended to absorb.

## Workflow Materialization

Hardware selection does not redesign the curated workflow.

Orange:

1. loads the curated API workflow
2. selects model variants from the pack manifest
3. rewrites only explicitly declared model filename bindings
4. writes/materializes the active workflow
5. runs Workflow Preflight against the target backend

Known-good graph choices are preserved. For example, Krea keeps the Wan 2.1 VAE even though an upstream example may use another VAE.

## First-Run Behavior

Fresh Orange installs start with Z-Image Turbo.

The setup wizard can also offer optional Krea 2 Turbo, Klein 9B Turbo, and SeedVR2 7B Upscale packs. For each selected pack, Orange:

1. connects to ComfyUI
2. reads backend hardware information
3. resolves a writable models path
4. selects model variants
5. downloads missing files
6. materializes the workflow
7. runs Workflow Preflight
8. exposes the tool only when the backend is routable

A failure in an optional pack does not prevent a working Z-Image starter from completing setup.

## Installing Packs Later

Use **Admin → General Settings → Curated Tools**.

Each configured ComfyUI server can have an optional `modelsRoot` path. That path represents model storage Orange can write to for that backend.

Typical examples include:

- a normal local `ComfyUI/models` directory
- a Stability Matrix model directory
- a Pinokio-managed ComfyUI model directory
- a writable network/shared model directory

The Admin installer targets one configured backend, reads that backend's hardware, downloads the selected pack's dependencies to the configured model path, materializes the workflow, runs Preflight, and adds the tool only if that backend is routable.

For remote ComfyUI machines where Orange cannot access the filesystem, Orange can still detect missing dependencies through Preflight but will not pretend it can install them.

## Pinokio Integration

The companion `orange-pinokio` launcher supports two deployment modes:

- **Orange + ComfyUI** — Pinokio owns a local ComfyUI installation and passes Orange the managed ComfyUI/model locations.
- **Orange Only** — Orange connects to an existing ComfyUI installation.

The Pinokio installer intentionally does **not** pre-download one fixed Z-Image precision. It starts the managed ComfyUI first so Orange can inspect `/system_stats` and make the same hardware-aware pack decision used everywhere else.

## CLI Installation

The dependency installer remains available for scripting:

```bash
python scripts/download_models.py --pack z-image-turbo --models-root /path/to/ComfyUI/models
```

Without live `/system_stats`, CLI installation uses conservative pack fallbacks. Browser first-run/Admin installation is preferred when automatic hardware selection matters.

## Adding a Curated Pack

When promoting a workflow into Orange's curated library:

1. Test the workflow directly in current ComfyUI.
2. Export a clean API-format workflow.
3. Prefer native ComfyUI nodes where practical.
4. Preserve intentional quality choices in the known-good graph.
5. Add the workflow under `workflows/defaults/`.
6. Add a `workflow-packs/<pack-id>/manifest.json` dependency manifest.
7. Declare only model filename bindings Orange is allowed to replace.
8. Add tests for the pack catalog, dependency selection, materialization, and any important workflow-specific choice.
9. Run Preflight against a real target ComfyUI build before treating the pack as production-ready.

Do not turn a curated pack into a generic model/node configuration UI. The point is to package a good workflow, not expose its internals.