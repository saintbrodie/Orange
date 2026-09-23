from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace(path, old, new, count=1):
    file = ROOT / path
    text = file.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"Expected patch text not found in {path}: {old[:100]!r}")
    text = text.replace(old, new, count)
    file.write_text(text, encoding="utf-8")


# LLM provider plumbing.
replace(
    "app/core/llm.py",
    'SUPPORTED_PROVIDERS = {"openai", "ollama", "gemini", "anthropic"}',
    'SUPPORTED_PROVIDERS = {"managed", "openai", "ollama", "gemini", "anthropic"}',
)
replace(
    "app/core/llm.py",
    '    if provider == "ollama":\n        return\n',
    '    if provider in {"ollama", "managed"}:\n        return\n',
)
replace(
    "app/core/llm.py",
    '''    provider = normalize_provider(provider)\n    base_url = validate_base_url(base_url)\n    model = validate_model(model)\n    system_prompt = str(system_prompt or "").strip()\n''',
    '''    provider = normalize_provider(provider)\n    if provider == "managed":\n        from app.core.managed_prompt_enhancer import MANAGED_BASE_URL, MANAGED_MODEL_ID, ensure_server_ready\n\n        try:\n            await ensure_server_ready()\n        except RuntimeError as exc:\n            raise LLMError(\n                "Managed Local prompt enhancement is unavailable.",\n                str(exc),\n                status_code=503,\n            )\n        base_url = MANAGED_BASE_URL\n        api_key = None\n        model = MANAGED_MODEL_ID\n    else:\n        base_url = validate_base_url(base_url)\n        model = validate_model(model)\n    system_prompt = str(system_prompt or "").strip()\n''',
)
replace(
    "app/core/llm.py",
    '        if provider == "openai":\n            url = _endpoint(base_url, "https://api.openai.com/v1", "chat/completions")',
    '        if provider in {"openai", "managed"}:\n            url = _endpoint(base_url, "https://api.openai.com/v1", "chat/completions")',
)
replace(
    "app/core/llm.py",
    '''    provider = normalize_provider(provider)\n    base_url = validate_base_url(base_url)\n    resolved_key = resolve_api_key(provider, api_key)\n''',
    '''    provider = normalize_provider(provider)\n    if provider == "managed":\n        from app.core.managed_prompt_enhancer import MANAGED_MODEL_ID\n\n        return [MANAGED_MODEL_ID]\n    base_url = validate_base_url(base_url)\n    resolved_key = resolve_api_key(provider, api_key)\n''',
)

# Config validation recognizes Managed Local.
replace(
    "app/core/config_validation.py",
    'ALLOWED_LLM_PROVIDERS = {"openai", "ollama", "gemini", "anthropic"}',
    'ALLOWED_LLM_PROVIDERS = {"managed", "openai", "ollama", "gemini", "anthropic"}',
)

