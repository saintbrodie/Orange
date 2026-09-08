import asyncio
import copy
import mimetypes
import os
import random
import uuid

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

from app.api.generate import MAX_PROMPT_CHARS, MAX_UPLOAD_BYTES, MAX_UPLOAD_MB, _read_validated_image
from app.core.backends import (
    decrement_active,
    get_backend_client,
    get_best_backend,
    increment_active,
    report_backend_failure,
    report_backend_success,
    workflow_compatibility_key,
)
from app.core.config import get_base_workflow, get_comfy_servers, get_tool_settings, load_config
from app.core.database import log_usage
from app.core.submission import SubmissionFailure, submit_prompt, upload_image_bytes
from app.core.workflow_assets import find_managed_asset_references

router = APIRouter()


def _prepare_asset_payloads(base_workflow: dict, mapping: dict, workflow_file: str):
    references = find_managed_asset_references(base_workflow, mapping, workflow_file)
    payloads = {}
    for _node_id, _field, asset_name, asset_path in references:
        if asset_name in payloads:
            continue
        if os.path.getsize(asset_path) > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"Workflow asset '{asset_name}' exceeds the {MAX_UPLOAD_MB} MB upload limit.",
            )
        with open(asset_path, "rb") as handle:
            image_bytes = handle.read()
        content_type = mimetypes.guess_type(asset_name)[0] or "application/octet-stream"
        payloads[asset_name] = (image_bytes, content_type)
    return references, payloads


async def _stage_assets(
    workflow: dict,
    references: list,
    payloads: dict,
    target_url: str,
    client,
):
    uploaded_names = {}
    for node_id, field, asset_name, _asset_path in references:
        uploaded_name = uploaded_names.get(asset_name)
        if uploaded_name is None:
            image_bytes, content_type = payloads[asset_name]
            uploaded_name = await upload_image_bytes(
                client,
                target_url,
                asset_name,
                image_bytes,
                content_type,
            )
            uploaded_names[asset_name] = uploaded_name
        workflow[node_id]["inputs"][field] = uploaded_name


