const $ = (id) => document.getElementById(id);

let setupStatus = null;
let backendOk = false;

function setStatus(el, message, kind = "") {
  el.textContent = message || "";
  el.className = `status ${kind}`.trim();
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
      `✓ ComfyUI found · ${data.nodeCount} node types · ${data.queueRunning} running / ${data.queuePending} queued`,
      "ok",
    );
  } catch (error) {
    backendOk = false;
    setStatus($("backend-result"), error.message, "error");
  } finally {
    button.disabled = false;
  }
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
  setStatus(
    $("setup-result"),
    installStarter ? "Setting up Orange and downloading the Z-Image starter files…" : "Saving your Orange setup…",
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
      }),
    });
    const data = await response.json();
    if (!response.ok) {
      const detail = typeof data.detail === "string" ? data.detail : (data.detail?.message || "Setup failed");
      throw new Error(detail);
    }
    setStatus($("setup-result"), "✓ Orange is ready. Opening your generator…", "ok");
    setTimeout(() => window.location.replace("/"), 500);
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
