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

## Repeatable GPU verification

`scripts/verify_comfyui_runtime.py` automates Preflight, local image/video generation,
output retrieval/decoding, and promotion. It never updates or restarts ComfyUI.
Run a **separate test checkout and environment**, with the exact candidate
requirements installed and existing model files exposed through an extra model
paths file. Launch with an absolute `main.py` path on a dedicated loopback port.
Do not move the checkout while its test server is running.

For example, after starting the candidate on port 8197:

```powershell
python scripts/verify_comfyui_runtime.py --comfy-dir C:\test\ComfyUI --ref v0.42.5 --url http://127.0.0.1:8197 --config C:\pinokio\api\orange\app\workflows\workflows-config.json --report runtime/verification/report.json --smoke --promote
```

The config selects the **installed Pinokio tools**. Workflow files are read from
that config's directory, with bundled defaults as fallback. Running without
`--smoke` checks compatibility only and cannot promote. `--promote` updates
`testedCommit`, `testedVersion`, and `testedDate` only when every configured tool
passes both checks and all bundled curated packs are covered. Missing
models, execution errors, timeouts, unavailable outputs, and undecodable images
block promotion. Reports include exact source and workflow hashes, runtime
versions, prompts' IDs, warnings, and errors. Reports and test checkouts live in
the ignored `runtime/verification/` directory.
Successful promotion also writes a compact, shareable record to
`runtime/managed-runtime-verification.json` alongside the pin.

Smoke tests use fixed seeds, 512px mapped generation sizes, and a generated
256px input fixture for image tools. They retain model choices and sampling
settings. This verifies execution and output transport; it does not grade image
quality, test every resolution/platform/GPU, or exercise Orange's browser UI.
A source checkout/version check prevents accidental verification against a
different installation. Start a fresh test process for every candidate: Git HEAD
alone cannot prove which code a long-running process has loaded.

### Scheduled maintenance on a local GPU machine

A Codex recurring automation can orchestrate this process (the machine and app
must be running). The local maintainer schedule is Monday at 04:00 Eastern:

1. Resolve a newer stable upstream tag to a full commit. Use stable version tags,
   not the moving `latest` portable-build tag or development HEAD.
2. Check queues and GPU memory; defer while normal generation work is active.
3. Fetch the candidate into the separate test checkout. Sync its requirements in
   an isolated environment without changing the user's normal installation.
   Existing model files may be reused; do not silently download new models.
4. Start a fresh loopback test server, then run the verifier against the current
   Pinokio tools with `--smoke --promote`. Run Orange's unit tests too. Never
   submit paid API workflows as smoke tests.
5. Keep the old pin on failure. Retain the report and flag new blockers. When
   verification and focused tests pass, review the manifest and evidence diff,
   then commit and publish only the pin, verification record, and related
   maintenance changes to the repository's default branch. Check the full suite
   for new failures against its known baseline. Respect branch protections and
   never force-push or include unrelated working changes. Notify the user of the
   published commit. Installed Pinokio copies still use their normal update action.
6. Stop only the test process started by this run to release its GPU memory.

The automation belongs to the maintainer's local Codex setup; cloning this
repository does not register a schedule or install a background service.

### Current verification

On 2026-10-26, v0.42.5 (`483dae4326356b81de05d27aca3f433dd323cc25`)
passed Preflight and image smoke tests for the Pinokio install's four tools:
Z-Image, Krea 2, Klein editing, and SeedVR2 upscaling. The isolated test environment
used the candidate's pinned ComfyUI packages with Python 3.12.12 and PyTorch
2.13.0+cu130, reusing GPU libraries and model files from the local machine.
This was not a clean Pinokio installation test.

The focused runtime tests passed. The full Orange unit suite also revealed
Windows SQLite temporary-file cleanup errors and an Admin provider-label
assertion failure in areas untouched by this update. These remain separate
issues; the GPU verification record does not imply a clean full CI run.

### Video packs

The verifier also generates and decodes video outputs. Supply `--video-python`
with the candidate ComfyUI environment's Python executable so its existing PyAV
installation can check the MP4. Video tests use a 384x256 mapped base size and
retain the workflow's frame count, audio path, and sampling settings. The LTX 2.5
pack upscales this to 768x512. A missing video, failed fetch, or undecodable video
blocks promotion just like an image failure. Every new curated pack must be
included in the verification configuration before a future pin can be promoted.

Video tools with an optional `imageVariant` are verified in both modes, including
an uploaded fixture for the first-frame graph. Duration uses the configured
default and the same seconds-to-frame conversion as normal requests.
