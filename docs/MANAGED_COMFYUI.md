# Managed ComfyUI Lifecycle

Orange keeps ComfyUI management deliberately narrow. **Orange declares the known-good revision and validates compatibility; the Pinokio launcher owns Git checkout, dependency sync, and rollback.** Orange does not manage external / bring-your-own ComfyUI installations.

## Known-good revision

The managed runtime contract lives in:

`runtime/managed-runtime.json`

The important field is `comfyui.testedCommit`. Fresh **Orange + ComfyUI** Pinokio installs check out that exact ComfyUI commit instead of following upstream `HEAD` automatically.

Updating this SHA is a maintainer decision. It does not need an automated ComfyUI test farm: use an Orange-managed machine, try the upstream revision, let Orange Preflight the installed workflows, exercise whichever curated workflows are relevant to the upstream changes, and then bump `testedCommit` when comfortable shipping it.

## Update channels

For a Pinokio-managed ComfyUI:

- **Update Orange** updates Orange/launcher code and Orange Python dependencies only. It does not move ComfyUI.
- **Update ComfyUI (Orange-tested)** checks out `testedCommit` and resyncs ComfyUI requirements.
- **Update ComfyUI to Latest (Advanced)** checks out current upstream ComfyUI `HEAD` and labels it upstream/untested.
- **Rollback ComfyUI** returns to the previously recorded ComfyUI commit.

ComfyUI is kept on a detached commit intentionally so a normal source update cannot advance it accidentally.

## Existing managed installs

When this lifecycle system encounters an older Pinokio-managed ComfyUI for the first time, it **adopts the current commit without moving it**. The current SHA is recorded as tested or custom as appropriate. The user decides whether to move to Orange's tested revision.

Lifecycle state is local to the Pinokio installation under `runtime/comfyui-state.json` and is removed by Factory Reset.

## Validation after a ComfyUI change

Before moving ComfyUI, Pinokio records the previous SHA and marks the new runtime as `validation: pending`.

On the next Orange start:

1. Pinokio starts managed ComfyUI and passes Orange the managed ComfyUI directory, lifecycle state path, and local backend URL.
2. Orange waits for `/system_stats` to become reachable.
3. Orange runs Workflow Preflight for every currently installed Orange tool against the managed backend.
4. The existing routing compatibility cache is refreshed.
5. A compact pass/fail result is written back to `runtime/comfyui-state.json`.
6. Admin → General Settings → System Management shows the current SHA, Orange-tested SHA, update channel, previous SHA, and validation result.

A failed validation is visible but **does not trigger an automatic rollback**. The operator can inspect the affected tools and choose **Rollback ComfyUI** from Pinokio.

## External ComfyUI

Orange-only/manual deployments remain externally managed. Orange can inspect `/object_info`, `/system_stats`, health, model availability, and workflow compatibility, but it does not:

- change their Git revision
- install or remove their Python packages
- expose tested/latest/rollback controls for them

This keeps the managed-runtime feature from turning Orange into a general ComfyUI package manager.

## Promoting a newer tested revision

A lightweight maintainer flow is enough:

1. Stop Orange in Pinokio.
2. Choose **Update ComfyUI to Latest (Advanced)** on a test/dogfood install.
3. Start Orange and confirm the managed-runtime Preflight result.
4. Exercise the curated workflow(s) affected by recent ComfyUI changes; run more if the upstream change is broad.
5. If satisfied, update `runtime/managed-runtime.json` to that ComfyUI SHA and its test date.
6. Normal users can then choose **Update ComfyUI (Orange-tested)** to receive it.

There is intentionally no scheduled GPU CI or automatic upstream promotion in the current design.
