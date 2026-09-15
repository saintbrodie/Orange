# Adding ComfyUI Workflows to Orange

Orange wraps ComfyUI **API workflows** and exposes only a small, intentional set of user-facing inputs. The workflow can be technically complicated underneath; the Orange tool should stay simple.

## Before You Start: Keep Complexity in the Workflow

Configure implementation decisions in ComfyUI whenever possible: model choice, sampler, scheduler, steps, CFG/guidance, LoRA strengths, negative conditioning, custom-node settings, and similar technical values normally belong in the workflow rather than the Orange UI.

Orange should expose only decisions the user genuinely needs to make for each generation, such as a prompt, one or more required images, and an intentionally curated aspect ratio choice.

> If the workflow engineer can make the decision once, the Orange user should not have to make it every time.

The mapping system is deliberately small. It is not intended to become a generic form builder for every ComfyUI node input.

## User Tools vs Curated Workflow Packs

Most workflows should be added as ordinary user tools using the Tool Editor described below.

Use a **curated workflow pack** only when the workflow is intended to ship as an official Orange capability with managed model dependencies, hardware-aware precision selection, and automated installation/Preflight. Current curated packs include Z-Image Turbo, Krea 2 Turbo, Klein 9B Turbo, and SeedVR2 7B Upscale.

Curated packs live under `workflow-packs/` and are documented in [WORKFLOW_PACKS.md](WORKFLOW_PACKS.md). Do not add pack machinery just because a workflow uses models; ordinary user workflows should continue to rely on the administrator's existing ComfyUI/model setup and Preflight.

## 1. Export an API Workflow from ComfyUI

Orange needs ComfyUI's execution/API JSON, not the normal UI workflow containing node positions and editor metadata.

1. Open ComfyUI and confirm the workflow works there first.
2. Enable **Dev mode Options** in ComfyUI settings if necessary.
3. Use **Save (API format)**.
4. Keep the exported `.json` file.

## 2. Add It Through the Tool Editor

1. Open `http://localhost:7070/admin`.
2. Log in with the configured Admin password/key.
3. Open **Tools**.
4. Upload or drag in the exported API workflow JSON.
5. Configure the tool name, output type, and Orange node mappings.
6. Save the tool configuration.

Orange attempts to auto-detect common mappings, but the workflow engineer should verify every mapped node and field.

### Supported semantic mappings

- **Prompt** — usually maps to a text/string input such as `CLIPTextEncode.text`.
- **Image** — maps to a user-supplied image input. Orange uploads the file to the selected backend and rewrites the workflow value.
- **Image 2** — second user-supplied image when the tool genuinely requires one.
- **Width / Height** — used for Orange's curated aspect-ratio choices.
- **Seed** — normally configured with `generateRandom: true`; users do not need a seed control.
- **Output Text** — identifies text returned by the workflow for display alongside media.

### What not to map

Do not add a frontend control just because a node has a configurable field. These normally stay fixed inside the workflow:

- checkpoint/model
- sampler and scheduler
- steps
- CFG/guidance
- denoise
- LoRA selection or strength
- negative-prompt internals
- ControlNet/adapter strength
- custom-node tuning values
- internal video settings
- technical resolution transforms

If a future workflow truly requires a new kind of user interaction, add it deliberately as a first-class Orange concept rather than opening arbitrary node parameters to the frontend.

## 3. Fixed Workflow Images / Assets

An unmapped `LoadImage`-style input is treated differently from a user image mapping. If the workflow requires a fixed reference image, manage it as a **Workflow Asset** in the Tool Editor.

Orange owns managed assets for that workflow, uploads them to whichever backend actually receives the request, and rewrites the workflow input with the backend-side filename. This keeps a workflow portable across multiple ComfyUI machines.

An unmapped image input with no managed asset produces a Preflight warning because it may depend on a file that happens to exist on only one ComfyUI installation.

## 4. Run Workflow Preflight

