const $ = (id) => document.getElementById(id);

let setupStatus = null;
let backendOk = false;
let compatibilityByPack = new Map();

function setStatus(el, message, kind = "") {
  el.textContent = message || "";
  el.className = `status ${kind}`.trim();
}

function sourceLabel(url) {
  if (!url) return "";
  try {
    const parsed = new URL(url);
    const pieces = parsed.pathname.split("/").filter(Boolean);
    if (parsed.hostname === "huggingface.co" && pieces.length >= 2) {
      return `${pieces[0]}/${pieces[1]}`;
    }
    return parsed.hostname;
  } catch (_) {
    return url;
  }
}

function filePlanHtml(files, heading) {
  if (!files?.length) return "";
  return `
    <div class="file-plan">
      <div class="file-plan-heading">${heading}</div>
      ${files.map((file) => `
        <div class="file-row">
          <code>${file.filename || "unknown"}</code>
          <span>${file.folder || "model"}${file.precision ? ` · ${String(file.precision).toUpperCase()}` : ""}${file.url ? ` · ${sourceLabel(file.url)}` : ""}</span>
        </div>
      `).join("")}
    </div>
  `;
}

function packStatusHtml(packId) {
  const inspection = compatibilityByPack.get(packId);
  if (!inspection) {
    return '<div class="pack-status neutral">Test & scan ComfyUI to check whether this tool is already runnable.</div>';
  }
  if (inspection.ready) {
    return `
      <div class="pack-status ready">✓ Ready — compatible models already found. No download required.</div>
      ${filePlanHtml(inspection.selectedModels, "Will use")}
    `;
  }
  if (inspection.missingNodes?.length) {
    return `<div class="pack-status error">Missing ComfyUI nodes: ${inspection.missingNodes.join(", ")}</div>`;
  }
  if (inspection.unknownModels?.length) {
    return `<div class="pack-status warning">Orange could not verify the model inventory for this workflow on this ComfyUI build.</div>`;
  }
  const count = inspection.downloadPlan?.length || inspection.missingModels?.length || 0;
  return `
    <div class="pack-status warning">Needs ${count} model download${count === 1 ? "" : "s"}.</div>
    ${filePlanHtml(inspection.downloadPlan, "Orange will download")}
  `;
}

function renderPacks() {
  const container = $("optional-packs");
  if (!container) return;
  const checked = new Set(
    Array.from(document.querySelectorAll("[data-pack-id]:checked")).map((input) => input.dataset.packId),
  );
  const packs = setupStatus?.packs || [];
  if (!packs.length) {
    container.innerHTML = '<p class="hint">No curated packs are available.</p>';
    return;
  }

  container.innerHTML = packs.map((pack) => `
    <label class="pack optional-pack">
      <input type="checkbox" data-pack-id="${pack.id}" ${checked.has(pack.id) ? "checked" : ""}>
      <div class="pack-body">
        <div class="pack-title">${pack.name}${pack.recommended ? " <span>Recommended</span>" : ""}</div>
        <p>${pack.description || ""}</p>
        ${packStatusHtml(pack.id)}
      </div>
    </label>
  `).join("");
}

async function loadStatus() {
  const response = await fetch("/api/setup/status");
  setupStatus = await response.json();
  if (!setupStatus.required) {
    window.location.replace("/");
    return;
  }

  $("comfy-url").value = setupStatus.defaultComfyUrl || "http://127.0.0.1:8188";
  if (setupStatus.detectedModelsRoot) {
    $("models-root").value = setupStatus.detectedModelsRoot;
  }

  const modeCopy = $("mode-copy");
  if (setupStatus.installMode === "pinokio" && setupStatus.managedComfyAvailable) {
    modeCopy.innerHTML = "<strong>Managed setup detected.</strong> Pinokio installed ComfyUI with Orange. Pick any curated tools you want, or install none and configure Orange yourself.";
  } else if (setupStatus.installMode === "pinokio") {
    modeCopy.innerHTML = "<strong>Orange-only Pinokio install.</strong> Connect your existing ComfyUI. Orange will scan its nodes and model dropdowns before offering downloads.";
  } else {
    modeCopy.innerHTML = "<strong>Existing ComfyUI.</strong> Enter a local or remote ComfyUI URL. Orange can reuse compatible model variants that are already installed; Pinokio is not required.";
  }

  renderPacks();

  const enhancer = setupStatus.managedPromptEnhancer || {};
  const enhancerCheckbox = $("managed-enhancer");
  const enhancerStatus = $("managed-enhancer-status");
  if (enhancerCheckbox && enhancerStatus) {
    enhancerCheckbox.disabled = enhancer.supported === false;
    enhancerCheckbox.checked = !!enhancer.installed;
    if (enhancer.installed) {
      enhancerStatus.textContent = "✓ Gemma 4 is already installed and ready.";
      enhancerStatus.className = "pack-status ready";
    } else if (enhancer.supported === false) {
      enhancerStatus.textContent = `Managed Local is not packaged for ${enhancer.platform || "this platform"}. Configure Ollama or an API later.`;
      enhancerStatus.className = "pack-status warning";
    }
  }
}

