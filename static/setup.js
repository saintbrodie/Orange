const $ = (id) => document.getElementById(id);

let setupStatus = null;
let backendOk = false;

function setStatus(el, message, kind = "") {
  el.textContent = message || "";
  el.className = `status ${kind}`.trim();
}

function renderOptionalPacks() {
  const container = $("optional-packs");
  if (!container) return;
  const packs = (setupStatus?.packs || []).filter((pack) => !pack.recommended && pack.id !== "z-image-turbo");
  if (!packs.length) {
    container.innerHTML = '<p class="hint">No additional curated packs are available yet.</p>';
    return;
  }

  container.innerHTML = packs.map((pack) => `
    <label class="pack optional-pack">
      <input type="checkbox" data-pack-id="${pack.id}">
      <div>
        <div class="pack-title">${pack.name}</div>
        <p>${pack.description || ""}</p>
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
    modeCopy.innerHTML = "<strong>Managed setup detected.</strong> Pinokio installed ComfyUI with Orange, so the local backend and model folder should already be filled in.";
  } else if (setupStatus.installMode === "pinokio") {
    modeCopy.innerHTML = "<strong>Orange-only Pinokio install.</strong> Connect an existing ComfyUI instance. Pinokio is optional; Orange works normally with any reachable ComfyUI backend.";
  } else {
    modeCopy.innerHTML = "<strong>Existing ComfyUI.</strong> Enter a local or remote ComfyUI URL. Orange does not require Pinokio when installed from GitHub or manually.";
  }

  renderOptionalPacks();
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
  setStatus($("backend-result"), "Checking ComfyUI…");
  try {
    const response = await fetch("/api/setup/test-backend", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({url: $("comfy-url").value.trim()}),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Connection failed");
    backendOk = true;
    setStatus(
      $("backend-result"),
      `✓ ComfyUI found · ${data.nodeCount} node types · ${data.queueRunning} running / ${data.queuePending} queued${hardwareLabel(data.hardware)}`,
      "ok",
    );
  } catch (error) {
    backendOk = false;
    setStatus($("backend-result"), error.message, "error");
  } finally {
    button.disabled = false;
  }
}

function selectedExtraPacks() {
  return Array.from(document.querySelectorAll("[data-pack-id]:checked")).map((input) => input.dataset.packId);
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

  button.disabled = true;
  const installStarter = $("install-starter").checked;
  const extras = selectedExtraPacks();
  const installing = installStarter || extras.length;
  setStatus(
    $("setup-result"),
    installing ? "Downloading the selected model files and checking the workflows…" : "Saving your Orange setup…",
  );

  try {
    const response = await fetch("/api/setup/complete", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        comfyUrl: $("comfy-url").value.trim(),
        modelsRoot: $("models-root").value.trim(),
        adminKey,
        installStarter,
        extraPacks: extras,
      }),
    });
    const data = await response.json();
    if (!response.ok) {
      let detail = typeof data.detail === "string" ? data.detail : (data.detail?.message || "Setup failed");
      const preflight = data.detail?.preflight;
      if (preflight?.backends?.[0]) {
        const backend = preflight.backends[0];
        const findings = [...(backend.errors || []), ...(backend.warnings || [])];
        if (findings.length) detail += ` ${findings.map((item) => item.message).join(" ")}`;
      }
      throw new Error(detail);
    }

    const optionalFailures = (data.optionalPacks || []).filter((pack) => !pack.installed);
    if (optionalFailures.length) {
      setStatus(
        $("setup-result"),
        `✓ Orange is ready. ${optionalFailures.map((pack) => `${pack.pack}: ${pack.error || "not installed"}`).join(" · ")} Opening your generator…`,
        "ok",
      );
      setTimeout(() => window.location.replace("/"), 2800);
    } else {
      const extraCount = (data.optionalPacks || []).filter((pack) => pack.installed).length;
      setStatus(
        $("setup-result"),
        extraCount ? `✓ Orange is ready with ${extraCount + 1} curated tools. Opening your generator…` : "✓ Orange is ready. Opening your generator…",
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
  setStatus($("backend-result"), "");
});

loadStatus().catch((error) => setStatus($("setup-result"), `Could not load setup: ${error.message}`, "error"));