@router.post("/api/generate")
async def generate_v2(
    request: Request,
    tool_id: str = Form(...),
    prompt: str = Form(None),
    aspect_ratio: str = Form(None),
    image: UploadFile = File(None),
    image2: UploadFile = File(None),
):
    client_ip = request.client.host if request.client else "unknown"

    if prompt and len(prompt) > MAX_PROMPT_CHARS:
        raise HTTPException(status_code=413, detail=f"Prompt exceeds the {MAX_PROMPT_CHARS} character limit.")

    tool = get_tool_settings(tool_id)
    if not tool:
        raise HTTPException(status_code=400, detail="Invalid tool ID")

    mapping = tool.get("nodeMapping", {})
    workflow_file = tool.get("workflowFile")
    try:
        base_workflow = get_base_workflow(workflow_file)
    except Exception as exc:
        log_usage(
            client_ip,
            tool_id,
            prompt,
            status="submission_failed",
            error=f"Workflow load failure: {type(exc).__name__}: {exc}",
        )
        raise HTTPException(status_code=500, detail="This tool's workflow could not be loaded. Check it in the admin dashboard.")

    compatibility_key = workflow_compatibility_key(workflow_file, base_workflow, mapping)

    if mapping.get("prompt") and not prompt:
        raise HTTPException(status_code=400, detail="Prompt is required for this tool")
    if mapping.get("image") and not image:
        raise HTTPException(status_code=400, detail="Image is required for this tool")
    if mapping.get("image2") and not image2:
        raise HTTPException(status_code=400, detail="Second image is required for this tool")

    # Validate and read user media once. Retries can then safely upload the exact
    # same bytes to another backend without depending on a consumed UploadFile.
    image_payload = await _read_validated_image(image) if image and mapping.get("image") else None
    image2_payload = await _read_validated_image(image2) if image2 and mapping.get("image2") else None
    try:
        asset_references, asset_payloads = _prepare_asset_payloads(base_workflow, mapping, workflow_file)
    except HTTPException:
        raise
    except Exception as exc:
        log_usage(
            client_ip,
            tool_id,
            prompt,
            status="submission_failed",
            error=f"Workflow asset preparation failure: {type(exc).__name__}: {exc}",
        )
        raise HTTPException(status_code=500, detail="This tool's fixed workflow assets could not be prepared.")

    config = load_config()
    ratio_values = None
    if aspect_ratio and mapping.get("width") and mapping.get("height"):
        ratio_values = tool.get("aspectRatios", config.get("aspectRatios", {})).get(aspect_ratio)

    # One Orange generation has one seed. Safe backend failover must not silently
    # turn the retry into a different creative request.
    generated_seed = None
    if mapping.get("seed") and mapping["seed"].get("generateRandom"):
        generated_seed = random.randint(1, 1125899906)

    client_id = str(uuid.uuid4())
    exclude_urls = []
    last_failure = None

    while True:
        target_url = await get_best_backend(
            exclude_urls=exclude_urls,
            compatibility_key=compatibility_key,
        )
        if not target_url:
            technical = str(last_failure) if last_failure else "No healthy compatible backend was available."
            log_usage(
                client_ip,
                tool_id,
                prompt,
                backend_url=exclude_urls[-1] if exclude_urls else None,
                status="submission_failed",
                error=technical,
            )
            detail = (
                "All compatible generation backends failed to accept the request."
                if last_failure
                else "No healthy compatible ComfyUI servers are available."
            )
            raise HTTPException(status_code=503, detail=detail)

        increment_active(target_url)
        queued = False
        client = await get_backend_client()
        try:
            workflow = copy.deepcopy(base_workflow)
            await _stage_assets(workflow, asset_references, asset_payloads, target_url, client)

            uploaded_image_name = None
            if image_payload:
                filename, image_bytes, content_type = image_payload
                uploaded_image_name = await upload_image_bytes(
                    client, target_url, filename, image_bytes, content_type
                )

            uploaded_image2_name = None
            if image2_payload:
                filename, image_bytes, content_type = image2_payload
                uploaded_image2_name = await upload_image_bytes(
                    client, target_url, filename, image_bytes, content_type
                )

            if prompt and mapping.get("prompt"):
                p_map = mapping["prompt"]
                workflow[p_map["nodeId"]]["inputs"][p_map["field"]] = prompt

            if uploaded_image_name and mapping.get("image"):
                i_map = mapping["image"]
                workflow[i_map["nodeId"]]["inputs"][i_map["field"]] = uploaded_image_name

            if uploaded_image2_name and mapping.get("image2"):
                i2_map = mapping["image2"]
                workflow[i2_map["nodeId"]]["inputs"][i2_map["field"]] = uploaded_image2_name

            if ratio_values:
                w_map = mapping["width"]
                h_map = mapping["height"]
                workflow[w_map["nodeId"]]["inputs"][w_map["field"]] = ratio_values["width"]
                workflow[h_map["nodeId"]]["inputs"][h_map["field"]] = ratio_values["height"]

            if generated_seed is not None:
                s_map = mapping["seed"]
                workflow[s_map["nodeId"]]["inputs"][s_map["field"]] = generated_seed

            data = await submit_prompt(
                client,
                target_url,
                {"prompt": workflow, "client_id": client_id},
            )
            queued = True
            report_backend_success(target_url)

        except SubmissionFailure as exc:
            last_failure = exc
            if exc.mark_backend_failed:
                report_backend_failure(target_url, exc.technical_message)

            if exc.retryable:
                exclude_urls.append(target_url)
                continue

            log_usage(
                client_ip,
                tool_id,
                prompt,
                backend_url=target_url,
                status="submission_failed",
                error=exc.technical_message,
            )
            raise HTTPException(status_code=exc.status_code, detail=exc.public_message)
        except Exception as exc:
            technical = f"Local workflow preparation failure: {type(exc).__name__}: {exc}"
            log_usage(
                client_ip,
                tool_id,
                prompt,
                backend_url=target_url,
                status="submission_failed",
                error=technical,
            )
            raise HTTPException(
                status_code=422,
                detail="Orange could not prepare this workflow. Run Workflow Preflight or check the tool mappings.",
            )
        finally:
            if not queued:
                decrement_active(target_url)

        break

    # Keep the short routing reservation after queue acknowledgement so another
    # simultaneous request does not select the same backend before /queue catches up.
    asyncio.get_running_loop().call_later(2.0, decrement_active, target_url)

    server_priority = next(
        (s.get("priority", 1) for s in get_comfy_servers() if str(s.get("url", "")).rstrip("/") == target_url),
        1,
    )
    prompt_id = data.get("prompt_id")
    log_usage(client_ip, tool_id, prompt, prompt_id=prompt_id, backend_url=target_url)

    return {
        "prompt_id": prompt_id,
        "client_id": client_id,
        "server_priority": server_priority,
    }
