(() => {
  let catalog = null;

  function authFetch(url, options = {}) {
    const key = localStorage.getItem('orange_admin_key');
    options.headers = options.headers || {};
    options.headers.Authorization = `Bearer ${key || ''}`;
    return fetch(url, options);
  }

  function injectResponsiveAdminStyles() {
    if (document.getElementById('orange-admin-responsive-styles')) return;
    const style = document.createElement('style');
    style.id = 'orange-admin-responsive-styles';
    style.textContent = `
      @media (max-width: 1180px) {
        body > nav {
          flex-wrap: wrap;
          gap: .75rem;
          padding: 1rem 1.25rem !important;
        }
        body > nav > div:first-child {
          width: 100%;
          min-width: 0;
          flex-wrap: wrap;
          padding-right: 7rem;
        }
        #admin-menu {
          width: 100%;
          flex-wrap: wrap;
          border-left: 0 !important;
          padding-left: 0 !important;
          margin-top: .35rem;
        }
        #logout-btn {
          position: absolute;
          top: 1.15rem;
          right: 1.25rem;
          margin-left: 0 !important;
          flex-shrink: 0;
        }
      }
      @media (max-width: 640px) {
        body {
          padding: .5rem !important;
        }
        body > nav {
          width: 100% !important;
          margin-top: .5rem !important;
          border-radius: 1rem !important;
        }
        body > nav > div:first-child {
          padding-right: 3.25rem;
        }
        body > nav h1 {
          font-size: 1.1rem !important;
          margin-right: 0 !important;
        }
        body > nav img {
          width: 2rem !important;
          height: 2rem !important;
        }
        #admin-menu {
          grid-template-columns: repeat(2, minmax(0, 1fr));
          gap: .4rem;
        }
        #admin-menu:not(.hidden) {
          display: grid !important;
        }
        #admin-menu .admin-tab {
          justify-content: center;
          padding: .55rem .6rem !important;
          font-size: .75rem !important;
        }
        #logout-btn {
          top: .9rem;
          right: .9rem;
          padding: .6rem !important;
          font-size: 0 !important;
        }
        #logout-btn svg {
          width: 1rem !important;
          height: 1rem !important;
        }
      }
    `;
    document.head.appendChild(style);
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
    if (tabTools) {
      tabTools.innerHTML = '<i data-lucide="wrench" class="w-4 h-4"></i> Tools';
    }

    const existingChildren = Array.from(toolsContainer.children);
    toolsContainer.classList.remove('md:flex-row');
    toolsContainer.classList.add('flex-col');

    const subnav = document.createElement('div');
    subnav.id = 'tools-subnav';
    subnav.className = 'w-full flex items-center gap-2 bg-zinc-900/80 border border-zinc-800 rounded-2xl p-2 shadow-lg';
    subnav.innerHTML = `
      <button id="tools-subtab-editor" class="text-zinc-400 hover:text-zinc-200 px-4 py-2 rounded-lg text-sm font-medium transition flex items-center gap-2">
        <i data-lucide="sliders-horizontal" class="w-4 h-4"></i> Editor
      </button>
      <button id="tools-subtab-curated" class="text-zinc-400 hover:text-zinc-200 px-4 py-2 rounded-lg text-sm font-medium transition flex items-center gap-2">
        <i data-lucide="library" class="w-4 h-4"></i> Curated Library
      </button>
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
            <h2 class="text-xl font-semibold text-zinc-100 flex items-center gap-2">
              <i data-lucide="library" class="w-5 h-5 text-orange-500"></i> Curated Library
            </h2>
            <p class="text-sm text-zinc-500 mt-1">Install Orange-tested tools and the model files they need.</p>
          </div>
          <button id="curated-refresh-btn" class="self-start bg-zinc-800 hover:bg-zinc-700 text-zinc-300 px-3 py-2 rounded-lg text-xs font-medium transition flex items-center gap-2 border border-zinc-700">
            <i data-lucide="refresh-cw" class="w-3.5 h-3.5"></i> Refresh
          </button>
        </div>
        <div class="grid grid-cols-1 md:grid-cols-2 gap-4 mb-5">
          <div>
            <label class="text-[10px] text-zinc-500 font-bold uppercase tracking-wider block mb-1">Target ComfyUI</label>
            <select id="curated-server" class="w-full bg-zinc-950 border border-zinc-800 rounded-xl p-3 text-xs text-zinc-300 outline-none focus:border-orange-500"></select>
          </div>
          <div>
            <label class="text-[10px] text-zinc-500 font-bold uppercase tracking-wider block mb-1">Models Path</label>
            <input id="curated-models-root" class="w-full bg-zinc-950 border border-zinc-800 rounded-xl p-3 text-xs text-zinc-300 font-mono outline-none focus:border-orange-500" placeholder="Local or shared ComfyUI models folder">
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
    document.getElementById('curated-server').addEventListener('change', syncModelsRoot);

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
      <div class="bg-zinc-950/70 border ${pack.installed ? 'border-emerald-900/70' : 'border-zinc-800'} rounded-2xl p-5 flex flex-col gap-3">
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
    setupToolsWorkspace();
    const status = document.getElementById('curated-tools-status');
    if (!status || !localStorage.getItem('orange_admin_key')) return;
    status.textContent = 'Loading curated tools…';
    try {
      const response = await authFetch('/api/admin/workflow-packs');
      if (!response.ok) throw new Error(response.status === 401 ? 'Admin login required.' : 'Could not load curated tools.');
      catalog = await response.json();
      renderCatalog();
      status.textContent = 'Orange selects the best supported model precision from this backend’s GPU and ComfyUI information.';
    } catch (error) {
      status.textContent = error.message;
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

  setupToolsWorkspace();

  const toolsTab = document.getElementById('tab-tools');
  if (toolsTab) {
    toolsTab.addEventListener('click', () => {
      if (localStorage.getItem('orange_tools_subtab') === 'curated') {
        setTimeout(refreshCatalog, 0);
      }
    });
  }

  document.addEventListener('visibilitychange', () => {
    const curatedView = document.getElementById('tools-curated-view');
    if (!document.hidden && curatedView && !curatedView.classList.contains('hidden')) refreshCatalog();
  });
})();
