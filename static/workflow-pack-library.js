(() => {
  let catalog = null;
  let inspectionByPack = new Map();
  let jobByKey = new Map();
  let pollTimer = null;

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

  function formatBytes(value) {
    const bytes = Number(value);
    if (!Number.isFinite(bytes) || bytes < 0) return '';
    if (bytes < 1024) return `${bytes} B`;
    const units = ['KB', 'MB', 'GB', 'TB'];
    let size = bytes / 1024;
    let index = 0;
    while (size >= 1024 && index < units.length - 1) {
      size /= 1024;
      index += 1;
    }
    return `${size >= 100 ? size.toFixed(0) : size >= 10 ? size.toFixed(1) : size.toFixed(2)} ${units[index]}`;
  }

  function formatSpeed(value) {
    const formatted = formatBytes(value);
    return formatted ? `${formatted}/s` : '';
  }

  function filePlanHtml(files, heading = 'Downloads', dynamic = false) {
    if (!files?.length) return '';
    return `
      <div class="mt-2 border border-zinc-800 rounded-xl overflow-hidden bg-zinc-950">
        <div class="px-3 py-2 border-b border-zinc-800 text-[10px] font-bold uppercase tracking-wider text-zinc-500">${heading}</div>
        ${files.map((file) => {
          const downloaded = Number(file.bytesDownloaded || 0);
          const total = Number(file.bytesTotal || 0);
          const pct = total > 0 ? Math.max(0, Math.min(100, (downloaded / total) * 100)) : null;
          const state = file.state || 'pending';
          const detail = dynamic
            ? [
                total > 0 ? `${formatBytes(downloaded)} / ${formatBytes(total)}` : (downloaded > 0 ? formatBytes(downloaded) : ''),
                state === 'downloading' ? formatSpeed(file.speedBps) : '',
                state === 'existing' ? 'Already present' : '',
                state === 'completed' ? 'Complete' : '',
                state === 'failed' ? 'Failed' : '',
              ].filter(Boolean).join(' · ')
            : '';
          return `
            <div class="px-3 py-2 border-b last:border-b-0 border-zinc-900 flex flex-col gap-1.5">
              <div class="flex items-center justify-between gap-3">
                <code class="text-[11px] text-orange-300 break-all">${file.filename || 'unknown'}</code>
                ${dynamic && state === 'downloading' ? '<i data-lucide="loader-2" class="w-3 h-3 text-orange-400 animate-spin shrink-0"></i>' : ''}
              </div>
              <span class="text-[10px] text-zinc-500 break-all">${file.folder || 'model'}${file.precision ? ` · ${String(file.precision).toUpperCase()}` : ''}${file.url ? ` · ${sourceLabel(file.url)}` : ''}</span>
              ${file.destination ? `<span class="text-[10px] text-zinc-600 break-all">→ ${file.destination}</span>` : ''}
              ${dynamic && detail ? `<span class="text-[10px] ${state === 'failed' ? 'text-red-400' : 'text-zinc-400'}">${detail}</span>` : ''}
              ${dynamic && pct !== null ? `
                <div class="h-1.5 bg-zinc-800 rounded-full overflow-hidden">
                  <div class="h-full bg-orange-500 transition-all duration-300" style="width:${pct.toFixed(1)}%"></div>
                </div>
              ` : ''}
              ${file.error ? `<span class="text-[10px] text-red-400 break-words">${file.error}</span>` : ''}
            </div>
          `;
        }).join('')}
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
      await refreshJobs();
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

  function jobStageLabel(job) {
    const labels = {
      queued: 'Queued…',
      inspecting: 'Scanning ComfyUI…',
      downloading: 'Downloading models…',
      materializing: 'Binding workflow…',
      preflight: 'Running Preflight…',
      completed: 'Ready',
      interrupted: 'Interrupted',
    };
    return labels[job?.stage] || job?.message || 'Working…';
  }

  function inspectionStatus(pack, inspection, job) {
    if (job?.state === 'queued' || job?.state === 'running') {
      return `
        <div class="bg-orange-950/30 border border-orange-900/60 rounded-xl p-3 text-xs text-orange-200">
          <div class="font-semibold flex items-center gap-2"><i data-lucide="loader-2" class="w-3.5 h-3.5 animate-spin"></i> ${jobStageLabel(job)}</div>
          ${job.message && job.message !== jobStageLabel(job) ? `<div class="text-[10px] text-orange-300/70 mt-1">${job.message}</div>` : ''}
          ${filePlanHtml(job.files?.length ? job.files : job.downloadPlan, job.mode === 'existing' ? 'Using existing models' : 'Install progress', true)}
        </div>
      `;
    }
    if (job?.state === 'failed' || job?.state === 'interrupted') {
      return `
        <div class="bg-red-950/30 border border-red-900/60 rounded-xl p-3 text-xs text-red-300">
          <div class="font-semibold">${job.state === 'interrupted' ? 'Install interrupted' : 'Install failed'}</div>
          <div class="mt-1">${job.error || 'The workflow install did not complete.'}</div>
          ${filePlanHtml(job.files, 'Last recorded progress', true)}
        </div>
      `;
    }
    if (job?.state === 'completed') {
      return `
        <div class="bg-emerald-950/30 border border-emerald-900/60 rounded-xl p-3 text-xs text-emerald-300">✓ ${job.message || 'Workflow installed successfully.'}</div>
        ${filePlanHtml(job.files, job.mode === 'existing' ? 'Existing models used' : 'Completed install', true)}
      `;
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
      const job = jobByKey.get(installKey(serverUrl, pack.id));
      const busy = job?.state === 'queued' || job?.state === 'running';
      const retryable = job?.state === 'failed' || job?.state === 'interrupted';
      let label = pack.installed ? 'Repair / Recheck' : 'Install missing models';
      if (inspection?.ready) label = pack.installed ? 'Recheck' : 'Add to Orange';
      if (busy) label = jobStageLabel(job);
      if (retryable) label = 'Retry';
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
          ${inspectionStatus(pack, inspection, job)}
          <button data-pack-id="${pack.id}" ${disabled ? 'disabled' : ''} class="self-start ${buttonClass} px-3 py-2 rounded-lg text-xs font-semibold transition disabled:opacity-40 disabled:cursor-not-allowed">${label}</button>
        </div>
      `;
    }).join('');

    list.querySelectorAll('[data-pack-id]').forEach((button) => {
      button.addEventListener('click', () => runPackAction(button.dataset.packId));
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

  function setLatestJobs(jobs) {
    const next = new Map();
    (jobs || []).forEach((job) => {
      const key = installKey(job.serverUrl, job.packId);
      if (!next.has(key)) next.set(key, job);
    });
    jobByKey = next;
  }

  function scheduleJobPoll() {
    if (pollTimer) clearTimeout(pollTimer);
    pollTimer = null;
    const hasActive = Array.from(jobByKey.values()).some((job) => job.state === 'queued' || job.state === 'running');
    if (!hasActive) return;
    pollTimer = setTimeout(pollJobs, 1000);
  }

  async function refreshJobs() {
    const serverUrl = document.getElementById('curated-server')?.value;
    if (!serverUrl || !localStorage.getItem('orange_admin_key')) {
      jobByKey = new Map();
      renderCatalog();
      return [];
    }
    const response = await authFetch(`/api/admin/workflow-packs/install-jobs?serverUrl=${encodeURIComponent(serverUrl)}&limit=50`);
    if (!response.ok) throw new Error('Could not load workflow install activity.');
    const data = await response.json();
    setLatestJobs(data.jobs || []);
    renderCatalog();
    scheduleJobPoll();
    return data.jobs || [];
  }

  async function pollJobs() {
    pollTimer = null;
    const before = new Map(Array.from(jobByKey.values()).map((job) => [job.id, job.state]));
    try {
      const jobs = await refreshJobs();
      const finished = jobs.some((job) => {
        const previous = before.get(job.id);
        return (previous === 'queued' || previous === 'running') && !['queued', 'running'].includes(job.state);
      });
      if (finished) {
        await refreshCatalog({skipJobs: true});
      }
    } catch (_) {
      pollTimer = setTimeout(pollJobs, 2000);
    }
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

  async function refreshCatalog(options = {}) {
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
      if (!options.skipJobs) await refreshJobs();
      await inspectServer();
    } catch (error) {
      status.textContent = error.message;
    }
  }

  async function runPackAction(packId) {
    const serverUrl = document.getElementById('curated-server').value;
    const modelsRoot = document.getElementById('curated-models-root').value.trim();
    const status = document.getElementById('curated-tools-status');
    const inspection = inspectionByPack.get(packId);
    const key = installKey(serverUrl, packId);
    const existingJob = jobByKey.get(key);

    if (!serverUrl) {
      status.textContent = 'Configure a ComfyUI server first.';
      return;
    }
    if (!inspection?.ready && !modelsRoot) {
      status.textContent = 'This workflow is missing models. Enter a local/shared models path Orange can write to, or install the models on the ComfyUI server yourself and Refresh.';
      return;
    }

    status.textContent = existingJob?.state === 'failed' || existingJob?.state === 'interrupted'
      ? 'Retrying workflow install…'
      : 'Starting workflow install job…';

    try {
      const retry = existingJob?.state === 'failed' || existingJob?.state === 'interrupted';
      const url = retry
        ? `/api/admin/workflow-packs/install-jobs/${encodeURIComponent(existingJob.id)}/retry`
        : '/api/admin/workflow-packs/install-jobs';
      const options = {method: 'POST', headers: {'Content-Type': 'application/json'}};
      if (!retry) options.body = JSON.stringify({packId, serverUrl, modelsRoot});
      const response = await authFetch(url, options);
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : (data.detail?.message || 'Could not start workflow install.'));
      const job = data.job;
      jobByKey.set(installKey(job.serverUrl, job.packId), job);
      status.textContent = data.created ? 'Install is running in the background. You can leave this screen or refresh safely.' : 'This workflow already has an active install job.';
      renderCatalog();
      scheduleJobPoll();
    } catch (error) {
      status.textContent = error.message;
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