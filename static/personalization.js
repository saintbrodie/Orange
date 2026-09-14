(() => {
  const menu = document.getElementById('admin-menu');
  const main = document.querySelector('body > main');
  if (!menu || !main) return;

  const DEFAULT_CLASS = 'admin-tab flex items-center gap-2 text-zinc-400 hover:text-zinc-200 px-4 py-2 rounded-lg text-sm font-medium transition';
  const ACTIVE_CLASS = 'admin-tab active flex items-center gap-2 bg-zinc-800 text-orange-400 px-4 py-2 rounded-lg text-sm font-medium shadow-sm border border-zinc-700 transition';
  const KNOWN_CONTAINERS = ['settings-container', 'tools-container', 'dashboard-container', 'gallery-container'];

  let presets = {};
  let state = null;
  let selectedTheme = 'classic';

  function adminKey() { return localStorage.getItem('orange_admin_key') || ''; }
  function adminFetch(url, options = {}) {
    options.headers = options.headers || {};
    options.headers.Authorization = `Bearer ${adminKey()}`;
    return fetch(url, options);
  }

  const tab = document.createElement('button');
  tab.id = 'tab-personalization';
  tab.className = DEFAULT_CLASS;
  tab.type = 'button';
  const icon = document.createElement('i');
  icon.setAttribute('data-lucide', 'palette');
  icon.className = 'w-4 h-4';
  tab.append(icon, document.createTextNode(' Personalization'));
  menu.insertBefore(tab, document.getElementById('tab-analytics'));

  const container = document.createElement('div');
  container.id = 'personalization-container';
  container.className = 'hidden w-full max-w-6xl mx-auto animate-in fade-in duration-300 pb-8';
  container.innerHTML = `
    <div class="bg-zinc-900/90 backdrop-blur-xl border border-zinc-800 rounded-3xl p-8 shadow-xl">
      <div class="flex items-start justify-between gap-6 mb-7">
        <div>
          <h2 class="text-xl font-semibold text-zinc-100 flex items-center gap-2"><i data-lucide="palette" class="w-5 h-5 text-orange-500"></i> Personalization</h2>
          <p class="text-sm text-zinc-500 mt-2">Theme Orange for your team or replace Orange branding entirely. Generator controls stay unchanged.</p>
        </div>
        <button id="personalization-save" class="bg-gradient-to-r from-orange-600 to-orange-500 text-white font-semibold rounded-xl py-3 px-5 transition flex items-center gap-2">
          <i data-lucide="save" class="w-4 h-4"></i> Save
        </button>
      </div>

      <div id="personalization-grid" style="display:grid;grid-template-columns:minmax(0,1.45fr) minmax(300px,.8fr);gap:28px;align-items:start">
        <div class="space-y-8">
          <section>
            <div class="flex items-end justify-between gap-4 mb-3">
              <div>
                <h3 class="text-sm font-semibold text-zinc-200">Theme</h3>
                <p class="text-xs text-zinc-500 mt-1">Presets include their own mascot treatment, palette, motion and Generate icon.</p>
              </div>
            </div>
            <div id="theme-cards" class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3"></div>
          </section>

          <section class="pt-6 border-t border-zinc-800/60">
            <h3 class="text-sm font-semibold text-zinc-200">Branding</h3>
            <p class="text-xs text-zinc-500 mt-1 mb-4">Branding can be used with any preset. Custom images replace the themed mascot.</p>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
              <label class="space-y-1"><span class="text-[10px] uppercase font-bold tracking-wider text-zinc-500">App Name</span><input id="brand-name" maxlength="64" class="w-full bg-zinc-950 border border-zinc-800 rounded-xl p-3 text-sm outline-none focus:border-orange-500"></label>
              <label class="space-y-1"><span class="text-[10px] uppercase font-bold tracking-wider text-zinc-500">Tagline</span><input id="brand-tagline" maxlength="120" class="w-full bg-zinc-950 border border-zinc-800 rounded-xl p-3 text-sm outline-none focus:border-orange-500"></label>
            </div>
            <label class="space-y-1 block mt-4"><span class="text-[10px] uppercase font-bold tracking-wider text-zinc-500">Footer Text <span class="normal-case font-normal">(optional)</span></span><input id="brand-footer" maxlength="160" class="w-full bg-zinc-950 border border-zinc-800 rounded-xl p-3 text-sm outline-none focus:border-orange-500" placeholder="Internal AI tools · Acme Creative"></label>

            <div class="grid grid-cols-1 md:grid-cols-2 gap-4 mt-4">
              <div class="bg-zinc-950/60 border border-zinc-800 rounded-2xl p-4">
                <div class="flex items-center justify-between gap-3 mb-3"><div><div class="text-xs font-semibold text-zinc-300">Primary Logo</div><div class="text-[10px] text-zinc-500">Replaces the full Orange mascot.</div></div><img id="brand-logo-preview" class="w-12 h-12 object-contain hidden" alt="Logo preview"></div>
                <div class="flex gap-2"><button id="upload-logo" class="text-xs bg-zinc-800 border border-zinc-700 px-3 py-2 rounded-lg">Upload</button><button id="remove-logo" class="hidden text-xs text-red-300 border border-red-900/60 px-3 py-2 rounded-lg">Remove</button></div>
                <input id="logo-file" type="file" accept="image/png,image/jpeg,image/webp" class="hidden">
              </div>
              <div class="bg-zinc-950/60 border border-zinc-800 rounded-2xl p-4">
                <div class="flex items-center justify-between gap-3 mb-3"><div><div class="text-xs font-semibold text-zinc-300">Compact Icon</div><div class="text-[10px] text-zinc-500">Favicon and compact brand mark.</div></div><img id="brand-icon-preview" class="w-12 h-12 object-contain hidden" alt="Icon preview"></div>
                <div class="flex gap-2"><button id="upload-icon" class="text-xs bg-zinc-800 border border-zinc-700 px-3 py-2 rounded-lg">Upload</button><button id="remove-icon" class="hidden text-xs text-red-300 border border-red-900/60 px-3 py-2 rounded-lg">Remove</button></div>
                <input id="icon-file" type="file" accept="image/png,image/jpeg,image/webp" class="hidden">
              </div>
            </div>
          </section>

          <section id="custom-theme-section" class="hidden pt-6 border-t border-zinc-800/60">
            <h3 class="text-sm font-semibold text-zinc-200">Custom Theme</h3>
            <p class="text-xs text-zinc-500 mt-1 mb-4">Structured tokens stay upgrade-safe; arbitrary CSS is intentionally not exposed.</p>
            <div id="custom-colors" class="grid grid-cols-2 md:grid-cols-3 gap-3"></div>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4 mt-4">
              <label class="space-y-1"><span class="text-[10px] uppercase font-bold tracking-wider text-zinc-500">Corner Radius</span><input id="custom-radius" type="range" min="0" max="40" step="1" class="w-full"><div class="text-xs text-zinc-500"><span id="custom-radius-value">24</span> px</div></label>
              <label class="space-y-1"><span class="text-[10px] uppercase font-bold tracking-wider text-zinc-500">Motion</span><select id="custom-motion" class="w-full bg-zinc-950 border border-zinc-800 rounded-xl p-3 text-sm"><option value="reduced">Reduced</option><option value="normal">Normal</option><option value="playful">Playful</option></select></label>
            </div>
          </section>

          <div id="personalization-message" class="hidden text-sm rounded-xl px-4 py-3"></div>
        </div>

        <aside>
          <div class="text-[10px] uppercase font-bold tracking-wider text-zinc-500 mb-2">Live Preview</div>
          <div id="personalization-preview">
            <div class="preview-shell">
              <div class="preview-side"><img id="preview-mascot" src="/static/orange.svg"><div id="preview-app-name" class="preview-name">Orange</div><div id="preview-tagline" style="font-size:8px;text-align:center;color:var(--preview-muted)">AI Media Tools</div></div>
              <div class="preview-main"><div class="preview-label">Prompt</div><div class="preview-input"></div><button class="preview-button"><span id="preview-button-label">Generate</span></button></div>
            </div>
          </div>
        </aside>
      </div>
    </div>`;
  main.appendChild(container);

  const colorFields = [
    ['accent', 'Accent'], ['accentSecondary', 'Accent 2'], ['background', 'Background'],
    ['panel', 'Panel'], ['text', 'Text'], ['muted', 'Muted']
  ];
  const colorGrid = container.querySelector('#custom-colors');
  colorFields.forEach(([key, label]) => {
    const wrapper = document.createElement('label');
    wrapper.className = 'space-y-1';
    const title = document.createElement('span'); title.className = 'text-[10px] uppercase font-bold tracking-wider text-zinc-500'; title.textContent = label;
    const row = document.createElement('div'); row.className = 'flex gap-2';
    const picker = document.createElement('input'); picker.type = 'color'; picker.id = `custom-${key}-picker`; picker.className = 'w-11 h-10 bg-zinc-950 border border-zinc-800 rounded-lg p-1';
    const text = document.createElement('input'); text.id = `custom-${key}`; text.maxLength = 7; text.className = 'min-w-0 flex-1 bg-zinc-950 border border-zinc-800 rounded-lg px-2 text-xs font-mono';
    picker.addEventListener('input', () => { text.value = picker.value; updatePreview(); });
    text.addEventListener('input', () => { if (/^#[0-9a-f]{6}$/i.test(text.value)) picker.value = text.value; updatePreview(); });
    row.append(picker, text); wrapper.append(title, row); colorGrid.appendChild(wrapper);
  });

  function resetView() {
    document.querySelectorAll('.admin-tab').forEach(el => { el.className = DEFAULT_CLASS; });
    KNOWN_CONTAINERS.forEach(id => {
      const el = document.getElementById(id); if (!el) return;
      el.classList.add('hidden');
      if (id === 'gallery-container') el.classList.remove('flex');
    });
    container.classList.add('hidden');
  }

  document.querySelectorAll('#tab-general,#tab-tools,#tab-analytics,#tab-gallery').forEach(other => {
    other.addEventListener('click', () => container.classList.add('hidden'));
  });
  document.getElementById('logout-btn')?.addEventListener('click', () => container.classList.add('hidden'));

  tab.addEventListener('click', async () => {
    resetView();
    tab.className = ACTIVE_CLASS;
    container.classList.remove('hidden');
    localStorage.setItem('orange_admin_tab', 'personalization');
    await load();
  });

  function currentPalette() {
    const preset = presets[selectedTheme] || presets.classic || {};
    if (selectedTheme !== 'custom') return preset;
    const custom = {};
    colorFields.forEach(([key]) => { custom[key] = document.getElementById(`custom-${key}`).value; });
    custom.radius = Number(document.getElementById('custom-radius').value || 24);
    return custom;
  }

  function updatePreview() {
    if (!state) return;
    const palette = currentPalette();
    const preview = document.getElementById('personalization-preview');
    preview.style.setProperty('--preview-accent', palette.accent || '#f97316');
    preview.style.setProperty('--preview-accent-2', palette.accentSecondary || '#ea580c');
    preview.style.setProperty('--preview-bg', palette.background || '#09090b');
    preview.style.setProperty('--preview-panel', palette.panel || '#18181b');
    preview.style.setProperty('--preview-text', palette.text || '#f4f4f5');
    preview.style.setProperty('--preview-muted', palette.muted || '#71717a');
    preview.style.setProperty('--preview-radius', `${palette.radius ?? 24}px`);

    document.getElementById('preview-app-name').textContent = document.getElementById('brand-name').value || 'Orange';
    document.getElementById('preview-tagline').textContent = document.getElementById('brand-tagline').value || '';
    const logo = state.brandingAssets?.logo || presets[selectedTheme]?.mascot || '/static/orange.svg';
    document.getElementById('preview-mascot').src = logo;
    document.getElementById('custom-theme-section').classList.toggle('hidden', selectedTheme !== 'custom');
    document.getElementById('custom-radius-value').textContent = document.getElementById('custom-radius').value;
  }

  function renderCards() {
    const target = document.getElementById('theme-cards'); target.textContent = '';
    Object.entries(presets).forEach(([id, preset]) => {
      const button = document.createElement('button'); button.type = 'button'; button.className = `theme-card ${id === selectedTheme ? 'active' : ''}`;
      const top = document.createElement('div'); top.className = 'flex items-center gap-3';
      const img = document.createElement('img'); img.src = preset.head || '/static/orange-head.svg'; img.alt = '';
      const copy = document.createElement('div');
      const name = document.createElement('div'); name.className = 'text-sm font-semibold text-zinc-200'; name.textContent = preset.name || id;
      const desc = document.createElement('div'); desc.className = 'text-[11px] text-zinc-500 mt-1 leading-snug'; desc.textContent = preset.description || '';
      copy.append(name, desc); top.append(img, copy); button.appendChild(top);
      button.addEventListener('click', () => { selectedTheme = id; renderCards(); updatePreview(); }); target.appendChild(button);
    });
  }

  function hydrate() {
    selectedTheme = state.theme || 'classic';
    document.getElementById('brand-name').value = state.branding?.appName || 'Orange';
    document.getElementById('brand-tagline').value = state.branding?.tagline || '';
    document.getElementById('brand-footer').value = state.branding?.footerText || '';
    colorFields.forEach(([key]) => {
      const value = state.custom?.[key] || '#000000';
      document.getElementById(`custom-${key}`).value = value;
      document.getElementById(`custom-${key}-picker`).value = value;
    });
    document.getElementById('custom-radius').value = state.custom?.radius ?? 24;
    document.getElementById('custom-motion').value = state.custom?.motion || 'normal';
    syncAssetPreview('logo'); syncAssetPreview('icon'); renderCards(); updatePreview();
  }

  function syncAssetPreview(kind) {
    const url = state.brandingAssets?.[kind];
    const preview = document.getElementById(`brand-${kind}-preview`);
    const remove = document.getElementById(`remove-${kind}`);
    preview.classList.toggle('hidden', !url); remove.classList.toggle('hidden', !url);
    if (url) preview.src = `${url}?v=${Date.now()}`; else preview.removeAttribute('src');
  }

  async function load() {
    const [presetData, res] = await Promise.all([
      window.OrangePersonalization?.presets?.() || fetch('/static/themes/presets.json').then(r => r.json()),
      adminFetch('/api/admin/personalization')
    ]);
    presets = presetData || {};
    if (!res.ok) { showMessage('Could not load personalization settings.', true); return; }
    state = await res.json(); hydrate();
  }

  function collect() {
    const custom = {};
    colorFields.forEach(([key]) => custom[key] = document.getElementById(`custom-${key}`).value);
    custom.radius = Number(document.getElementById('custom-radius').value);
    custom.motion = document.getElementById('custom-motion').value;
    return {
      theme: selectedTheme,
      branding: {
        appName: document.getElementById('brand-name').value.trim(),
        tagline: document.getElementById('brand-tagline').value.trim(),
        footerText: document.getElementById('brand-footer').value.trim()
      },
      custom
    };
  }

  function showMessage(message, error = false) {
    const el = document.getElementById('personalization-message');
    el.textContent = message; el.classList.remove('hidden', 'bg-red-950/50', 'text-red-200', 'border-red-900', 'bg-emerald-950/40', 'text-emerald-200', 'border-emerald-900');
    el.classList.add('border', error ? 'bg-red-950/50' : 'bg-emerald-950/40', error ? 'text-red-200' : 'text-emerald-200', error ? 'border-red-900' : 'border-emerald-900');
  }

  document.getElementById('personalization-save').addEventListener('click', async () => {
    const button = document.getElementById('personalization-save'); button.disabled = true;
    try {
      const res = await adminFetch('/api/admin/personalization', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(collect()) });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Save failed');
      state = data; hydrate(); await window.OrangePersonalization?.apply?.(state); showMessage('Personalization saved and applied.');
    } catch (err) { showMessage(err.message || 'Could not save personalization.', true); }
    finally { button.disabled = false; }
  });

  async function upload(kind, file) {
    if (!file) return;
    const body = new FormData(); body.append('file', file);
    const res = await adminFetch(`/api/admin/personalization/branding/${kind}`, { method: 'POST', body });
    const data = await res.json(); if (!res.ok) throw new Error(data.detail || 'Upload failed'); state = data; syncAssetPreview(kind); updatePreview(); await window.OrangePersonalization?.apply?.(state);
  }
  ['logo', 'icon'].forEach(kind => {
    const input = document.getElementById(`${kind}-file`);
    document.getElementById(`upload-${kind}`).addEventListener('click', () => input.click());
    input.addEventListener('change', async () => { try { await upload(kind, input.files?.[0]); showMessage(`${kind === 'logo' ? 'Logo' : 'Icon'} uploaded.`); } catch (e) { showMessage(e.message, true); } finally { input.value = ''; } });
    document.getElementById(`remove-${kind}`).addEventListener('click', async () => {
      const res = await adminFetch(`/api/admin/personalization/branding/${kind}`, { method: 'DELETE' });
      if (res.ok) { state = await res.json(); syncAssetPreview(kind); updatePreview(); await window.OrangePersonalization?.apply?.(state); }
    });
  });

  ['brand-name', 'brand-tagline', 'brand-footer', 'custom-radius', 'custom-motion'].forEach(id => document.getElementById(id).addEventListener('input', updatePreview));

  if (window.lucide) lucide.createIcons();
})();