# Setup API advertises and optionally starts the local enhancer.
replace(
    "app/api/setup.py",
    'from app.core.onboarding import detect_install_mode, managed_comfy_dir, managed_models_root, mark_setup_complete, setup_required\n',
    'from app.core.onboarding import detect_install_mode, managed_comfy_dir, managed_models_root, mark_setup_complete, setup_required\nfrom app.core.managed_prompt_enhancer import MANAGED_MODEL_ID, get_status as get_managed_prompt_status, schedule_install as schedule_managed_prompt_install\n',
)
replace(
    "app/api/setup.py",
    '''        "detectedModelsRoot": model_root,\n        "packs": list_workflow_packs(),\n    }\n''',
    '''        "detectedModelsRoot": model_root,\n        "packs": list_workflow_packs(),\n        "managedPromptEnhancer": get_managed_prompt_status(),\n    }\n''',
)
replace(
    "app/api/setup.py",
    '''    known_packs = {str(pack["id"]) for pack in list_workflow_packs()}\n    selected_packs = _selected_pack_ids(payload, known_packs)\n\n    object_info, _queue, system_stats = await _read_backend_metadata(comfy_url)\n''',
    '''    known_packs = {str(pack["id"]) for pack in list_workflow_packs()}\n    selected_packs = _selected_pack_ids(payload, known_packs)\n    use_managed_prompt = bool(payload.get("managedPromptEnhancer", False))\n    managed_prompt_status = get_managed_prompt_status()\n    if use_managed_prompt and not managed_prompt_status.get("supported"):\n        raise HTTPException(\n            status_code=400,\n            detail=f"Managed Local prompt enhancement is not packaged for {managed_prompt_status.get('platform', 'this platform')}.",\n        )\n\n    object_info, _queue, system_stats = await _read_backend_metadata(comfy_url)\n''',
)
replace(
    "app/api/setup.py",
    '''    config = dict(load_config())\n    config["tools"] = []\n    pack_results = []\n''',
    '''    config = dict(load_config())\n    config["tools"] = []\n    if use_managed_prompt:\n        config["llm"] = {\n            "enabled": True,\n            "provider": "managed",\n            "baseUrl": "",\n            "apiKey": "",\n            "model": MANAGED_MODEL_ID,\n        }\n    pack_results = []\n''',
)
replace(
    "app/api/setup.py",
    '''    mark_setup_complete()\n    await backend_manager.refresh_all()\n\n    return {\n''',
    '''    mark_setup_complete()\n    await backend_manager.refresh_all()\n\n    enhancer_result = None\n    if use_managed_prompt:\n        try:\n            enhancer_result = schedule_managed_prompt_install()\n        except Exception as exc:\n            enhancer_result = {"state": "failed", "error": str(exc)}\n\n    return {\n''',
)
replace(
    "app/api/setup.py",
    '''        "installedPackCount": sum(1 for item in pack_results if item.get("installed")),\n        "packs": pack_results,\n    }\n''',
    '''        "installedPackCount": sum(1 for item in pack_results if item.get("installed")),\n        "packs": pack_results,\n        "managedPromptEnhancer": enhancer_result,\n    }\n''',
)

# Register API + stop child process on Orange shutdown.
replace(
    "app/main.py",
    'from app.api import admin, backend_status, db_admin, generate, generation_debug, generation_v2, llm_api, managed_runtime, outputs, personalization, preflight, setup, status, workflow_assets, workflow_pack_admin, workflows\n',
    'from app.api import admin, backend_status, db_admin, generate, generation_debug, generation_v2, llm_api, managed_prompt_enhancer, managed_runtime, outputs, personalization, preflight, setup, status, workflow_assets, workflow_pack_admin, workflows\n',
)
replace(
    "app/main.py",
    'from app.core.managed_runtime import validate_pending_managed_runtime\n',
    'from app.core.managed_runtime import validate_pending_managed_runtime\nfrom app.core.managed_prompt_enhancer import stop_server as stop_managed_prompt_enhancer\n',
)
replace(
    "app/main.py",
    '''        await asyncio.gather(runtime_validation_task, return_exceptions=True)\n        await backend_manager.stop()\n''',
    '''        await asyncio.gather(runtime_validation_task, return_exceptions=True)\n        stop_managed_prompt_enhancer()\n        await backend_manager.stop()\n''',
)
replace(
    "app/main.py",
    'app.include_router(managed_runtime.router)\n',
    'app.include_router(managed_runtime.router)\napp.include_router(managed_prompt_enhancer.router)\n',
)
replace(
    "app/main.py",
    '''            '    <script src="/static/managed-comfyui.js?v=1"></script>\\n'\n            '    <script src="/static/mobile-navigation.js?v=4"></script>\\n'\n''',
    '''            '    <script src="/static/managed-comfyui.js?v=1"></script>\\n'\n            '    <script src="/static/managed-prompt-enhancer.js?v=1"></script>\\n'\n            '    <script src="/static/mobile-navigation.js?v=4"></script>\\n'\n''',
)

# Runtime state should never be committed.
replace(
    ".gitignore",
    'workflows/assets/\n',
    'workflows/assets/\nworkflows/.runtime/\n',
)

# Admin provider option + cache bump.
replace(
    "static/admin.html",
    '<option value="openai">OpenAI / Compatible (LM Studio, llama.cpp, OpenRouter)</option>',
    '<option value="managed">Managed Local — Gemma 4 E2B (Private)</option>\n                                        <option value="openai">OpenAI / Compatible (LM Studio, llama.cpp, OpenRouter)</option>',
)
replace(
    "static/admin.html",
    '<script src="/static/admin.js?v=6"></script>',
    '<script src="/static/admin.js?v=7"></script>',
)