function hardwareLabel(hardware) {
  if (!hardware) return "";
  const parts = [];
  if (hardware.deviceName) parts.push(hardware.deviceName);
  if (hardware.vramGb) parts.push(`${hardware.vramGb} GB VRAM`);
  if (hardware.int8ConvRot) parts.push("INT8 ConvRot ready");
  return parts.length ? ` · ${parts.join(" · ")}` : "";
}

async function testBackend() {
  const button = $("test-backend");
  button.disabled = true;
  setStatus($("backend-result"), "Checking ComfyUI nodes and model inventory…");
  try {
    const response = await fetch("/api/setup/test-backend", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        url: $("comfy-url").value.trim(),
        modelsRoot: $("models-root").value.trim(),
      }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Connection failed");
    backendOk = true;
    compatibilityByPack = new Map((data.packCompatibility || []).map((pack) => [pack.pack, pack]));
    if (data.modelsRoot && !$("models-root").value.trim()) $("models-root").value = data.modelsRoot;
    renderPacks();
    const readyCount = (data.packCompatibility || []).filter((pack) => pack.ready).length;
    setStatus(
      $("backend-result"),
      `✓ ComfyUI found · ${data.nodeCount} node types · ${readyCount}/${(data.packCompatibility || []).length} curated tools already have compatible models${hardwareLabel(data.hardware)}`,
      "ok",
    );
  } catch (error) {
    backendOk = false;
    compatibilityByPack = new Map();
    renderPacks();
    setStatus($("backend-result"), error.message, "error");
  } finally {
    button.disabled = false;
  }
}

function selectedPacks() {
  return Array.from(document.querySelectorAll("[data-pack-id]:checked")).map((input) => input.dataset.packId);
}

function selectedNeedsDownloads(packIds) {
  return packIds.some((packId) => {
    const inspection = compatibilityByPack.get(packId);
    return inspection && !inspection.ready && (inspection.downloadPlan?.length || inspection.missingModels?.length);
  });
}

async function finishSetup() {
  const button = $("finish-setup");
  const adminKey = $("admin-key").value;
  if (adminKey.length < 8) {
    setStatus($("setup-result"), "Create an Admin password with at least 8 characters.", "error");
    return;
  }
  if (!backendOk) {
    await testBackend();
    if (!backendOk) {
      setStatus($("setup-result"), "Connect to ComfyUI successfully before finishing setup.", "error");
      return;
    }
  }

  const packs = selectedPacks();
  button.disabled = true;
  if (!packs.length) {
    setStatus($("setup-result"), "Saving Orange with no curated tools selected…");
  } else if (selectedNeedsDownloads(packs)) {
    setStatus($("setup-result"), "Installing only the missing model files, binding the workflows, and running Preflight…");
  } else {
    setStatus($("setup-result"), "Adding the selected workflows using models already on this ComfyUI…");
  }

  try {
    const response = await fetch("/api/setup/complete", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        comfyUrl: $("comfy-url").value.trim(),
        modelsRoot: $("models-root").value.trim(),
        adminKey,
        selectedPacks: packs,
        managedPromptEnhancer: !!$("managed-enhancer")?.checked,
      }),
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(typeof data.detail === "string" ? data.detail : (data.detail?.message || "Setup failed"));
    }

    localStorage.setItem("orange_admin_key", adminKey);
    const managedEnhancerSelected = !!$("managed-enhancer")?.checked;
    const failures = (data.packs || []).filter((pack) => !pack.installed);
    if (failures.length) {
      setStatus(
        $("setup-result"),
        `✓ Orange setup is complete. ${failures.map((pack) => `${pack.name || pack.pack}: ${pack.error || "not added"}`).join(" · ")}`,
        "ok",
      );
      setTimeout(() => window.location.replace(managedEnhancerSelected ? "/admin" : (data.installedPackCount ? "/" : "/admin")), 2800);
      return;
    }

    if (managedEnhancerSelected) {
      setStatus($("setup-result"), "✓ Orange is ready. Gemma 4 is downloading in the background; opening Admin to show progress…", "ok");
      setTimeout(() => window.location.replace("/admin"), 900);
    } else if (!packs.length) {
      setStatus($("setup-result"), "✓ Orange is ready with no curated tools installed. Opening Admin…", "ok");
      setTimeout(() => window.location.replace("/admin"), 900);
    } else {
      setStatus(
        $("setup-result"),
        `✓ Orange is ready with ${data.installedPackCount} curated tool${data.installedPackCount === 1 ? "" : "s"}. Opening Generate…`,
        "ok",
      );
      setTimeout(() => window.location.replace("/"), 900);
    }
  } catch (error) {
    setStatus($("setup-result"), error.message, "error");
    button.disabled = false;
  }
}

$("test-backend").addEventListener("click", testBackend);
$("finish-setup").addEventListener("click", finishSetup);
$("comfy-url").addEventListener("input", () => {
  backendOk = false;
  compatibilityByPack = new Map();
  renderPacks();
  setStatus($("backend-result"), "");
});
$("models-root").addEventListener("change", () => {
  backendOk = false;
  setStatus($("backend-result"), "Models path changed — scan again to refresh the download plan.");
});

loadStatus().catch((error) => setStatus($("setup-result"), `Could not load setup: ${error.message}`, "error"));
