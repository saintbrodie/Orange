# Curated Workflow Packs

Orange workflow packs are curated, installable ComfyUI tools intended to provide known-good workflows without forcing them on every deployment.

They are different from arbitrary user-uploaded workflows:

- a pack has a tested ComfyUI API workflow
- a pack declares the Orange tool mapping
- a pack declares its model dependencies
- dependencies can publish multiple precision variants
- Orange can inspect the connected ComfyUI for compatible variants already present
- Orange can select missing model variants from the connected backend's hardware
- Orange rewrites only explicitly declared model filenames in the active workflow
- Orange runs Workflow Preflight before exposing the tool

The pack system is not a general ComfyUI model manager. It installs dependencies for Orange's curated tools when Orange has filesystem access to the target backend's model storage. Advanced users may install Orange with **zero curated tools** and use only their own workflows.

## Included Packs

### Z-Image Turbo

Recommended as a simple first generator, but not required.

- general text-to-image
- user inputs: prompt and aspect ratio
- stock/native ComfyUI nodes
- no realism LoRA or optional custom-node dependency
- hardware-aware diffusion/text-encoder selection when files need to be downloaded

Fresh installs do not enable Z-Image or any other curated tool unless the user selects it.

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

The corresponding curated API workflow lives in `workflows/defaults/` and is materialized into the active workflow area only when the pack is added to Orange.

A pack manifest describes the stable parts Orange needs to know:

- pack ID/name/description
- curated workflow filename
- Orange tool definition and semantic mappings
- model dependencies and destination categories
- supported model variants
- workflow node/input bindings whose filenames may be replaced

Keep this schema intentionally small. The ComfyUI workflow should continue to own implementation details such as samplers, schedulers, steps, CFG/guidance, denoise, and LoRA choices.

## Existing-Model Discovery

Before downloading a curated pack in browser setup or Admin, Orange reads the connected ComfyUI backend's `/object_info` and `/system_stats`.

For each model dependency, Orange inspects the model choices exposed by the specific loader node/input bound in the pack manifest. A declared variant counts as available when ComfyUI exposes the same filename. Subfolder paths are supported: a loader value such as `z-image/z_image_turbo_bf16.safetensors` matches the declared `z_image_turbo_bf16.safetensors`, and Orange binds the exact option string reported by ComfyUI.

This produces three useful states:

- **Ready / Add to Orange** — all required nodes and compatible declared model variants are already present. No model filesystem access is required.
- **Missing models / Install missing models** — Orange preserves compatible existing variants and plans downloads only for absent dependencies.
- **Missing nodes or unverifiable inventory** — Orange explains the blocker instead of blindly downloading files.

This is especially useful with Orange-only/bring-your-own ComfyUI installs. A remote ComfyUI can use **Add to Orange** even when Orange cannot write to that machine's filesystem, provided its required models and nodes are already present.

## Model Dependencies

A dependency declares:

- destination model category such as `diffusion_models`, `text_encoders`, or `vae`
- one fixed file or multiple supported variants
- source URL/repository path
- optional workflow bindings describing which node/input contains that filename

When a file is missing, Orange's install plan shows the selected filename, category, precision, source, and resolved destination before the user starts the download.

## Hardware-Aware Precision Selection

Hardware selection applies to dependencies Orange actually needs to download. An existing compatible declared variant is reused rather than replaced simply because another precision would have been preferred for a fresh installation.

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

Not every dependency publishes every precision, so selection happens independently for each missing model dependency.

Normal users should not be asked to choose INT8, FP8, or BF16. That is an implementation decision Orange is intended to absorb.

## Workflow Materialization

Discovery and hardware selection do not redesign the curated workflow.

Orange:

1. loads the curated API workflow
2. resolves each model binding to either an existing compatible ComfyUI option or a selected missing-file download
3. rewrites only explicitly declared model filename bindings
4. preserves the exact subfolder path when ComfyUI reports one
5. writes/materializes the active workflow
6. runs Workflow Preflight against the target backend

Known-good graph choices are preserved. For example, Krea keeps the Wan 2.1 VAE even though an upstream example may use another VAE.

## First-Run Behavior

Fresh Orange installs may finish with no curated tools at all.

The setup wizard presents Z-Image Turbo, Krea 2 Turbo, Klein 9B Turbo, and SeedVR2 7B Upscale as optional packs. Z-Image is visually recommended for newcomers but is not selected or required.

After connecting ComfyUI, setup:

1. reads backend hardware, nodes, and model inventory
2. reports which curated packs are already runnable with existing model variants
3. shows the exact missing-file download plan for packs that are not already complete
4. requires a writable models path only when selected dependencies actually need downloading
5. reuses any compatible existing declared variants
6. downloads only missing files
7. materializes selected workflows
8. runs Workflow Preflight
9. exposes each tool only when the backend is routable

A failure in any selected pack does not block Orange's first-run setup. A zero-pack setup opens Admin so advanced users can configure their own tools.

## Installing Packs Later

Use **Admin → Tools → Curated Library**.

Select a configured ComfyUI backend. Orange scans it immediately and shows each pack's current compatibility state.

If the backend already has every required model and node, choose **Add to Orange**. This path does not require `modelsRoot` and works for remote backends.

If model dependencies are missing, Curated Library shows each planned download before installation. A configured `modelsRoot` is then required so Orange has somewhere it can write the files. Typical examples include:

- a normal local `ComfyUI/models` directory
- a Stability Matrix model directory
- a Pinokio-managed ComfyUI model directory
- a writable network/shared model directory

When an install starts, the card continues to show the active state and file list while navigating between Admin screens and back. Errors remain attached to the card as a retry state.

## Pinokio Integration

The companion `orange-pinokio` launcher supports two deployment modes:

- **Orange + ComfyUI** — Pinokio owns a local ComfyUI installation and passes Orange the managed ComfyUI/model locations.
- **Orange Only** — Orange connects to an existing ComfyUI installation.

The Pinokio installer intentionally does **not** pre-download Z-Image or any other workflow model. Once ComfyUI is connected, Orange uses the same existing-model discovery and missing-file planning used everywhere else.

## CLI Installation

The dependency installer remains available for scripting:

```bash
python scripts/download_models.py --pack z-image-turbo --models-root /path/to/ComfyUI/models
```

Without live `/system_stats` and `/object_info`, CLI installation cannot perform the same existing-model inventory discovery. It therefore uses conservative pack fallbacks. Browser first-run/Admin installation is preferred when automatic reuse and hardware selection matter.

## Adding a Curated Pack

When promoting a workflow into Orange's curated library:

1. Test the workflow directly in current ComfyUI.
2. Export a clean API-format workflow.
3. Prefer native ComfyUI nodes where practical.
4. Preserve intentional quality choices in the known-good graph.
5. Add the workflow under `workflows/defaults/`.
6. Add a `workflow-packs/<pack-id>/manifest.json` dependency manifest.
7. Declare only model filename bindings Orange is allowed to replace.
8. Include every compatible model variant Orange is allowed to recognize/reuse.
9. Add tests for catalog behavior, existing-model discovery, dependency selection, materialization, and important workflow-specific choices.
10. Run Preflight against a real target ComfyUI build before treating the pack as production-ready.

Do not turn a curated pack into a generic model/node configuration UI. The point is to package a good workflow, not expose its internals.