# Admin save/load behavior for fixed managed model.
replace(
    "static/admin.js",
    '''        const llmDefaults = {\n            openai: "https://api.openai.com/v1",\n''',
    '''        const llmDefaults = {\n            managed: "",\n            openai: "https://api.openai.com/v1",\n''',
)
replace(
    "static/admin.js",
    '''                populateModelSelect(\n                    document.getElementById('setting-llm-model'),\n                    'setting-llm-model-custom-container',\n                    'setting-llm-model-custom',\n                    provider,\n                    document.getElementById('setting-llm-model').value,\n                    activeFetchedModels\n                );\n            });\n''',
    '''                populateModelSelect(\n                    document.getElementById('setting-llm-model'),\n                    'setting-llm-model-custom-container',\n                    'setting-llm-model-custom',\n                    provider,\n                    document.getElementById('setting-llm-model').value,\n                    activeFetchedModels\n                );\n                if (window.syncManagedEnhancerProviderUI) window.syncManagedEnhancerProviderUI();\n            });\n''',
)
replace(
    "static/admin.js",
    '''                    toggleGlobalLlm();\n\n                    if (appConfig.aspectRatios) {\n''',
    '''                    toggleGlobalLlm();\n                    if (window.syncManagedEnhancerProviderUI) window.syncManagedEnhancerProviderUI();\n\n                    if (appConfig.aspectRatios) {\n''',
)
replace(
    "static/admin.js",
    '''            const modelSelectVal = document.getElementById('setting-llm-model').value;\n            const modelVal = modelSelectVal === '__custom__'\n                ? document.getElementById('setting-llm-model-custom').value.trim()\n                : modelSelectVal;\n\n            const globalSystemPromptVal = document.getElementById('setting-llm-systemprompt').value.trim();\n            appConfig.llm = {\n                enabled: document.getElementById('setting-llm-enabled').checked,\n                provider: document.getElementById('setting-llm-provider').value,\n                model: modelVal,\n                baseUrl: document.getElementById('setting-llm-baseurl').value.trim(),\n                apiKey: document.getElementById('setting-llm-apikey').value.trim()\n            };\n''',
    '''            const providerVal = document.getElementById('setting-llm-provider').value;\n            const modelSelectVal = document.getElementById('setting-llm-model').value;\n            const selectedModelVal = modelSelectVal === '__custom__'\n                ? document.getElementById('setting-llm-model-custom').value.trim()\n                : modelSelectVal;\n            const modelVal = providerVal === 'managed' ? 'gemma-4-e2b' : selectedModelVal;\n\n            const globalSystemPromptVal = document.getElementById('setting-llm-systemprompt').value.trim();\n            appConfig.llm = {\n                enabled: document.getElementById('setting-llm-enabled').checked,\n                provider: providerVal,\n                model: modelVal,\n                baseUrl: providerVal === 'managed' ? '' : document.getElementById('setting-llm-baseurl').value.trim(),\n                apiKey: providerVal === 'managed' ? '' : document.getElementById('setting-llm-apikey').value.trim()\n            };\n''',
)

# First-run managed local option.
replace(
    "static/setup.html",
    '''    <section class="card">\n      <div class="step">3</div>\n      <div class="content">\n        <h2>Secure Admin</h2>\n''',
    '''    <section class="card">\n      <div class="step">3</div>\n      <div class="content">\n        <h2>Prompt enhancement <span class="optional-label">Optional</span></h2>\n        <p class="hint">Orange can expand short prompts locally without an API key. You can also configure Ollama, LM Studio, or a cloud API later.</p>\n        <label class="pack optional-pack">\n          <input type="checkbox" id="managed-enhancer">\n          <div class="pack-body">\n            <div class="pack-title">Managed Local <span>Recommended</span></div>\n            <p>Gemma 4 E2B Instruct · Q4_0 QAT · about 3.35 GB. Runs privately through Orange's own llama.cpp runtime, CPU-first so it does not reserve ComfyUI GPU memory.</p>\n            <div id="managed-enhancer-status" class="pack-status neutral">The model downloads in the background after setup and unloads from memory after 5 idle minutes.</div>\n          </div>\n        </label>\n      </div>\n    </section>\n\n    <section class="card">\n      <div class="step">4</div>\n      <div class="content">\n        <h2>Secure Admin</h2>\n''',
)
replace(
    "static/setup.html",
    '<script src="/static/setup.js?v=3"></script>',
    '<script src="/static/setup.js?v=4"></script>',
)

