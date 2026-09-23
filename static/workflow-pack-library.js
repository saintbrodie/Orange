(() => {
  let catalog = null;
  let inspectionByPack = new Map();
  let inspectionHardware = null;
  let jobByKey = new Map();
  let pollTimer = null;

  function authFetch(url, options = {}) {
    const key = localStorage.getItem('orange_admin_key');
    options.headers = options.headers || {};
    options.headers.Authorization = `Bearer ${key || ''}`;
    return fetch(url, options);
  }

  function escapeHtml(value) {
    return String(value ?? '')
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#039;');
  }

  function installKey(serverUrl, packId) {
    return `${serverUrl || ''}::${packId}`;
  }

  function modelsRootStorageKey(serverUrl) {
    return `orange_curated_models_root::${serverUrl || 'default'}`;
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

  function hardwareLabel(hardware) {
    if (!hardware) return '';
    return [
      hardware.deviceName,
      hardware.vramGb ? `${hardware.vramGb} GB VRAM` : '',
      hardware.comfyuiVersion ? `ComfyUI ${hardware.comfyuiVersion}` : '',
    ].filter(Boolean).join(' · ');
  }

  function typePresentation(pack) {
    const id = String(pack?.id || '');
    if (id.includes('upscale')) return {label: 'Upscale', icon: 'maximize-2'};
    if (id.includes('edit') || pack?.type === 'image-to-image') return {label: 'Image edit', icon: 'image-plus'};
    return {label: 'Generate', icon: 'sparkles'};
  }

  function filePlanHtml(files, heading = 'Model files', dynamic = false) {
    if (!files?.length) return '';
    return `
      <div class="mt-2 border border-zinc-800 rounded-xl overflow-hidden bg-zinc-950/80">
        <div class="px-3 py-2 border-b border-zinc-800 text-[10px] font-bold uppercase tracking-wider text-zinc-500">${escapeHtml(heading)}</div>
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
            <div class="px-3 py-2.5 border-b last:border-b-0 border-zinc-900 flex flex-col gap-1.5">
              <div class="flex items-center justify-between gap-3">
                <code class="text-[11px] text-zinc-300 break-all">${escapeHtml(file.filename || 'unknown')}</code>
                ${dynamic && state === 'downloading' ? '<i data-lucide="loader-2" class="w-3 h-3 text-orange-400 animate-spin shrink-0"></i>' : ''}
              </div>
              <span class="text-[10px] text-zinc-500 break-all">${escapeHtml(file.folder || 'model')}${file.precision ? ` · ${escapeHtml(String(file.precision).toUpperCase())}` : ''}${file.url ? ` · ${escapeHtml(sourceLabel(file.url))}` : ''}</span>
              ${file.destination ? `<span class="text-[10px] text-zinc-600 break-all">→ ${escapeHtml(file.destination)}</span>` : ''}
              ${dynamic && detail ? `<span class="text-[10px] ${state === 'failed' ? 'text-red-400' : 'text-zinc-400'}">${escapeHtml(detail)}</span>` : ''}
              ${dynamic && pct !== null ? `
                <div class="h-1.5 bg-zinc-800 rounded-full overflow-hidden">
                  <div class="h-full bg-orange-500 transition-all duration-300" style="width:${pct.toFixed(1)}%"></div>
                </div>
              ` : ''}
              ${file.error ? `<span class="text-[10px] text-red-400 break-words">${escapeHtml(file.error)}</span>` : ''}
            </div>
          `;
        }).join('')}
      </div>
    `;
  }

  function detailsHtml(files, label, dynamic = false, open = false) {
    if (!files?.length) return '';
    return `
      <details class="group border-t border-zinc-800/80 pt-3" ${open ? 'open' : ''}>
        <summary class="cursor-pointer list-none flex items-center justify-between gap-3 text-[11px] text-zinc-500 hover:text-zinc-300 transition select-none">
          <span class="flex items-center gap-1.5"><i data-lucide="hard-drive-download" class="w-3.5 h-3.5"></i> ${escapeHtml(label)}</span>
          <span class="flex items-center gap-1">${files.length} file${files.length === 1 ? '' : 's'} <i data-lucide="chevron-down" class="w-3.5 h-3.5 group-open:rotate-180 transition-transform"></i></span>
        </summary>
        ${filePlanHtml(files, dynamic ? 'Install activity' : 'Model files', dynamic)}
      </details>
    `;
  }

  function setLibraryStatus(message, tone = 'neutral') {
    const status = document.getElementById('curated-tools-status');
    if (!status) return;
    const toneClasses = {
      neutral: 'text-zinc-500',
      working: 'text-orange-300',
      success: 'text-emerald-400',
      warning: 'text-amber-300',
      error: 'text-red-400',
    };
    status.className = `text-xs min-h-5 ${toneClasses[tone] || toneClasses.neutral}`;
    status.textContent = message || '';
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
      <section id="curated-tools-section" class="bg-zinc-900/90 backdrop-blur-xl border border-zinc-800 rounded-3xl p-5 md:p-8 shadow-xl">
        <div class="flex flex-col sm:flex-row sm:items-start justify-between gap-4 mb-6">
          <div class="max-w-2xl">
            <div class="flex items-center gap-2 mb-1.5">
              <div class="w-8 h-8 rounded-xl bg-orange-500/10 border border-orange-500/20 flex items-center justify-center"><i data-lucide="library" class="w-4 h-4 text-orange-400"></i></div>
              <h2 class="text-xl font-semibold text-zinc-100">Curated Library</h2>
            </div>
            <p class="text-sm text-zinc-500 leading-relaxed">Orange-tested workflows with guided setup. Choose a backend and Orange will tell you what is already ready, what it would download, and what needs attention before anything changes.</p>
          </div>
          <button id="curated-refresh-btn" class="self-start bg-zinc-800 hover:bg-zinc-700 text-zinc-300 px-3 py-2 rounded-lg text-xs font-medium transition flex items-center gap-2 border border-zinc-700"><i data-lucide="refresh-cw" class="w-3.5 h-3.5"></i> Scan again</button>
        </div>

        <div class="bg-zinc-950/55 border border-zinc-800 rounded-2xl p-4 mb-4">
          <div class="grid grid-cols-1 md:grid-cols-[minmax(0,1fr)_auto] gap-4 md:items-end">
            <div>
              <label class="text-[10px] text-zinc-500 font-bold uppercase tracking-wider block mb-1.5">Set up for</label>
              <select id="curated-server" class="w-full bg-zinc-950 border border-zinc-800 rounded-xl px-3 py-2.5 text-xs text-zinc-300 outline-none focus:border-orange-500"></select>
            </div>
            <div id="curated-hardware" class="text-[11px] text-zinc-500 md:text-right min-h-5"></div>
          </div>
          <details id="curated-storage-details" class="mt-3 border-t border-zinc-800/70 pt-3">
            <summary class="cursor-pointer list-none text-[11px] text-zinc-500 hover:text-zinc-300 flex items-center gap-2 select-none"><i data-lucide="folder-cog" class="w-3.5 h-3.5"></i> Download location <span class="text-zinc-600">Only needed when models are missing</span></summary>
            <div class="mt-3">
              <input id="curated-models-root" class="w-full bg-zinc-950 border border-zinc-800 rounded-xl p-3 text-xs text-zinc-300 font-mono outline-none focus:border-orange-500" placeholder="ComfyUI models folder or shared path">
              <p class="text-[10px] text-zinc-600 mt-1.5">If this backend already has compatible models, Orange uses them in place and does not need filesystem access.</p>
            </div>
          </details>
        </div>

        <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-4">
          <div id="curated-tools-status" class="text-xs text-zinc-500 min-h-5" aria-live="polite"></div>
          <div id="curated-summary" class="flex items-center flex-wrap gap-1.5"></div>
        </div>
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
      const serverUrl = document.getElementById('curated-server').value;
      localStorage.setItem('orange_curated_server', serverUrl);
      inspectionByPack = new Map();
      inspectionHardware = null;
      syncModelsRoot();
      renderCatalog();
      await refreshJobs();
      await inspectServer();
    });
    document.getElementById('curated-models-root').addEventListener('change', () => {
      const serverUrl = document.getElementById('curated-server').value;
      localStorage.setItem(modelsRootStorageKey(serverUrl), document.getElementById('curated-models-root').value.trim());
      inspectServer();
    });

    setToolsSubtab(localStorage.getItem('orange_tools_subtab') || 'editor');
    if (window.lucide) lucide.createIcons();
  }

  function syncModelsRoot() {
    if (!catalog) return;
    const serverSelect = document.getElementById('curated-server');
    const modelsRoot = document.getElementById('curated-models-root');
    if (!serverSelect || !modelsRoot) return;
    const server = (catalog.servers || []).find((item) => item.url === serverSelect.value);
    const saved = localStorage.getItem(modelsRootStorageKey(serverSelect.value));
    modelsRoot.value = saved ?? server?.modelsRoot ?? catalog.detectedModelsRoot ?? '';
  }

  function jobStageLabel(job) {
    const labels = {
      queued: 'Waiting to start',
      inspecting: 'Checking backend',
      downloading: 'Downloading models',
      materializing: 'Preparing workflow',
      preflight: 'Final compatibility check',
      completed: 'Ready',
      interrupted: 'Interrupted',
    };
    return labels[job?.stage] || job?.message || 'Working';
  }

  function cardState(pack, inspection, job) {
    if (job?.state === 'queued' || job?.state === 'running') return 'working';
    if (job?.state === 'failed' || job?.state === 'interrupted') return 'failed';
    if (inspection?.missingNodes?.length || inspection?.unknownModels?.length) return 'blocked';
    if (inspection?.ready) return 'ready';
    if (inspection) return 'download';
    return 'scanning';
  }

  function stateBadge(pack, inspection, job) {
    const state = cardState(pack, inspection, job);
    const configs = {
      working: ['Working', 'text-orange-300 bg-orange-500/10 border-orange-500/20', 'loader-2', true],
      failed: ['Needs attention', 'text-red-300 bg-red-500/10 border-red-500/20', 'circle-alert', false],
      blocked: ['Blocked', 'text-amber-300 bg-amber-500/10 border-amber-500/20', 'triangle-alert', false],
      ready: [pack.installed ? 'Ready' : 'Ready to add', 'text-emerald-300 bg-emerald-500/10 border-emerald-500/20', 'circle-check', false],
      download: ['Download needed', 'text-zinc-300 bg-zinc-800 border-zinc-700', 'download', false],
      scanning: ['Checking…', 'text-zinc-400 bg-zinc-800 border-zinc-700', 'loader-2', true],
    };
    const [label, classes, icon, spin] = configs[state];
    return `<span class="inline-flex items-center gap-1.5 border rounded-full px-2 py-1 text-[10px] font-semibold ${classes}"><i data-lucide="${icon}" class="w-3 h-3 ${spin ? 'animate-spin' : ''}"></i>${label}</span>`;
  }

  function inspectionStatus(pack, inspection, job) {
    if (job?.state === 'queued' || job?.state === 'running') {
      const files = job.files?.length ? job.files : job.downloadPlan;
      return `
        <div class="bg-orange-500/5 border border-orange-500/20 rounded-xl p-3">
          <div class="flex items-center gap-2 text-xs font-semibold text-orange-200"><i data-lucide="loader-2" class="w-3.5 h-3.5 animate-spin"></i>${escapeHtml(jobStageLabel(job))}</div>
          ${job.message && job.message !== jobStageLabel(job) ? `<div class="text-[10px] text-orange-300/70 mt-1">${escapeHtml(job.message)}</div>` : ''}
          ${filePlanHtml(files, job.mode === 'existing' ? 'Using existing models' : 'Install progress', true)}
        </div>
      `;
    }
    if (job?.state === 'failed' || job?.state === 'interrupted') {
      return `
        <div class="bg-red-500/5 border border-red-500/20 rounded-xl p-3 text-xs text-red-300">
          <div class="font-semibold flex items-center gap-2"><i data-lucide="circle-alert" class="w-3.5 h-3.5"></i>${job.state === 'interrupted' ? 'Install was interrupted' : 'Install did not finish'}</div>
          <div class="mt-1 text-[11px] text-red-300/80">${escapeHtml(job.error || 'The workflow setup did not complete.')}</div>
        </div>
        ${detailsHtml(job.files, 'Last install details', true, false)}
      `;
    }
    if (job?.state === 'completed') {
      return `
        <div class="text-xs text-emerald-300 flex items-center gap-2"><i data-lucide="circle-check" class="w-3.5 h-3.5"></i>${escapeHtml(job.message || 'Setup completed successfully.')}</div>
        ${detailsHtml(job.files, job.mode === 'existing' ? 'Models already on this backend' : 'Installed model files', true, false)}
      `;
    }
    if (!inspection) return '<div class="text-xs text-zinc-600 flex items-center gap-2"><i data-lucide="loader-2" class="w-3.5 h-3.5 animate-spin"></i>Checking this backend…</div>';
    if (inspection.ready) {
      return `
        <div class="text-xs text-emerald-300 flex items-center gap-2"><i data-lucide="circle-check" class="w-3.5 h-3.5"></i>${pack.installed ? 'Ready on this backend.' : 'Everything this workflow needs is already on this backend.'}</div>
        ${detailsHtml(inspection.selectedModels, 'Models Orange will use')}
      `;
    }
    if (inspection.missingNodes?.length) {
      return `
        <div class="text-xs text-amber-300 flex items-start gap-2"><i data-lucide="blocks" class="w-3.5 h-3.5 mt-0.5 shrink-0"></i><span>This ComfyUI is missing ${inspection.missingNodes.length} required node${inspection.missingNodes.length === 1 ? '' : 's'}.</span></div>
        <details class="border-t border-zinc-800/80 pt-3"><summary class="cursor-pointer text-[11px] text-zinc-500 hover:text-zinc-300">Show missing nodes</summary><div class="mt-2 text-[10px] text-zinc-500 font-mono break-all">${inspection.missingNodes.map(escapeHtml).join('<br>')}</div></details>
      `;
    }
    if (inspection.unknownModels?.length) {
      return '<div class="text-xs text-amber-300 flex items-start gap-2"><i data-lucide="help-circle" class="w-3.5 h-3.5 mt-0.5 shrink-0"></i><span>Orange cannot safely verify this workflow’s model inventory on this ComfyUI build.</span></div>';
    }
    const count = inspection.downloadPlan?.length || 0;
    return `
      <div class="text-xs text-zinc-300 flex items-center gap-2"><i data-lucide="download" class="w-3.5 h-3.5 text-orange-400"></i>${count} missing model file${count === 1 ? '' : 's'} will be downloaded. Existing compatible files are reused.</div>
      ${detailsHtml(inspection.downloadPlan, 'See exactly what Orange will download')}
    `;
  }

  function renderSummary() {
    const summary = document.getElementById('curated-summary');
    const hardware = document.getElementById('curated-hardware');
    if (!summary) return;
    const packs = catalog?.packs || [];
    if (!packs.length || !inspectionByPack.size) {
      summary.innerHTML = '';
      if (hardware) hardware.textContent = hardwareLabel(inspectionHardware);
      return;
    }
    let ready = 0;
    let downloads = 0;
    let blocked = 0;
    packs.forEach((pack) => {
      const inspection = inspectionByPack.get(pack.id);
      if (!inspection) return;
      if (inspection.missingNodes?.length || inspection.unknownModels?.length) blocked += 1;
      else if (inspection.ready) ready += 1;
      else downloads += 1;
    });
    const installed = packs.filter((pack) => pack.installed).length;
    summary.innerHTML = [
      installed ? `<span class="text-[10px] px-2 py-1 rounded-full border border-zinc-700 bg-zinc-800 text-zinc-300">${installed} in Orange</span>` : '',
      ready ? `<span class="text-[10px] px-2 py-1 rounded-full border border-emerald-500/20 bg-emerald-500/10 text-emerald-300">${ready} ready</span>` : '',
      downloads ? `<span class="text-[10px] px-2 py-1 rounded-full border border-orange-500/20 bg-orange-500/10 text-orange-300">${downloads} need downloads</span>` : '',
      blocked ? `<span class="text-[10px] px-2 py-1 rounded-full border border-amber-500/20 bg-amber-500/10 text-amber-300">${blocked} blocked</span>` : '',
    ].filter(Boolean).join('');
    if (hardware) hardware.textContent = hardwareLabel(inspectionHardware);
  }

  function actionForPack(pack, inspection, job) {
    const busy = job?.state === 'queued' || job?.state === 'running';
    const retryable = job?.state === 'failed' || job?.state === 'interrupted';
    if (busy) return {label: jobStageLabel(job), disabled: true, primary: false, icon: 'loader-2', spin: true};
    if (retryable) return {label: 'Retry setup', disabled: false, primary: true, icon: 'rotate-ccw'};
    if (inspection?.missingNodes?.length) return {label: 'Required nodes missing', disabled: true, primary: false, icon: 'blocks'};
    if (inspection?.unknownModels?.length) return {label: 'Can’t verify models', disabled: true, primary: false, icon: 'help-circle'};
    if (inspection?.ready && pack.installed) return {label: 'Verify setup', disabled: false, primary: false, icon: 'shield-check'};
    if (inspection?.ready) return {label: 'Add to Orange', disabled: false, primary: true, icon: 'plus'};
    if (inspection) {
      const count = inspection.downloadPlan?.length || 0;
      return {
        label: pack.installed ? 'Set up this backend' : `Install ${count} file${count === 1 ? '' : 's'}`,
        disabled: false,
        primary: true,
        icon: 'download',
      };
    }
    return {label: 'Checking…', disabled: true, primary: false, icon: 'loader-2', spin: true};
  }

  function renderCatalog() {
    const serverSelect = document.getElementById('curated-server');
    const list = document.getElementById('curated-tools-list');
    if (!serverSelect || !list || !catalog) return;

    const servers = catalog.servers || [];
    if (!servers.length) {
      list.innerHTML = `
        <div class="lg:col-span-2 border border-dashed border-zinc-700 rounded-2xl p-8 text-center bg-zinc-950/40">
          <div class="w-10 h-10 mx-auto rounded-xl bg-zinc-800 flex items-center justify-center mb-3"><i data-lucide="server-off" class="w-5 h-5 text-zinc-500"></i></div>
          <h3 class="text-sm font-semibold text-zinc-200">Connect a ComfyUI backend first</h3>
          <p class="text-xs text-zinc-500 mt-1 max-w-md mx-auto">The library checks a real backend before it offers installs, so Orange never guesses about nodes or models.</p>
          <button id="curated-open-general" class="mt-4 bg-zinc-800 hover:bg-zinc-700 border border-zinc-700 text-zinc-300 px-3 py-2 rounded-lg text-xs font-semibold">Open General Settings</button>
        </div>
      `;
      document.getElementById('curated-open-general')?.addEventListener('click', () => document.getElementById('tab-general')?.click());
      renderSummary();
      if (window.lucide) lucide.createIcons();
      return;
    }

    const serverUrl = serverSelect.value;
    list.innerHTML = (catalog.packs || []).map((pack) => {
      const inspection = inspectionByPack.get(pack.id);
      const job = jobByKey.get(installKey(serverUrl, pack.id));
      const action = actionForPack(pack, inspection, job);
      const presentation = typePresentation(pack);
      const highlights = Array.isArray(pack.highlights) ? pack.highlights : [];
      const buttonClass = action.primary
        ? 'bg-orange-600 hover:bg-orange-500 text-white border border-orange-500/60'
        : 'bg-zinc-800 hover:bg-zinc-700 text-zinc-300 border border-zinc-700';
      const thumbnail = pack.thumbnail
        ? `<div class="relative overflow-hidden rounded-xl border border-zinc-800 bg-zinc-900 aspect-[16/9]">
            <img src="${escapeHtml(pack.thumbnail)}" alt="${escapeHtml(pack.thumbnailAlt || `${pack.name} example`)}" loading="lazy" class="w-full h-full object-cover" draggable="false">
            <div class="absolute left-2 bottom-2 text-[9px] uppercase tracking-wider font-bold text-zinc-200 bg-black/65 border border-white/10 rounded-md px-1.5 py-1 backdrop-blur-sm">Example</div>
          </div>`
        : '';
      return `
        <article class="bg-zinc-950/65 border ${pack.installed ? 'border-emerald-900/60' : 'border-zinc-800'} rounded-2xl p-5 flex flex-col gap-4 shadow-sm hover:border-zinc-700 transition-colors">
          ${thumbnail}
          <div class="flex items-start gap-3">
            <div class="w-10 h-10 rounded-xl bg-zinc-900 border border-zinc-800 flex items-center justify-center shrink-0"><i data-lucide="${presentation.icon}" class="w-4.5 h-4.5 text-orange-400"></i></div>
            <div class="min-w-0 flex-1">
              <div class="flex flex-wrap items-center gap-2">
                <h3 class="text-sm font-semibold text-zinc-100">${escapeHtml(pack.name)}</h3>
                ${pack.recommended ? '<span class="text-[9px] uppercase tracking-wider font-bold text-orange-300 bg-orange-500/10 border border-orange-500/20 rounded-full px-1.5 py-0.5">Recommended</span>' : ''}
                ${pack.installed ? '<span class="text-[9px] uppercase tracking-wider font-bold text-emerald-300 bg-emerald-500/10 border border-emerald-500/20 rounded-full px-1.5 py-0.5">In Orange</span>' : ''}
              </div>
              <div class="text-[10px] text-zinc-600 mt-0.5">${escapeHtml(presentation.label)}</div>
            </div>
            ${stateBadge(pack, inspection, job)}
          </div>

          <div>
            <p class="text-xs text-zinc-400 leading-relaxed">${escapeHtml(pack.tagline || pack.description || '')}</p>
            ${highlights.length ? `<div class="flex flex-wrap gap-1.5 mt-2.5">${highlights.map((item) => `<span class="text-[10px] text-zinc-500 bg-zinc-900 border border-zinc-800 rounded-md px-2 py-1">${escapeHtml(item)}</span>`).join('')}</div>` : ''}
          </div>

          <div class="min-h-6">${inspectionStatus(pack, inspection, job)}</div>

          <div class="mt-auto flex items-center gap-2 pt-1">
            <button data-pack-id="${escapeHtml(pack.id)}" ${action.disabled ? 'disabled' : ''} class="flex-1 justify-center ${buttonClass} px-3 py-2.5 rounded-xl text-xs font-semibold transition disabled:opacity-40 disabled:cursor-not-allowed flex items-center gap-2">
              <i data-lucide="${action.icon}" class="w-3.5 h-3.5 ${action.spin ? 'animate-spin' : ''}"></i>${escapeHtml(action.label)}
            </button>
          </div>
        </article>
      `;
    }).join('');

    list.querySelectorAll('[data-pack-id]').forEach((button) => {
      button.addEventListener('click', () => runPackAction(button.dataset.packId));
    });
    renderSummary();
    if (window.lucide) lucide.createIcons();
  }

  function renderServerOptions(previousUrl = '') {
    const serverSelect = document.getElementById('curated-server');
    if (!serverSelect || !catalog) return;
    serverSelect.innerHTML = '';
    const servers = catalog.servers || [];
    if (!servers.length) {
      const option = document.createElement('option');
      option.value = '';
      option.textContent = 'No ComfyUI backends configured';
      serverSelect.appendChild(option);
      serverSelect.disabled = true;
      return;
    }
    serverSelect.disabled = false;
    servers.forEach((server) => {
      const option = document.createElement('option');
      option.value = server.url;
      let host = server.url;
      try { host = new URL(server.url).host; } catch (_) { /* keep URL */ }
      option.textContent = `Backend ${server.priority || 1} · ${host}`;
      serverSelect.appendChild(option);
    });
    const savedUrl = localStorage.getItem('orange_curated_server') || '';
    const preferred = previousUrl || savedUrl;
    if (preferred && servers.some((server) => server.url === preferred)) serverSelect.value = preferred;
    localStorage.setItem('orange_curated_server', serverSelect.value);
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
      if (finished) await refreshCatalog({skipJobs: true});
    } catch (_) {
      pollTimer = setTimeout(pollJobs, 2000);
    }
  }

  async function inspectServer() {
    const serverUrl = document.getElementById('curated-server')?.value;
    const modelsRoot = document.getElementById('curated-models-root')?.value.trim() || '';
    if (!serverUrl) {
      inspectionByPack = new Map();
      inspectionHardware = null;
      renderCatalog();
      return;
    }
    setLibraryStatus('Checking nodes and model inventory…', 'working');
    try {
      const response = await authFetch('/api/admin/workflow-packs/inspect', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({serverUrl, modelsRoot}),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : (data.detail?.message || 'Could not inspect backend.'));
      inspectionByPack = new Map((data.packs || []).map((pack) => [pack.pack, pack]));
      inspectionHardware = data.hardware || null;
      if (data.modelsRoot && !document.getElementById('curated-models-root').value.trim()) {
        document.getElementById('curated-models-root').value = data.modelsRoot;
      }
      const ready = (data.packs || []).filter((pack) => pack.ready).length;
      const blocked = (data.packs || []).filter((pack) => pack.missingNodes?.length || pack.unknownModels?.length).length;
      const downloads = (data.packs || []).length - ready - blocked;
      const pieces = [];
      if (ready) pieces.push(`${ready} ready now`);
      if (downloads) pieces.push(`${downloads} need downloads`);
      if (blocked) pieces.push(`${blocked} need attention`);
      setLibraryStatus(pieces.length ? pieces.join(' · ') : 'Backend scan complete.', blocked ? 'warning' : 'success');

      const storageDetails = document.getElementById('curated-storage-details');
      if (storageDetails && downloads > 0 && !document.getElementById('curated-models-root').value.trim()) storageDetails.open = true;
      renderCatalog();
    } catch (error) {
      inspectionByPack = new Map();
      inspectionHardware = null;
      setLibraryStatus(error.message, 'error');
      renderCatalog();
    }
  }

  async function refreshCatalog(options = {}) {
    setupToolsWorkspace();
    const serverSelect = document.getElementById('curated-server');
    if (!localStorage.getItem('orange_admin_key')) return;
    const previousUrl = serverSelect?.value || '';
    setLibraryStatus('Loading curated tools…', 'working');
    try {
      const response = await authFetch('/api/admin/workflow-packs');
      if (!response.ok) throw new Error(response.status === 401 ? 'Admin login required.' : 'Could not load curated tools.');
      catalog = await response.json();
      renderServerOptions(previousUrl);
      renderCatalog();
      if (!(catalog.servers || []).length) {
        setLibraryStatus('Add a ComfyUI backend in General Settings to use the library.', 'warning');
        return;
      }
      if (!options.skipJobs) await refreshJobs();
      await inspectServer();
    } catch (error) {
      setLibraryStatus(error.message, 'error');
    }
  }

  async function runPackAction(packId) {
    const serverUrl = document.getElementById('curated-server').value;
    const modelsRoot = document.getElementById('curated-models-root').value.trim();
    const inspection = inspectionByPack.get(packId);
    const key = installKey(serverUrl, packId);
    const existingJob = jobByKey.get(key);

    if (!serverUrl) {
      setLibraryStatus('Configure a ComfyUI backend first.', 'warning');
      return;
    }
    if (!inspection?.ready && !modelsRoot) {
      const storageDetails = document.getElementById('curated-storage-details');
      if (storageDetails) storageDetails.open = true;
      document.getElementById('curated-models-root')?.focus();
      setLibraryStatus('Choose a writable models folder before Orange downloads the missing files.', 'warning');
      return;
    }

    setLibraryStatus(
      existingJob?.state === 'failed' || existingJob?.state === 'interrupted'
        ? 'Retrying workflow setup…'
        : inspection?.ready
          ? 'Adding workflow and running the final check…'
          : 'Starting model download and workflow setup…',
      'working',
    );

    try {
      const retry = existingJob?.state === 'failed' || existingJob?.state === 'interrupted';
      const url = retry
        ? `/api/admin/workflow-packs/install-jobs/${encodeURIComponent(existingJob.id)}/retry`
        : '/api/admin/workflow-packs/install-jobs';
      const options = {method: 'POST', headers: {'Content-Type': 'application/json'}};
      if (!retry) options.body = JSON.stringify({packId, serverUrl, modelsRoot});
      const response = await authFetch(url, options);
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : (data.detail?.message || 'Could not start workflow setup.'));
      const job = data.job;
      jobByKey.set(installKey(job.serverUrl, job.packId), job);
      setLibraryStatus(data.created ? 'Setup is running in the background. You can leave this screen or refresh safely.' : 'This workflow already has an active setup job.', 'working');
      renderCatalog();
      scheduleJobPoll();
    } catch (error) {
      setLibraryStatus(error.message, 'error');
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