import os
import time
import urllib.request

from app.core.workflow_install_jobs import is_cancel_requested, update_file_progress
from app.core.workflow_packs import (
    get_workflow_pack,
    materialize_workflow_pack,
    summarize_system_stats,
)


class InstallCancelled(Exception):
    pass


def _raise_if_canceled(job_id: str) -> None:
    if is_cancel_requested(job_id):
        raise InstallCancelled("Workflow setup canceled.")


def _download_with_progress(url: str, destination: str, job_id: str, filename: str) -> None:
    part_path = destination + ".part"
    if os.path.exists(part_path):
        try:
            os.remove(part_path)
        except OSError:
            pass

    _raise_if_canceled(job_id)
    request = urllib.request.Request(url, headers={"User-Agent": "Orange/1.0"})
    downloaded = 0
    started = time.monotonic()
    last_report = 0.0
    try:
        with urllib.request.urlopen(request) as response, open(part_path, "wb") as output:
            raw_total = response.headers.get("Content-Length")
            try:
                total = int(raw_total) if raw_total else None
            except (TypeError, ValueError):
                total = None

            update_file_progress(
                job_id,
                filename,
                state="downloading",
                bytes_downloaded=0,
                bytes_total=total,
                speed_bps=0,
                destination=destination,
            )

            while True:
                _raise_if_canceled(job_id)
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
                downloaded += len(chunk)
                now = time.monotonic()
                if now - last_report >= 0.75:
                    elapsed = max(now - started, 0.001)
                    update_file_progress(
                        job_id,
                        filename,
                        state="downloading",
                        bytes_downloaded=downloaded,
                        bytes_total=total,
                        speed_bps=downloaded / elapsed,
                        destination=destination,
                    )
                    last_report = now

            output.flush()
            os.fsync(output.fileno())

        _raise_if_canceled(job_id)
        os.replace(part_path, destination)
        elapsed = max(time.monotonic() - started, 0.001)
        update_file_progress(
            job_id,
            filename,
            state="completed",
            bytes_downloaded=downloaded,
            bytes_total=total or downloaded,
            speed_bps=downloaded / elapsed,
            destination=destination,
        )
    except InstallCancelled:
        update_file_progress(
            job_id,
            filename,
            state="canceled",
            bytes_downloaded=downloaded,
            destination=destination,
        )
        raise
    except Exception as exc:
        update_file_progress(job_id, filename, state="failed", error=str(exc), destination=destination)
        raise
    finally:
        if os.path.exists(part_path):
            try:
                os.remove(part_path)
            except OSError:
                pass


def install_workflow_pack_job(
    job_id: str,
    pack_id: str,
    models_root: str,
    system_stats: dict | None,
    selected_models: list[dict],
) -> dict:
    manifest = get_workflow_pack(pack_id)
    root = os.path.abspath(os.path.expanduser(models_root))
    if not os.path.isdir(root):
        raise FileNotFoundError(f"ComfyUI models directory does not exist: {root}")

    installed = []
    skipped = []
    failures = []
    for model in selected_models:
        _raise_if_canceled(job_id)
        filename = os.path.basename(str(model.get("filename", "")).strip())
        if model.get("reuseExisting"):
            skipped.append(str(model.get("filename") or "existing model"))
            if filename:
                update_file_progress(job_id, filename, state="existing")
            continue

        folder = str(model.get("folder", "")).strip()
        url = str(model.get("url", "")).strip()
        if not folder or not filename or not url:
            error = "Invalid model manifest entry"
            failures.append({"filename": filename or "unknown", "error": error})
            if filename:
                update_file_progress(job_id, filename, state="failed", error=error)
            continue

        destination_dir = os.path.join(root, folder)
        os.makedirs(destination_dir, exist_ok=True)
        destination = os.path.join(destination_dir, filename)
        if os.path.exists(destination):
            skipped.append(destination)
            try:
                size = os.path.getsize(destination)
            except OSError:
                size = None
            update_file_progress(
                job_id,
                filename,
                state="existing",
                bytes_downloaded=size,
                bytes_total=size,
                destination=destination,
            )
            continue

        try:
            _download_with_progress(url, destination, job_id, filename)
            installed.append(destination)
        except InstallCancelled:
            raise
        except Exception as exc:
            failures.append({"filename": filename, "error": str(exc)})
            break

    workflow_path = None
    if not failures:
        _raise_if_canceled(job_id)
        workflow_path = materialize_workflow_pack(pack_id, selected_models)

    return {
        "pack": manifest.get("id", pack_id),
        "modelsRoot": root,
        "hardware": summarize_system_stats(system_stats),
        "selectedModels": selected_models,
        "installed": installed,
        "skipped": skipped,
        "failures": failures,
        "workflowPath": workflow_path,
    }
