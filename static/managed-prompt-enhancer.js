(() => {
  let pollTimer = null;

  function authFetch(url, options = {}) {
    const key = localStorage.getItem('orange_admin_key');
    options.headers = options.headers || {};
    options.headers.Authorization = `Bearer ${key || ''}`;
    return fetch(url, options);
  }

  function formatBytes(value) {
    const bytes = Number(value || 0);
    if (!bytes) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
    const amount = bytes / (1024 ** index);
    return `${amount >= 100 || index === 0 ? amount.toFixed(0) : amount.toFixed(1)} ${units[index]}`;
  }

  function ensurePanel() {
    const provider = document.getElementById('setting-llm-provider');
    if (!provider) return null;
    let option = provider.querySelector('option[value="managed"]');
    if (!option) {
      option = document.createElement('option');
      option.value = 'managed';
      provider.insertBefore(option, provider.firstChild);
    }
    option.textContent = 'Internal LLM — Gemma 4 E2B (Private)';

    let panel = document.getElementById('managed-enhancer-panel');
    if (!panel) {
      panel = document.createElement('div');
      panel.id = 'managed-enhancer-panel';
      panel.className = 'hidden bg-violet-950/10 border border-violet-900/50 rounded-2xl p-4 space-y-3';
      const firstGrid = provider.closest('.grid');
      if (firstGrid) firstGrid.insertAdjacentElement('afterend', panel);
    }
    return panel;
  }

  function managedFieldContainers() {
    return [
      document.getElementById('setting-llm-model')?.closest('.space-y-1'),
      document.getElementById('setting-llm-baseurl')?.closest('.space-y-1'),
      document.getElementById('setting-llm-apikey')?.closest('.space-y-1'),
    ].filter(Boolean);
  }

  window.syncManagedEnhancerProviderUI = function syncManagedEnhancerProviderUI() {
    const provider = document.getElementById('setting-llm-provider');
    const panel = ensurePanel();
    if (!provider || !panel) return;
    const managed = provider.value === 'managed';
    managedFieldContainers().forEach((container) => container.classList.toggle('hidden', managed));
    panel.classList.toggle('hidden', !managed);
    if (managed) refreshStatus();
  };

  function progressHtml(status) {
    const total = Number(status.bytesTotal || 0);
    const downloaded = Number(status.bytesDownloaded || 0);
    const percent = total > 0 ? Math.max(0, Math.min(100, (downloaded / total) * 100)) : 0;
    if (!['queued', 'installing'].includes(status.state)) return '';
    return `
      <div class="space-y-2">
        <div class="h-2 rounded-full bg-zinc-800 overflow-hidden">
          <div class="h-full bg-violet-500 transition-all duration-300" style="width:${total ? percent : 4}%"></div>
        </div>
        <div class="flex flex-wrap gap-x-3 gap-y-1 text-[10px] text-zinc-500 font-mono">
          ${status.currentFile ? `<span class="text-zinc-400">${status.currentFile}</span>` : ''}
          ${total ? `<span>${formatBytes(downloaded)} / ${formatBytes(total)} · ${percent.toFixed(1)}%</span>` : ''}
          ${status.speedBps ? `<span>${formatBytes(status.speedBps)}/s</span>` : ''}
        </div>
      </div>
    `;
  }

  function renderStatus(status) {
    const panel = ensurePanel();
    if (!panel) return;
    const installing = ['queued', 'installing'].includes(status.state);
    const installed = !!status.installed;
    const failed = status.state === 'failed' || status.state === 'interrupted';
    const supported = status.supported !== false;
    const model = status.model || {};

    let badge = '<span class="text-[10px] uppercase tracking-wider font-bold text-zinc-500">Not installed</span>';
    if (installed) badge = '<span class="text-[10px] uppercase tracking-wider font-bold text-emerald-400">Ready</span>';
    else if (installing) badge = '<span class="text-[10px] uppercase tracking-wider font-bold text-violet-300">Installing</span>';
    else if (failed) badge = '<span class="text-[10px] uppercase tracking-wider font-bold text-red-400">Needs attention</span>';

    panel.innerHTML = `
      <div class="flex items-start justify-between gap-3">
        <div>
          <div class="flex items-center gap-2">
            <i data-lucide="brain-circuit" class="w-4 h-4 text-violet-400"></i>
            <strong class="text-sm text-zinc-200">Internal LLM</strong>
            ${badge}
          </div>
          <p class="text-xs text-zinc-500 mt-1">${model.name || 'Gemma 4 E2B Instruct'} · ${model.quantization || 'Q4_0 QAT'} · ~3.35 GB</p>
          <p class="text-[11px] text-zinc-600 mt-1">Orange's private prompt-enhancement model. It runs through an internal llama.cpp server, CPU-first so ComfyUI keeps the GPU, and unloads after 5 idle minutes.</p>
        </div>
      </div>
      ${status.message ? `<div class="text-xs ${failed ? 'text-red-300' : 'text-zinc-400'}">${status.message}</div>` : ''}
      ${status.error ? `<div class="bg-red-950/30 border border-red-900/60 rounded-xl p-3 text-xs text-red-300 break-words">${status.error}</div>` : ''}
      ${progressHtml(status)}
      <div class="flex flex-wrap gap-2">
        ${!installed && supported ? `<button id="managed-enhancer-install" ${installing ? 'disabled' : ''} class="bg-violet-600 hover:bg-violet-500 disabled:opacity-40 text-white px-3 py-2 rounded-lg text-xs font-semibold transition flex items-center gap-2"><i data-lucide="${failed ? 'rotate-ccw' : 'download'}" class="w-3.5 h-3.5"></i>${failed ? 'Retry Install' : 'Install Gemma 4'}</button>` : ''}
        ${installed ? '<button id="managed-enhancer-test" class="bg-zinc-800 hover:bg-zinc-700 border border-zinc-700 text-zinc-300 px-3 py-2 rounded-lg text-xs font-semibold transition flex items-center gap-2"><i data-lucide="play" class="w-3.5 h-3.5"></i>Test</button>' : ''}
        ${installed ? '<button id="managed-enhancer-remove" class="bg-zinc-900 hover:bg-red-950/40 border border-zinc-800 hover:border-red-900 text-zinc-500 hover:text-red-300 px-3 py-2 rounded-lg text-xs font-medium transition">Remove internal model</button>' : ''}
      </div>
      ${!supported ? `<div class="text-xs text-amber-300">Internal LLM is not packaged for ${status.platform || 'this platform'} yet. Existing Ollama and API providers still work.</div>` : ''}
      <div id="managed-enhancer-action-status" class="text-xs text-zinc-500"></div>
    `;

    document.getElementById('managed-enhancer-install')?.addEventListener('click', installManaged);
    document.getElementById('managed-enhancer-test')?.addEventListener('click', testManaged);
    document.getElementById('managed-enhancer-remove')?.addEventListener('click', removeManaged);
    if (window.lucide) lucide.createIcons();

    if (pollTimer) clearTimeout(pollTimer);
    pollTimer = installing ? setTimeout(refreshStatus, 1000) : null;
  }

  async function refreshStatus() {
    if (document.getElementById('setting-llm-provider')?.value !== 'managed') return;
    if (!localStorage.getItem('orange_admin_key')) return;
    try {
      const response = await authFetch('/api/admin/prompt-enhancer/managed/status');
      if (!response.ok) return;
      renderStatus(await response.json());
    } catch (_) {}
  }

  async function installManaged() {
    const button = document.getElementById('managed-enhancer-install');
    if (button) button.disabled = true;
    try {
      const response = await authFetch('/api/admin/prompt-enhancer/managed/install', {method: 'POST'});
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Could not start Internal LLM installation.');
      renderStatus(data);
    } catch (error) {
      const target = document.getElementById('managed-enhancer-action-status');
      if (target) target.textContent = error.message;
      if (button) button.disabled = false;
    }
  }

  async function testManaged() {
    const target = document.getElementById('managed-enhancer-action-status');
    if (target) target.textContent = 'Loading Gemma 4 and running a local test…';
    try {
      const response = await authFetch('/api/admin/prompt-enhancer/managed/test', {method: 'POST'});
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Internal LLM test failed.');
      if (target) target.textContent = `✓ ${data.response || 'Internal LLM is ready.'}`;
      await refreshStatus();
    } catch (error) {
      if (target) target.textContent = error.message;
    }
  }

  async function removeManaged() {
    if (!confirm('Remove Orange\'s internal Gemma 4 model and llama.cpp runtime? This does not affect Ollama, LM Studio, or ComfyUI models.')) return;
    try {
      const response = await authFetch('/api/admin/prompt-enhancer/managed/remove', {method: 'POST'});
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Could not remove Internal LLM.');
      renderStatus(data);
    } catch (error) {
      const target = document.getElementById('managed-enhancer-action-status');
      if (target) target.textContent = error.message;
    }
  }

  ensurePanel();
  document.getElementById('setting-llm-provider')?.addEventListener('change', window.syncManagedEnhancerProviderUI);
  document.getElementById('tab-general')?.addEventListener('click', () => setTimeout(() => {
    window.syncManagedEnhancerProviderUI();
    refreshStatus();
  }, 50));
  setTimeout(window.syncManagedEnhancerProviderUI, 0);
  setTimeout(window.syncManagedEnhancerProviderUI, 500);
})();
