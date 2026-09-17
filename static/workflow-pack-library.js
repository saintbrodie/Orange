(() => {
  let catalog = null;
  let inspectionByPack = new Map();
  const activeInstalls = new Map();

  function authFetch(url, options = {}) {
    const key = localStorage.getItem('orange_admin_key');
    options.headers = options.headers || {};
    options.headers.Authorization = `Bearer ${key || ''}`;
    return fetch(url, options);
  }

  function installKey(serverUrl, packId) {
    return `${serverUrl || ''}::${packId}`;
  }

  function sourceLabel(url) {
    if (!url) return '';
    try {
      const parsed = new URL(url);
      const pieces = parsed.pathname.split('/').filter(Boolean);
      if (parsed.hostname === 'huggingface.co' && pieces.length >= 2) return `${pieces[0]}/${pieces[1]}`;
      return parsed.hostname;
    } catch (_) {
      return url;
    }
  }

  function filePlanHtml(files, heading = 'Downloads') {
    if (!files?.length) return '';
    return `
      <div class="mt-2 border border-zinc-800 rounded-xl overflow-hidden bg-zinc-950">
        <div class="px-3 py-2 border-b border-zinc-800 text-[10px] font-bold uppercase tracking-wider text-zinc-500">${heading}</div>
        ${files.map((file) => `
          <div class="px-3 py-2 border-b last:border-b-0 border-zinc-900 flex flex-col gap-1">
            <code class="text-[11px] text-orange-300 break-all">${file.filename || 'unknown'}</code>
            <span class="text-[10px] text-zinc-500 break-all">${file.folder || 'model'}${file.precision ? ` · ${String(file.precision).toUpperCase()}` : ''}${file.url ? ` · ${sourceLabel(file.url)}` : ''}</span>
            ${file.destination ? `<span class="text-[10px] text-zinc-600 break-all">→ ${file.destination}</span>` : ''}
          </div>
        `).join('')}
      </div>
    `;
  }

  function injectResponsiveAdminStyles() {
    // Admin navigation breakpoints and the hamburger drawer are owned by
    // mobile-navigation.css/js. Keeping a second responsive nav here caused the
    // desktop tabs and hamburger to render at the same time on narrow screens.
  }

  function removeLegacyRestoreDefaults() {
    const restoreButton = document.getElementById('restore-defaults-btn');
    const section = restoreButton?.closest('.pt-4.border-t');
    if (section) section.remove();
  }

  function setToolsSubtab(view) {
    const editorView = document.getElementById('tools-editor-view');
    const curatedView = document.getElementById('tools-curated-view');
    const editorTab = document.getElementById('tools-subtab-editor');
    const curatedTab = document.getElementById('tools-subtab-curated');
    if (!editorView || !curatedView || !editorTab || !curatedTab) return;

    const editorActive = view !== 'curated';
    editorView.classList.toggle('hidden', !editorActive);
    curatedView.classList.toggle('hidden', editorActive);
    editorTab.className = editorActive
      ? 'bg-zinc-800 text-orange-400 border border-zinc-700 px-4 py-2 rounded-lg text-sm font-medium transition flex items-center gap-2'
      : 'text-zinc-400 hover:text-zinc-200 px-4 py-2 rounded-lg text-sm font-medium transition flex items-center gap-2';
    curatedTab.className = !editorActive
      ? 'bg-zinc-800 text-orange-400 border border-zinc-700 px-4 py-2 rounded-lg text-sm font-medium transition flex items-center gap-2'
      : 'text-zinc-400 hover:text-zinc-200 px-4 py-2 rounded-lg text-sm font-medium transition flex items-center gap-2';
    localStorage.setItem('orange_tools_subtab', editorActive ? 'editor' : 'curated');
    if (!editorActive) refreshCatalog();
    if (window.lucide) lucide.createIcons();
  }

  function setupToolsWorkspace() {
    injectResponsiveAdminStyles();
    removeLegacyRestoreDefaults();

    const toolsContainer = document.getElementById('tools-container');
    if (!toolsContainer || document.getElementById('tools-subnav')) return;

    const tabTools = document.getElementById('tab-tools');
    if (tabTools) tabTools.innerHTML = '<i data-lucide="wrench" class="w-4 h-4"></i> Tools';

    const existingChildren = Array.from(toolsContainer.children);
    toolsContainer.classList.remove('md:flex-row');
    toolsContainer.classList.add('flex-col');

    const subnav = document.createElement('div');
    subnav.id = 'tools-subnav';
    subnav.className = 'w-full flex items-center gap-2 bg-zinc-900/80 border border-zinc-800 rounded-2xl p-2 shadow-lg';
    subnav.innerHTML = `
      <button id="tools-subtab-editor" class="text-zinc-400 hover:text-zinc-200 px-4 py-2 rounded-lg text-sm font-medium transition flex items-center gap-2"><i data-lucide="sliders-horizontal" class="w-4 h-4"></i> Editor</button>
      <button id="tools-subtab-curated" class="text-zinc-400 hover:text-zinc-200 px-4 py-2 rounded-lg text-sm font-medium transition flex items-center gap-2"><i data-lucide="library" class="w-4 h-4"></i> Curated Library</button>
    `;

    const editorView = document.createElement('div');
    editorView.id = 'tools-editor-view';
    editorView.className = 'w-full flex flex-col md:flex-row gap-6';
    existingChildren.forEach((child) => editorView.appendChild(child));

    const curatedView = document.createElement('div');
    curatedView.id = 'tools-curated-view';
    curatedView.className = 'hidden w-full';
    curatedView.innerHTML = `
      <section id="curated-tools-section" class="bg-zinc-900/90 backdrop-blur-xl border border-zinc-800 rounded-3xl p-6 md:p-8 shadow-xl">
        <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-6">
          <div>
            <h2 class="text-xl font-semibold text-zinc-100 flex items-center gap-2"><i data-lucide="library" class="w-5 h-5 text-orange-500"></i> Curated Library</h2>
            <p class="text-sm text-zinc-500 mt-1">Scan a ComfyUI backend, reuse compatible models it already has, or download only the missing files.</p>
          </div>
          <button id="curated-refresh-btn" class="self-start bg-zinc-800 hover:bg-zinc-700 text-zinc-300 px-3 py-2 rounded-lg text-xs font-medium transition flex items-center gap-2 border border-zinc-700"><i data-lucide="refresh-cw" class="w-3.5 h-3.5"></i> Refresh</button>
        </div>
        <div class="grid grid-cols-1 md:grid-cols-2 gap-4 mb-5">
          <div>
            <label class="text-[10px] text-zinc-500 font-bold uppercase tracking-wider block mb-1">Target ComfyUI</label>
            <select id="curated-server" class="w-full bg-zinc-950 border border-zinc-800 rounded-xl p-3 text-xs text-zinc-300 outline-none focus:border-orange-500"></select>
          </div>
          <div>
            <label class="text-[10px] text-zinc-500 font-bold uppercase tracking-wider block mb-1">Models Path <span class="normal-case tracking-normal font-normal">(downloads only)</span></label>
            <input id="curated-models-root" class="w-full bg-zinc-950 border border-zinc-800 rounded-xl p-3 text-xs text-zinc-300 font-mono outline-none focus:border-orange-500" placeholder="Not required when compatible models already exist">
          </div>
        </div>
        <div id="curated-tools-status" class="text-xs text-zinc-500 mb-4"></div>
        <div id="curated-tools-list" class="grid grid-cols-1 lg:grid-cols-2 gap-4"></div>
      </section>
    `;

    toolsContainer.appendChild(subnav);
    toolsContainer.appendChild(editorView);
    toolsContainer.appendChild(curatedView);

    document.getElementById('tools-subtab-editor').addEventListener('click', () => setToolsSubtab('editor'));
    document.getElementById('tools-subtab-curated').addEventListener('click', () => setToolsSubtab('curated'));
    document.getElementById('curated-refresh-btn').addEventListener('click', refreshCatalog);
    document.getElementById('curated-server').addEventListener('change', async () => {
      syncModelsRoot();
      await inspectServer();
    });
    document.getElementById('curated-models-root').addEventListener('change', inspectServer);

    setToolsSubtab(localStorage.getItem('orange_tools_subtab') || 'editor');
    if (window.lucide) lucide.createIcons();
  }

  function syncModelsRoot() {
    if (!catalog) return;
    const serverSelect = document.getElementById('curated-server');
    const modelsRoot = document.getElementById('curated-models-root');
    if (!serverSelect || !modelsRoot) return;
    const server = (catalog.servers || []).find((item) => item.url === serverSelect.value);
    modelsRoot.value = server?.modelsRoot || catalog.detectedModelsRoot || '';
  }

  function inspectionStatus(pack, inspection, active) {
    if (active?.state === 'installing') {
      return `
        <div class="bg-orange-950/30 border border-orange-900/60 rounded-xl p-3 text-xs text-orange-200">
          <div class="font-semibold flex items-center gap-2"><i data-lucide="loader-2" class="w-3.5 h-3.5 animate-spin"></i> ${active.mode === 'existing' ? 'Adding workflow and running Preflight…' : 'Downloading models, binding workflow, and running Preflight…'}</div>
          ${filePlanHtml(active.files, active.mode === 'existing' ? 'Using existing models' : 'Downloading')}
        </div>
      `;
    }
    if (active?.state === 'error') {
      return `<div class="bg-red-950/30 border border-red-900/60 rounded-xl p-3 text-xs text-red-300">${active.error}</div>`;
    }
    if (!inspection) return '<div class="text-xs text-zinc-600">Scanning backend compatibility…</div>';
    if (inspection.ready) {
      return `
        <div class="bg-emerald-950/30 border border-emerald-900/60 rounded-xl p-3 text-xs text-emerald-300">✓ Compatible models already found — no download required.</div>
        ${filePlanHtml(inspection.selectedModels, 'Existing models Orange will use')}
      `;
    }
    if (inspection.missingNodes?.length) {
      return `<div class="bg-red-950/30 border border-red-900/60 rounded-xl p-3 text-xs text-red-300">Missing nodes: ${inspection.missingNodes.join(', ')}</div>`;
    }
    if (inspection.unknownModels?.length) {
      return '<div class="bg-amber-950/30 border border-amber-900/60 rounded-xl p-3 text-xs text-amber-300">ComfyUI did not expose enough model inventory to verify this pack safely.</div>';
    }
    return `
      <div class="bg-amber-950/30 border border-amber-900/60 rounded-xl p-3 text-xs text-amber-300">${inspection.downloadPlan?.length || 0} missing model file${inspection.downloadPlan?.length === 1 ? '' : 's'}.</div>
      ${filePlanHtml(inspection.downloadPlan, 'Orange will download')}
    `;
  }

  function renderCatalog() {
    const serverSelect = document.getElementById('curated-server');
    const list = document.getElementById('curated-tools-list');
    if (!serverSelect || !list || !catalog) return;

    const serverUrl = serverSelect.value;
    list.innerHTML = (catalog.packs || []).map((pack) => {
      const inspection = inspectionByPack.get(pack.id);
      const active = activeInstalls.get(installKey(serverUrl, pack.id));
      const busy = active?.state === 'installing';
      let label = pack.installed ? 'Repair / Recheck' : 'Install missing models';
      let action = 'install';
      if (inspection?.ready) {
        action = 'activate';
        label = pack.installed ? 'Recheck' : 'Add to Orange';
      }
      if (busy) label = active.mode === 'existing' ? 'Adding…' : 'Installing…';
      if (active?.state === 'error') label = 'Retry';
      const buttonClass = pack.installed || inspection?.ready
        ? 'bg-zinc-800 hover:bg-zinc-700 text-zinc-300 border border-zinc-700'
        : 'bg-orange-600 hover:bg-orange-500 text-white';
      const disabled = busy || inspection?.missingNodes?.length || inspection?.unknownModels?.length;
      return `
        <div class="bg-zinc-950/70 border ${pack.installed ? 'border-emerald-900/70' : 'border-zinc-800'} rounded-2xl p-5 flex flex-col gap-3">
          <div>
            <div class="flex items-center justify-between gap-2">
              <strong class="text-sm text-zinc-200">${pack.name}</strong>
              ${pack.installed ? '<span class="text-[10px] uppercase tracking-wider font-bold text-emerald-400">In Orange</span>' : ''}
            </div>
            <p class="text-xs text-zinc-500 mt-1 leading-relaxed">${pack.description || ''}</p>
          </div>
          ${inspectionStatus(pack, inspection, active)}
          <button data-pack-action="${action}" data-pack-id="${pack.id}" ${disabled ? 'disabled' : ''} class="self-start ${buttonClass} px-3 py-2 rounded-lg text-xs font-semibold transition disabled:opacity-40 disabled:cursor-not-allowed">${label}</button>
        </div>
      `;
    }).join('');

    list.querySelectorAll('[data-pack-action]').forEach((button) => {
      button.addEventListener('click', () => runPackAction(button.dataset.packId, button.dataset.packAction));
    });
    if (window.lucide) lucide.createIcons();
  }

  function renderServerOptions(previousUrl = '') {
    const serverSelect = document.getElementById('curated-server');
    if (!serverSelect || !catalog) return;
    serverSelect.innerHTML = '';
    (catalog.servers || []).forEach((server) => {
      const option = document.createElement('option');
      option.value = server.url;
      option.textContent = `Server ${server.priority || 1} · ${server.url}`;
      serverSelect.appendChild(option);
    });
    if (previousUrl && (catalog.servers || []).some((server) => server.url === previousUrl)) serverSelect.value = previousUrl;
    syncModelsRoot();
  }

  async function inspectServer() {
    const status = document.getElementById('curated-tools-status');
    const serverUrl = document.getElementById('curated-server')?.value;
    const modelsRoot = document.getElementById('curated-models-root')?.value.trim() || '';
    if (!serverUrl || !status) {
      inspectionByPack = new Map();
      renderCatalog();
      return;
    }
    status.textContent = 'Scanning ComfyUI nodes and model inventory…';
    try {
      const response = await authFetch('/api/admin/workflow-packs/inspect', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({serverUrl, modelsRoot}),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : (data.detail?.message || 'Could not inspect backend.'));
      inspectionByPack = new Map((data.packs || []).map((pack) => [pack.pack, pack]));
      const ready = (data.packs || []).filter((pack) => pack.ready).length;
      status.textContent = `${ready}/${(data.packs || []).length} curated tools already have compatible models on this backend. Downloads below include only missing dependencies.`;
      renderCatalog();
    } catch (error) {
      inspectionByPack = new Map();
      status.textContent = error.message;
      renderCatalog();
    }
  }

  async function refreshCatalog() {
    setupToolsWorkspace();
    const status = document.getElementById('curated-tools-status');
    const serverSelect = document.getElementById('curated-server');
    if (!status || !localStorage.getItem('orange_admin_key')) return;
    const previousUrl = serverSelect?.value || '';
    status.textContent = 'Loading curated tools…';
    try {
      const response = await authFetch('/api/admin/workflow-packs');
      if (!response.ok) throw new Error(response.status === 401 ? 'Admin login required.' : 'Could not load curated tools.');
      catalog = await response.json();
      renderServerOptions(previousUrl);
      renderCatalog();
      await inspectServer();
    } catch (error) {
      status.textContent = error.message;
    }
  }

  async function runPackAction(packId, requestedAction) {
    const serverUrl = document.getElementById('curated-server').value;
    const modelsRoot = document.getElementById('curated-models-root').value.trim();
    const status = document.getElementById('curated-tools-status');
    const inspection = inspectionByPack.get(packId);
    const action = inspection?.ready ? 'activate' : requestedAction;
    if (!serverUrl) {
      status.textContent = 'Configure a ComfyUI server first.';
      return;
    }
    if (action === 'install' && !modelsRoot) {
      status.textContent = 'This workflow is missing models. Enter a local/shared models path Orange can write to, or install the models on the ComfyUI server yourself and Refresh.';
      return;
    }

    const key = installKey(serverUrl, packId);
    const files = action === 'activate' ? (inspection?.selectedModels || []) : (inspection?.downloadPlan || []);
    activeInstalls.set(key, {state: 'installing', mode: action === 'activate' ? 'existing' : 'download', files});
    renderCatalog();
    status.textContent = action === 'activate'
      ? 'Binding existing model files into the curated workflow and running Preflight…'
      : 'Downloading the files shown on the workflow card, then running Preflight…';

    try {
      const response = await authFetch(`/api/admin/workflow-packs/${action}`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({packId, serverUrl, modelsRoot}),
      });
      const data = await response.json();
      if (!response.ok) {
        let message = typeof data.detail === 'string' ? data.detail : (data.detail?.message || 'Workflow setup failed.');
        const backend = data.detail?.preflight?.backends?.[0];
        const findings = backend ? [...(backend.errors || []), ...(backend.warnings || [])] : [];
        if (findings.length) message += ` ${findings.map((item) => item.message).join(' ')}`;
        throw new Error(message);
      }
      activeInstalls.delete(key);
      const selected = (data.selectedModels || []).map((model) => `${model.filename}${model.precision ? ` (${model.precision})` : ''}`).join(', ');
      status.textContent = `✓ ${data.tool?.name || packId} is ready${selected ? ` · ${selected}` : ''}`;
      await refreshCatalog();
    } catch (error) {
      activeInstalls.set(key, {state: 'error', mode: action === 'activate' ? 'existing' : 'download', files, error: error.message});
      status.textContent = error.message;
      renderCatalog();
    }
  }

  setupToolsWorkspace();

  const toolsTab = document.getElementById('tab-tools');
  if (toolsTab) {
    toolsTab.addEventListener('click', () => {
      if (localStorage.getItem('orange_tools_subtab') === 'curated') setTimeout(refreshCatalog, 0);
    });
  }

  document.addEventListener('visibilitychange', () => {
    const curatedView = document.getElementById('tools-curated-view');
    if (!document.hidden && curatedView && !curatedView.classList.contains('hidden')) refreshCatalog();
  });
})();