Run **Workflow Preflight** before treating a tool as ready. Preflight validates both Orange's local configuration and each configured ComfyUI backend.

It checks, among other things:

- the JSON is a ComfyUI API workflow rather than the editor/UI format
- mapped node IDs exist
- mapped fields exist
- required node classes/custom nodes are installed on each backend
- required inputs are present or intentionally supplied by Orange
- enumerated values such as checkpoint/model names are available on each backend
- unmanaged image inputs are called out
- managed workflow assets are recognized as Orange-owned inputs

### Warning vs routing compatibility

Preflight severity and routing eligibility are intentionally separate.

For example, if Backend 1 is healthy and has every required custom node but is missing the workflow's selected checkpoint, the Admin UI reports that as a **warning** (`value_unavailable`) rather than claiming the server itself is broken. However, that backend is marked **not routable for that workflow**.

If Backend 2 has the required checkpoint, Orange routes the generation directly to Backend 2 instead of knowingly sending the request to Backend 1 first.

This compatibility decision is cached using a fingerprint of the workflow and node mapping, so changing either produces a new compatibility key. Run Preflight again after changing a workflow, model choice, custom-node dependency, or mapping when you want routing to use the updated compatibility information.

Preflight is workflow-specific. A backend excluded for one tool is not globally unhealthy and can continue serving other workflows it supports.

## 5. Backend Failover Behavior

Routing first considers workflow compatibility, then live backend health/load. Orange tracks queue state and a short-lived active-request reservation so simultaneous requests do not all pile onto the same backend before ComfyUI's queue poll updates.

If a compatible backend rejects a workflow during submission with a safe, backend-specific 4xx response, Orange can retry another compatible backend without marking the first server globally unhealthy. Network failures and server errors are tracked separately from workflow incompatibility.

Orange deliberately does **not** blindly retry ambiguous failures where the first backend may already have accepted the job, because doing so could create duplicate generations.

## Output Types

Each tool has an intended output type:

- **Image** — image result display.
- **Video** — video/animated output playback.
- **Audio** — audio playback with waveform UI.
- **Text** — text can be surfaced through an `outputText` mapping where appropriate.

## Workflow Design Checklist

Before publishing a tool, verify:

1. The workflow runs correctly in ComfyUI by itself.
2. It was exported in API format.
3. Model/sampler/steps/CFG/LoRA and other implementation details are resolved inside the workflow.
4. Every Orange input is a real per-generation user decision.
5. Mapped node IDs and fields are stable.
6. Required fixed images are uploaded as Workflow Assets rather than relying on backend-local filenames.
7. Workflow Preflight has been run against the configured backend pool.
8. At least one backend is routable for the workflow.
9. The configured output type matches what the workflow actually saves/returns.

The ideal Orange tool can be sophisticated underneath while feeling extremely simple to use.

## Advanced: Manual JSON Configuration

You can also edit `workflows/workflows-config.json` manually. A basic tool looks like:

```json
{
  "id": "my-custom-tool",
  "name": "Enhance Image",
  "workflowFile": "my_exported_api_workflow.json",
  "nodeMapping": {
    "prompt": {
      "nodeId": "6",
      "field": "text"
    },
    "width": {
      "nodeId": "10",
      "field": "width"
    },
    "height": {
      "nodeId": "10",
      "field": "height"
    },
    "seed": {
      "nodeId": "3",
      "field": "seed",
      "generateRandom": true
    },
    "image": {
      "nodeId": "12",
      "field": "image"
    }
  }
}
```

Place the workflow JSON in `workflows/` as well. Configuration is read dynamically, so ordinary tool edits do not require restarting Orange; refresh the browser after saving.

## Defaults and User-Owned Files

Tracked defaults live under `workflows/defaults/`. Active/user-owned configuration lives under `workflows/` and is kept separate so updates can improve Orange without overwriting local tools, prompts, assets, and branding.
