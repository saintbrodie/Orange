# Persistent Workflow Install Jobs

Curated workflow installation in **Admin → Tools → Curated Library** runs as a server-side Orange job rather than a browser-bound request.

## Why

Large model downloads can take many minutes. The browser should be free to change Admin tabs, refresh the page, or close and reopen without losing the install state or making it unclear whether a download is still running.

## Job lifecycle

A workflow install job moves through these stages:

1. `queued` — accepted by Orange and waiting to start.
2. `inspecting` — Orange reads the target ComfyUI `/object_info` and `/system_stats`.
3. `downloading` — only model files missing from the target backend are downloaded.
4. `materializing` — existing model filenames are bound into the curated workflow when no download is required.
5. `preflight` — Orange runs Workflow Preflight and updates routing compatibility.
6. `completed` — the workflow is enabled in Orange.

Failures retain their last stage and error. A retry creates a new job using the same pack, backend, and models path; model files that completed successfully are reused.

## Persistence

Job state is stored locally in:

`workflows/.runtime/workflow-install-jobs.json`

This file is local runtime state and is ignored by Git. Orange keeps the most recent 50 install jobs.

Browser reloads reconnect to the latest job for each pack/backend pair. The Curated Library polls active jobs and renders current stage, filename, downloaded bytes, total bytes when known, transfer speed, destination, and errors.

Orange prevents multiple active installs of the same pack against the same backend. Repeated clicks return the already-running job instead of starting a duplicate model download.

## Orange process restarts

The actual download runs inside the Orange server process. Closing or refreshing the browser does not stop it.

If the **Orange process itself** stops or restarts while a job is active, that process cannot continue the old network stream. On next load Orange converts the stale active job to `interrupted` and presents **Retry** rather than leaving it permanently marked as downloading.

A retry currently restarts an incomplete `.part` file from the beginning. Files that had already completed are detected and skipped.

## API

Admin-authenticated endpoints:

- `GET /api/admin/workflow-packs/install-jobs` — recent job history, optionally filtered by `serverUrl`.
- `GET /api/admin/workflow-packs/install-jobs/{job_id}` — one job.
- `POST /api/admin/workflow-packs/install-jobs` — start or reuse an active job for a pack/backend.
- `POST /api/admin/workflow-packs/install-jobs/{job_id}/retry` — retry a failed/interrupted job.

The older synchronous workflow-pack install/activate endpoints remain available for compatibility, but Curated Library uses the persistent job API.
