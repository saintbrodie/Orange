(() => {
  let catalog = null;

  function authFetch(url, options = {}) {
    const key = localStorage.getItem('orange_admin_key');
    options.headers = options.headers || {};
    options.headers.Authorization = `Bearer ${key || ''}`;
    return fetch(url, options);
  }

  function injectSection() {
    if (document.getElementById('curated-tools-section')) return;
    const restoreButton = document.getElementById('restore-defaults-btn');
    const workflowSection = restoreButton?.closest('.pt-4.border-t');
    if (!workflowSection) return;

    const section = document.createElement('div');
    section.id = 'curated-tools-section';
    section.className = 'pt-4 border-t border-zinc-800/50';
    section.innerHTML = `
      <div class="flex justify-between items-center gap-3 mb-3">
        <div>
          <h3 class="text-sm font-semibold text-zinc-300">Curated Tools</h3>
          <p class="text-xs text-zinc-500 mt-1">Install Orange-tested workflows and their required model files.</p>
        </div>
        <button id="curated-refresh-btn" class="bg-zinc-800 hover:bg-zinc-700 text-zinc-300 px-3 py-2 rounded-lg text-xs font-medium transition flex items-center gap-2 border border-zinc-700">
          <i data-lucide="refresh-cw" class="w-3.5 h-3.5"></i> Refresh
        </button>
      </div>
      <div class="grid grid-cols-1 md:grid-cols-2 gap-3 mb-4">
        <div>
          <label class="text-[10px] text-zinc-500 font-bold uppercase tracking-wider block mb-1">Target ComfyUI</label>
          <select id="curated-server" class="w-full bg-zinc-950 border border-zinc-800 rounded-lg p-2.5 text-xs text-zinc-300 outline-none focus:border-orange-500"></select>
        </div>
        <div>
          <label class="text-[10px] text-zinc-500 font-bold uppercase tracking-wider block mb-1">Models Path</label>
          <input id="curated-models-root" class="w-full bg-zinc-950 border border-zinc-800 rounded-lg p-2.5 text-xs text-zinc-300 font-mono outline-none focus:border-orange-500" placeholder="Local or shared ComfyUI models folder">
        </div>
      </div>
      <div id="curated-tools-status" class="text-xs text-zinc-500 mb-3"></div>
      <div id="curated-tools-list" class="grid grid-cols-1 md:grid-cols-2 gap-3"></div>
    `;
    workflowSection.insertAdjacentElement('afterend', section);

    document.getElementById('curated-refresh-btn').addEventListener('click', refreshCatalog);
    document.getElementById('curated-server').addEventListener('change', syncModelsRoot);
    if (window.lucide) lucide.createIcons();
  }

  function syncModelsRoot() {
    if (!catalog) return;
    const serverUrl = document.getElementById('curated-server').value;
    const server = (catalog.servers || []).find((item) => item.url === serverUrl);
    document.getElementById('curated-models-root').value = server?.modelsRoot || catalog.detectedModelsRoot || '';
  }

  function renderCatalog() {
    const serverSelect = document.getElementById('curated-server');
    const list = document.getElementById('curated-tools-list');
    if (!serverSelect || !list || !catalog) return;

    const oldServer = serverSelect.value;
    serverSelect.innerHTML = '';
    (catalog.servers || []).forEach((server) => {
      const option = document.createElement('option');
      option.value = server.url;
      option.textContent = `Server ${server.priority || 1} · ${server.url}`;
      serverSelect.appendChild(option);
    });
    if (oldServer && (catalog.servers || []).some((server) => server.url === oldServer)) {
      serverSelect.value = oldServer;
    }
    syncModelsRoot();

    list.innerHTML = (catalog.packs || []).map((pack) => `
      <div class="bg-zinc-950/70 border ${pack.installed ? 'border-emerald-900/70' : 'border-zinc-800'} rounded-xl p-4 flex flex-col gap-3">
        <div>
          <div class="flex items-center justify-between gap-2">
            <strong class="text-sm text-zinc-200">${pack.name}</strong>
            ${pack.installed ? '<span class="text-[10px] uppercase tracking-wider font-bold text-emerald-400">Installed</span>' : ''}
          </div>
          <p class="text-xs text-zinc-500 mt-1 leading-relaxed">${pack.description || ''}</p>
        </div>
        <button data-install-pack="${pack.id}" class="self-start ${pack.installed ? 'bg-zinc-800 hover:bg-zinc-700 text-zinc-300' : 'bg-orange-600 hover:bg-orange-500 text-white'} px-3 py-2 rounded-lg text-xs font-semibold transition">
          ${pack.installed ? 'Repair / Recheck' : 'Install'}
        </button>
      </div>
    `).join('');

    list.querySelectorAll('[data-install-pack]').forEach((button) => {
      button.addEventListener('click', () => installPack(button.dataset.installPack, button));
    });
    if (window.lucide) lucide.createIcons();
  }

  async function refreshCatalog() {
    injectSection();
    const status = document.getElementById('curated-tools-status');
    if (!localStorage.getItem('orange_admin_key')) return;
    if (status) status.textContent = 'Loading curated tools…';
    try {
      const response = await authFetch('/api/admin/workflow-packs');
      if (!response.ok) throw new Error(response.status === 401 ? 'Admin login required.' : 'Could not load curated tools.');
      catalog = await response.json();
      renderCatalog();
      if (status) status.textContent = 'Orange selects the best supported model precision from this backend’s GPU/ComfyUI information.';
    } catch (error) {
      if (status) status.textContent = error.message;
    }
  }

  async function installPack(packId, button) {
    const serverUrl = document.getElementById('curated-server').value;
    const modelsRoot = document.getElementById('curated-models-root').value.trim();
    const status = document.getElementById('curated-tools-status');
    if (!serverUrl) {
      status.textContent = 'Configure a ComfyUI server first.';
      return;
    }
    if (!modelsRoot) {
      status.textContent = 'Enter a local/shared models path Orange can write to for this backend.';
      return;
    }

    const original = button.textContent;
    button.disabled = true;
    button.textContent = 'Installing…';
    status.textContent = 'Downloading missing files, binding the workflow, and running Preflight…';
    try {
      const response = await authFetch('/api/admin/workflow-packs/install', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({packId, serverUrl, modelsRoot}),
      });
      const data = await response.json();
      if (!response.ok) {
        let message = typeof data.detail === 'string' ? data.detail : (data.detail?.message || 'Install failed.');
        const backend = data.detail?.preflight?.backends?.[0];
        const findings = backend ? [...(backend.errors || []), ...(backend.warnings || [])] : [];
        if (findings.length) message += ` ${findings.map((item) => item.message).join(' ')}`;
        throw new Error(message);
      }
      const selected = (data.selectedModels || []).map((model) => `${model.filename}${model.precision ? ` (${model.precision})` : ''}`).join(', ');
      status.textContent = `✓ ${data.tool?.name || packId} is ready${selected ? ` · ${selected}` : ''}`;
      await refreshCatalog();
    } catch (error) {
      status.textContent = error.message;
    } finally {
      button.disabled = false;
      button.textContent = original;
    }
  }

  injectSection();
  const generalTab = document.getElementById('tab-general');
  if (generalTab) generalTab.addEventListener('click', () => setTimeout(refreshCatalog, 0));
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden && !document.getElementById('settings-container')?.classList.contains('hidden')) refreshCatalog();
  });
})();