# Setup JS availability, payload, and background-install handoff.
replace(
    "static/setup.js",
    '''  renderPacks();\n}\n\nfunction hardwareLabel(hardware) {\n''',
    '''  renderPacks();\n\n  const enhancer = setupStatus.managedPromptEnhancer || {};\n  const enhancerCheckbox = $("managed-enhancer");\n  const enhancerStatus = $("managed-enhancer-status");\n  if (enhancerCheckbox && enhancerStatus) {\n    enhancerCheckbox.disabled = enhancer.supported === false;\n    enhancerCheckbox.checked = !!enhancer.installed;\n    if (enhancer.installed) {\n      enhancerStatus.textContent = "✓ Gemma 4 is already installed and ready.";\n      enhancerStatus.className = "pack-status ready";\n    } else if (enhancer.supported === false) {\n      enhancerStatus.textContent = `Managed Local is not packaged for ${enhancer.platform || "this platform"}. Configure Ollama or an API later.`;\n      enhancerStatus.className = "pack-status warning";\n    }\n  }\n}\n\nfunction hardwareLabel(hardware) {\n''',
)
replace(
    "static/setup.js",
    '''        adminKey,\n        selectedPacks: packs,\n      }),\n''',
    '''        adminKey,\n        selectedPacks: packs,\n        managedPromptEnhancer: !!$("managed-enhancer")?.checked,\n      }),\n''',
)
replace(
    "static/setup.js",
    '''    const failures = (data.packs || []).filter((pack) => !pack.installed);\n    if (failures.length) {\n''',
    '''    localStorage.setItem("orange_admin_key", adminKey);\n    const managedEnhancerSelected = !!$("managed-enhancer")?.checked;\n    const failures = (data.packs || []).filter((pack) => !pack.installed);\n    if (failures.length) {\n''',
)
replace(
    "static/setup.js",
    '''      setTimeout(() => window.location.replace(data.installedPackCount ? "/" : "/admin"), 2800);\n      return;\n    }\n\n    if (!packs.length) {\n''',
    '''      setTimeout(() => window.location.replace(managedEnhancerSelected ? "/admin" : (data.installedPackCount ? "/" : "/admin")), 2800);\n      return;\n    }\n\n    if (managedEnhancerSelected) {\n      setStatus($("setup-result"), "✓ Orange is ready. Gemma 4 is downloading in the background; opening Admin to show progress…", "ok");\n      setTimeout(() => window.location.replace("/admin"), 900);\n    } else if (!packs.length) {\n''',
)

# README: explain the built-in provider.
replace(
    "README.md",
    '''- **Prompt Enhancement** — optional OpenAI/OpenAI-compatible, Ollama, Gemini, or Anthropic LLM expansion with local prompt overrides.\n''',
    '''- **Prompt Enhancement** — optional Managed Local Gemma 4, OpenAI/OpenAI-compatible, Ollama, Gemini, or Anthropic LLM expansion with local prompt overrides.\n''',
)
replace(
    "README.md",
    '''Prompt enhancement is optional. In **General Settings**, enable it and choose a provider:\n\n- **OpenAI** — also supports compatible Base URLs such as LM Studio, llama.cpp, or OpenRouter.\n''',
    '''Prompt enhancement is optional. In **General Settings**, enable it and choose a provider:\n\n- **Managed Local** — installs Google's Gemma 4 E2B Instruct Q4_0 QAT plus a private pinned llama.cpp runtime. It requires no API key, binds only to localhost, runs CPU-first so ComfyUI keeps the GPU, and unloads the model after 5 idle minutes.\n- **OpenAI** — also supports compatible Base URLs such as LM Studio, llama.cpp, or OpenRouter.\n''',
)

print("managed Gemma patch applied")
