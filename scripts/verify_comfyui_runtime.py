"""Preflight and GPU smoke tests for an isolated ComfyUI candidate.

Does not install, update, launch, or restart ComfyUI. Point this at a separate
test server launched with an absolute main.py path. Promotion requires every
curated pack plus every configured tool to pass in this invocation.
"""
import argparse
import ast
import asyncio
import copy
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import time
from datetime import datetime, timezone
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx
from PIL import Image

from app.core.managed_runtime import _routing_compatible
from app.core.outputs import collect_media_outputs
from app.core.preflight import run_preflight
from app.core.submission import submit_prompt, upload_image_bytes


def git(repo, *args):
    return subprocess.check_output(
        ["git", "-C", str(repo), *args], text=True, stderr=subprocess.STDOUT
    ).strip()


def source_commit(repo, ref):
    head = git(repo, "rev-parse", "HEAD")
    if head != git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}"):
        raise ValueError("Candidate checkout does not match the requested ref")
    if git(repo, "status", "--porcelain", "--untracked-files=no"):
        raise ValueError("Candidate has modified tracked files")
    return head


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def required_pack_ids():
    return {
        json.loads(path.read_text(encoding="utf-8"))["tool"]["id"]
        for path in (ROOT / "workflow-packs").glob("*/manifest.json")
    }


def promotion_ready(report):
    tools = report.get("tools", [])
    return bool(
        report.get("passed") and tools
        and required_pack_ids().issubset({item["id"] for item in tools})
        and all(item.get("preflightPassed") and item.get("smokePassed") for item in tools)
    )


def verification_summary(report):
    return {
        key: report[key] for key in ("schemaVersion", "commit", "ref", "checkedAt", "orangeCommit", "passed")
    } | {
        "system": {key: report["system"].get(key) for key in (
            "comfyui_version", "python_version", "pytorch_version", "comfy_package_versions",
        )},
        "tools": [{key: tool[key] for key in (
            "id", "workflowSha256", "preflightPassed", "smokePassed",
        )} for tool in report["tools"]],
        "scope": "512px mapped image generation sizes; 384x256 mapped video base size; 256px fixture for editing/upscaling; output retrieval and media decoding. No visual-quality or browser UI assessment.",
    }


def prepare_workflow(workflow, mapping, image_name, output_type="image"):
    workflow = copy.deepcopy(workflow)
    values = {
        "prompt": "A bright orange ceramic mug on a plain blue table, studio photograph",
        "seed": 12345, "width": 384 if output_type == "video" else 512, "height": 256 if output_type == "video" else 512,
        "image": image_name, "image2": image_name,
    }
    for key, value in values.items():
        entry = mapping.get(key)
        if entry:
            workflow[str(entry["nodeId"])]["inputs"][entry["field"]] = value
    # Give test outputs their own namespace; leave models and sampling unchanged.
    for node in workflow.values():
        if node.get("class_type") in {"SaveImage", "SaveVideo"}:
            node["inputs"]["filename_prefix"] = "orange-verification/smoke"
    return workflow


def decode_video(data, python_executable):
    # Use the candidate ComfyUI environment, where PyAV is already required.
    code = """import av,io,json,sys
with av.open(io.BytesIO(sys.stdin.buffer.read())) as container:
    frame = next(container.decode(video=0))
    print(json.dumps(dict(width=frame.width,height=frame.height,
                         audioStreams=len(container.streams.audio))))
"""
    try:
        decoded = subprocess.run([python_executable, "-c", code], input=data,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 check=True, timeout=60)
    except subprocess.CalledProcessError as exc:
        raise ValueError("Video decode failed: " + exc.stderr.decode(errors="replace")[-1500:]) from exc
    return json.loads(decoded.stdout)


async def smoke(client, url, workflow, timeout, output_type="image", video_python=sys.executable):
    payload = await submit_prompt(client, url, {"prompt": workflow, "client_id": str(uuid.uuid4())})
    prompt_id = payload["prompt_id"]
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = await client.get(f"{url}/history/{prompt_id}")
        response.raise_for_status()
        record = response.json().get(prompt_id)
        if record:
            status = record.get("status", {})
            if status.get("status_str") == "error":
                raise ValueError(f"Generation {prompt_id} failed: {status.get('messages')}")
            if status.get("completed"):
                items = collect_media_outputs(record.get("outputs", {}), output_type)
                if not items:
                    raise ValueError(f"Generation {prompt_id} completed without an image" if output_type == "image" else f"Generation {prompt_id} completed without a video")
                output = items[0]
                media = await client.get(f"{url}/view", params={
                    "filename": output["filename"], "subfolder": output["subfolder"], "type": output["type"],
                })
                media.raise_for_status()
                result = {"promptId": prompt_id, "output": output, "bytes": len(media.content)}
                if output_type == "video":
                    result["video"] = decode_video(media.content, video_python)
                else:
                    with Image.open(io.BytesIO(media.content)) as image:
                        image.verify()
                return result
        await asyncio.sleep(2)
    # Remove only our pending job; never interrupt another user's running work.
    await client.post(f"{url}/queue", json={"delete": [prompt_id]})
    raise TimeoutError(f"Generation {prompt_id} timed out; a running test may need operator attention")


async def verify(args):
    repo = Path(args.comfy_dir).resolve()
    commit = source_commit(repo, args.ref)
    url = args.url.rstrip("/")
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    workflow_dir = Path(args.config).resolve().parent
    tools = config.get("tools", [])
    if not tools or len({tool["id"] for tool in tools}) != len(tools):
        raise ValueError("Verification requires a nonempty list of unique tools")
    report = {"schemaVersion": 1, "commit": commit, "ref": args.ref,
              "checkedAt": datetime.now(timezone.utc).isoformat(), "url": url,
              "orangeCommit": git(ROOT, "rev-parse", "HEAD"), "tools": [], "passed": False}
    async with httpx.AsyncClient(timeout=60) as client:
        stats = await client.get(f"{url}/system_stats")
        stats.raise_for_status()
        system = stats.json()["system"]
        main = system.get("argv", [None])[0]
        if not main or not Path(main).is_absolute() or Path(main).resolve() != repo / "main.py":
            raise ValueError("Server must be launched using the candidate's absolute main.py path")
        version_source = ast.parse((repo / "comfyui_version.py").read_text(encoding="utf-8"))
        version = next(ast.literal_eval(node.value) for node in version_source.body
                       if isinstance(node, ast.Assign) and any(
                           isinstance(target, ast.Name) and target.id == "__version__" for target in node.targets))
        if system.get("comfyui_version") != version:
            raise ValueError("Running ComfyUI version does not match the candidate source; restart the test backend")
        if any(package.get("installed") != package.get("required")
               for package in system.get("comfy_package_versions", [])):
            raise ValueError("Candidate runtime has mismatched ComfyUI package versions")
        # A stale process can load old code even when Git HEAD has moved.
        # Only verify a dedicated server started after the candidate checkout.
        report["system"] = system
        queue = await client.get(f"{url}/queue")
        queue.raise_for_status()
        if any(queue.json().get(key) for key in ("queue_running", "queue_pending")):
            raise ValueError("Test backend is busy; defer verification")
        image_name = None
        if args.smoke:
            fixture = io.BytesIO()
            Image.new("RGB", (256, 256), (240, 140, 40)).save(fixture, "PNG")
            image_name = await upload_image_bytes(client, url, f"orange-smoke-{uuid.uuid4().hex}.png", fixture.getvalue(), "image/png")
        for tool in tools:
            result = {"id": tool["id"], "preflightPassed": False, "smokePassed": False}
            report["tools"].append(result)
            try:
                workflow_path = workflow_dir / Path(tool["workflowFile"]).name
                if not workflow_path.is_file():
                    workflow_path = ROOT / "workflows" / "defaults" / Path(tool["workflowFile"]).name
                original = json.loads(workflow_path.read_text(encoding="utf-8"))
                output_type = tool.get("outputType", "image")
                if output_type not in {"image", "video"}:
                    raise ValueError("Smoke verification currently supports image and video tools")
                result["workflowSha256"] = hashlib.sha256(json.dumps(original, sort_keys=True).encode()).hexdigest()
                workflow = prepare_workflow(original, tool.get("nodeMapping", {}), image_name, output_type) if args.smoke else original
                check = await run_preflight(tool["workflowFile"], workflow, tool.get("nodeMapping", {}), [{"url": url, "priority": 1}])
                result["preflight"] = check
                result["preflightPassed"] = bool(
                    not check["local"]["errors"] and check["backends"]
                    and all(_routing_compatible(backend) for backend in check["backends"])
                )
                if result["preflightPassed"] and args.smoke:
                    result["smoke"] = await smoke(client, url, workflow, args.timeout, output_type, args.video_python)
                    result["smokePassed"] = True
            except Exception as exc:
                result["error"] = str(exc)
            write_json(args.report, report)
            print(f"{tool['id']}: preflight={result['preflightPassed']} smoke={result['smokePassed']}", flush=True)
            if result.get("error", "").startswith("Generation") and "timed out" in result["error"]:
                break
    source_commit(repo, args.ref)
    report["passed"] = bool(len(report["tools"]) == len(tools) and all(
        item["preflightPassed"] and item["smokePassed"] for item in report["tools"]
    ))
    report["promotionReady"] = promotion_ready(report)
    report["preflightPassed"] = bool(len(report["tools"]) == len(tools) and all(
        item["preflightPassed"] for item in report["tools"]
    ))
    write_json(args.report, report)
    if args.promote:
        if not report["promotionReady"]:
            raise ValueError("Pin unchanged: all configured tools and curated packs must pass GPU smoke tests")
        manifest_path = ROOT / "runtime" / "managed-runtime.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["comfyui"].update({
            "testedCommit": commit, "testedDate": report["checkedAt"][:10],
            "testedVersion": args.ref,
            "note": "Preflight and GPU media smoke tests passed for all curated packs and configured tools. See docs/MANAGED_COMFYUI.md for scope.",
        })
        write_json(ROOT / "runtime" / "managed-runtime-verification.json", verification_summary(report))
        write_json(manifest_path, manifest)
    return 0 if (report["passed"] if args.smoke else report["preflightPassed"]) else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--comfy-dir", required=True)
    parser.add_argument("--ref", required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--config", default=str(ROOT / "workflows" / "workflows-config.json"))
    parser.add_argument("--report", default=str(ROOT / "runtime" / "verification" / "report.json"))
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--video-python", default=sys.executable, help="Python executable with PyAV for video output decoding (candidate ComfyUI environment)")
    parser.add_argument("--smoke", action="store_true", help="Submit local GPU image/video jobs")
    parser.add_argument("--promote", action="store_true", help="Update the tested pin only after this run passes")
    args = parser.parse_args()
    if args.promote and not args.smoke:
        parser.error("--promote requires --smoke")
    try:
        return asyncio.run(verify(args))
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
