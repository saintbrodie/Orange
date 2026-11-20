/* Provider settings and curated tools use the existing Admin workspace. */
(() => {
  const $ = id => document.getElementById(id);
  const fieldClass = 'w-full bg-zinc-950 border border-zinc-700 rounded-lg p-3 text-sm text-zinc-200';
  const buttonClass = 'bg-zinc-800 hover:bg-zinc-700 border border-zinc-700 rounded-lg px-4 py-2 text-sm';
  const providerNames = {google: 'Google', openai: 'OpenAI', anthropic: 'Anthropic', openrouter: 'OpenRouter', venice: 'Venice', xai: 'xAI (Grok)', runway: 'Runway', fal: 'fal.ai'};
  let providers = [];
  let editIndex = -1;
  const node = (tag, text = '', className = '') => {
    const el = document.createElement(tag); el.textContent = text; el.className = className; return el;
  };
  function field(parent, label, type = 'text', value = '') {
    const wrap = node('label', '', 'block space-y-2 text-sm text-zinc-400');
    wrap.append(node('span', label));
    const input = node(type === 'select' ? 'select' : 'input', '', fieldClass);
    if (type !== 'select') input.type = type;
    input.value = value;
    wrap.append(input); parent.append(wrap); return input;
  }
  function option(select, value, label = value) {
    const item = node('option', label); item.value = value; select.append(item);
  }
  function check(parent, label, checked) {
    const wrap = node('label', '', 'flex items-center gap-2 text-sm text-zinc-300');
    const input = document.createElement('input'); input.type = 'checkbox'; input.checked = checked;
    wrap.append(input, document.createTextNode(label)); parent.append(wrap); return input;
  }
  function choices(parent, label, values, selected) {
    const group = node('fieldset', '', 'flex flex-wrap gap-3'); group.append(node('legend', label, 'text-sm text-zinc-400 mb-2'));
    parent.append(group);
    const controls = values.map(value => [value, check(group, String(value), selected.includes(value))]);
    return () => controls.filter(([, input]) => input.checked).map(([value]) => value);
  }
  function action(parent, label, callback) {
    const button = node('button', label, buttonClass); button.type = 'button';
    button.addEventListener('click', async () => { button.disabled = true; try { await callback(); } finally { button.disabled = false; } });
    parent.append(button); return button;
  }
  async function api(path, method = 'GET', body) {
    const response = await adminFetch(path, {method, headers: {'Content-Type': 'application/json'}, ...(body === undefined ? {} : {body: JSON.stringify(body)})});
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Could not save these settings.');
    return data;
  }
  async function refreshProviders(options = {}) {
    const list = $('api-providers-list');
    if (!list) return;
    try {
      const opened = new Set([...list.querySelectorAll('details[data-provider][open]')].map(el => el.dataset.provider));
      providers = (await api('/api/admin/providers')).providers;
      list.replaceChildren();
      for (const provider of providers) {
        const card = node('details', '', 'bg-zinc-950/50 border border-zinc-800 rounded-xl p-4'); list.append(card);
        card.dataset.provider = provider.id;
        card.open = options.expand === provider.id || opened.has(provider.id);
        const summary = node('summary', '', 'cursor-pointer text-sm font-medium text-zinc-100');
        summary.append(document.createTextNode(providerNames[provider.id] || provider.id));
        summary.append(node('span', ` · ${provider.configured ? (!provider.supportsMedia || provider.enabled) ? provider.discoveredAt ? 'Connected' : 'Configured' : 'Disabled' : 'Not configured'}`, 'text-xs font-normal text-zinc-500'));
        card.append(summary);
        const body = node('div', '', 'space-y-4 pt-4'); card.append(body);
        if (provider.storageError) body.append(node('p', provider.storageError, 'text-xs text-amber-400'));
        const enabled = provider.supportsMedia ? check(body, 'Enable media generation', provider.enabled) : null;
        if (!provider.supportsMedia) body.append(node('p', 'Used for prompt enhancement.', 'text-xs text-zinc-400'));
        const key = field(body, 'API credential (leave blank to keep current)', 'password');
        key.autocomplete = 'new-password'; key.spellcheck = false;
        key.placeholder = provider.configured ? '••••••••••••••••' : 'Enter API credential';
        if (provider.discoveredAt) {
          const count = provider.catalog.filter(m => provider.models.includes(m.id)).length;
          body.append(node('p', count ? `${count} compatible media model${count === 1 ? '' : 's'} available in tool creation.` : 'No compatible media models were found for this account.', 'text-xs text-zinc-400'));
          if (provider.id === 'runway') body.append(node('p', 'Runway uses Orange’s curated model list. Model access is checked when generating.', 'text-xs text-zinc-500'));
        }
        const status = node('p', '', 'text-sm text-zinc-400'); status.setAttribute('role', 'status');
        if (options.expand === provider.id && options.message) status.textContent = options.message;
        const buttons = node('div', '', 'flex flex-wrap gap-2'); body.append(buttons, status);
        async function save(clearCredential = false) {
          const credential = key.value;
          key.value = '';
          await api(`/api/admin/providers/${provider.id}`, 'PUT', {enabled: enabled?.checked || false, ...(credential ? {apiKey: credential} : {}), clearCredential});
        }
        action(buttons, 'Save provider', async () => {
          try { await save(); await refreshProviders({expand: provider.id, message: 'Provider saved.'}); } catch (error) { status.textContent = error.message; }
        });
        action(buttons, 'Test connection', async () => {
          try {
            await save();
            status.textContent = 'Connecting and finding available models…';
            const result = await api(`/api/admin/providers/${provider.id}/test`, 'POST', {});
            await refreshProviders({expand: provider.id, message: result.detail});
          } catch (error) { status.textContent = error.message; }
        });
        action(buttons, 'Remove saved credential', async () => {
          try { await save(true); await refreshProviders(); } catch (error) { status.textContent = error.message; }
        });
      }
    } catch (error) { list.replaceChildren(node('p', error.message, 'text-sm text-red-400')); }
  }
  function editor() {
    let el = $('api-tool-editor');
    if (!el) {
      el = node('div', '', 'hidden space-y-5'); el.id = 'api-tool-editor';
      $('tool-editor-empty').parentElement.append(el);
    }
    $('tool-editor-empty').classList.add('hidden');
    $('tool-editor-form').classList.add('hidden');
    $('tool-editor-form').classList.remove('flex');
    el.classList.remove('hidden'); el.replaceChildren(); return el;
  }
  async function editTool(index = -1) {
    editIndex = index;
    if (!providers.length) await refreshProviders();
    const panel = editor();
    const original = index >= 0 ? appConfig.tools[index] : null;
    panel.append(node('h3', original ? 'Edit API Tool' : 'Create API Tool', 'text-lg font-medium text-zinc-100'));
    panel.append(node('p', 'Curate the choices people need. Model settings and credentials stay in Admin.', 'text-sm text-zinc-400'));
    const nextId = base => { let value = base, count = 2; while (appConfig.tools.some(t => t.id === value)) value = `${base}-${count++}`; return value; };
    const id = field(panel, 'Tool ID', 'text', original?.id || nextId('api-image'));
    const name = field(panel, 'Display name', 'text', original?.name || '');
    const providerInput = field(panel, 'Provider', 'select');
    providers.filter(p => p.supportsMedia).forEach(p => option(providerInput, p.id, providerNames[p.id] || p.id));
    providerInput.value = original?.provider || 'google';
    const modelInput = field(panel, 'Model', 'select');
    const controls = node('div', '', 'space-y-4'); panel.append(controls);
    const status = node('p', '', 'text-sm text-zinc-400'); status.setAttribute('role', 'status');
    const buttons = node('div', '', 'flex gap-2'); panel.append(buttons, status);
    let readControls;
    function showControls(useOriginal = false) {
      controls.replaceChildren();
      const provider = providers.find(p => p.id === providerInput.value);
      const model = provider.catalog.find(m => m.id === modelInput.value);
      if (!model) {
        readControls = null;
        controls.append(node('p', provider.discoveredAt ? 'No compatible media models were found for this account.' : 'Test the provider connection in General Settings → API Keys to find available models.', 'text-sm text-zinc-400'));
        return;
      }
      const saved = useOriginal ? original?.api : null;
      if (!provider.enabled || !provider.configured) controls.append(node('p', 'Configure and enable this provider in General Settings → API Keys before generating.', 'text-sm text-amber-400'));
      if (!provider.models.includes(model.id)) controls.append(node('p', 'This existing tool’s model was not found in the last connection test. Test the provider again to refresh availability.', 'text-sm text-amber-400'));
      const ratios = model.sourceAspect ? () => ['source'] : choices(controls, 'Aspect ratios', model.ratios, saved?.ratios?.includes('source') ? model.ratios : saved?.ratios || model.ratios);
      const ratioGroup = controls.querySelector('fieldset');
      const sourceNote = node('p', 'Output uses the reference image’s aspect ratio.', 'text-sm text-zinc-400');
      controls.append(sourceNote);
      const resolutions = choices(controls, 'Resolutions', model.resolutions, saved?.resolutions || [model.resolutions[0]]);
      const defaultResolution = field(controls, 'Default resolution', 'select');
      model.resolutions.forEach(r => option(defaultResolution, r)); defaultResolution.value = saved?.defaultResolution || model.resolutions[0];
      const references = field(controls, 'Reference images', 'select');
      for (let count = model.requiresImage ? 1 : 0; count <= model.references; count++) option(references, String(count), String(count));
      references.value = String(saved?.references ?? (model.referenceAspect ? 0 : Math.min(1, model.references)));
      if (!model.references) references.parentElement.classList.add('hidden');
      const required = field(controls, 'Image input', 'select');
      option(required, 'optional', 'Optional reference'); option(required, 'required', 'Required reference image');
      if (!model.references) required.parentElement.classList.add('hidden');
      required.value = (saved?.requireImage || model.requiresImage) ? 'required' : 'optional';
      function syncReferences() {
        const sourceAspect = model.sourceAspect || (model.referenceAspect && Number(references.value) > 0);
        if (model.referenceAspect && Number(references.value) > 0) required.value = 'required';
        required.disabled = model.requiresImage || model.referenceAspect || Number(references.value) === 0;
        if (ratioGroup) ratioGroup.classList.toggle('hidden', sourceAspect);
        sourceNote.classList.toggle('hidden', !sourceAspect);
      }
      references.addEventListener('change', syncReferences); syncReferences();
      const instructions = node('details'); instructions.append(node('summary', 'System prompt (optional)', 'cursor-pointer text-sm text-zinc-400'));
      const systemPrompt = node('textarea', '', fieldClass); systemPrompt.setAttribute('aria-label', 'System prompt'); systemPrompt.rows = 4; systemPrompt.maxLength = model.promptLimit || 10000;
      systemPrompt.value = saved?.systemPrompt || ''; instructions.append(systemPrompt);
      instructions.append(node('p', 'Instructions applied to every generation with this tool.', 'text-xs text-zinc-500')); controls.append(instructions);
      if (!original && /^api-(image|video)(-\d+)?$/.test(id.value)) id.value = nextId(`api-${model.output}`);
      let durations, defaultDuration;
      if (model.output === 'video') {
        durations = choices(controls, 'Video duration (seconds)', model.durations, saved?.durations || model.durations);
        defaultDuration = field(controls, 'Default duration', 'select');
        model.durations.forEach(d => option(defaultDuration, String(d), `${d} seconds`)); defaultDuration.value = String(saved?.defaultDuration || (model.durations.includes(10) ? 10 : model.durations[0]));
      }
      readControls = () => ({provider: provider.id, model: model.id, outputType: model.output,
        api: {ratios: model.sourceAspect || (model.referenceAspect && Number(references.value) > 0) ? ['source'] : ratios(), resolutions: resolutions(), defaultResolution: defaultResolution.value,
          references: Number(references.value), requireImage: Number(references.value) > 0 && required.value === 'required', systemPrompt: systemPrompt.value.trim(),
          ...(durations ? {durations: durations(), defaultDuration: Number(defaultDuration.value)} : {})}});
    }
    function showModels(useOriginal = false) {
      modelInput.replaceChildren();
      const provider = providers.find(p => p.id === providerInput.value);
      provider.catalog.filter(m => provider.models.includes(m.id) || (useOriginal && original?.provider === provider.id && original.model === m.id)).forEach(m => option(modelInput, m.id, m.name));
      if (!modelInput.children.length) option(modelInput, '', 'No available models — test provider connection');
      if (useOriginal && original) modelInput.value = original.model;
      showControls(useOriginal);
    }
    providerInput.addEventListener('change', () => showModels());
    modelInput.addEventListener('change', () => showControls());
    showModels(true);
    async function persist(tools) {
      await api('/api/admin/config', 'POST', {...appConfig, tools});
      appConfig.tools = tools; editingToolIndex = -1; renderToolsList();
      panel.classList.add('hidden'); $('tool-editor-empty').classList.remove('hidden');
    }
    action(buttons, 'Save tool', async () => {
      try {
        if (!readControls) throw new Error('Choose a supported model.');
        const tool = {...(original || {}), id: id.value.trim(), name: name.value.trim(), ...readControls()};
        const tools = [...appConfig.tools];
        if (editIndex >= 0) tools[editIndex] = tool; else tools.push(tool);
        await persist(tools);
      } catch (error) { status.textContent = error.message; }
    });
    if (original) action(buttons, 'Delete tool', async () => {
      try { await persist(appConfig.tools.filter((_, i) => i !== editIndex)); } catch (error) { status.textContent = error.message; }
    });
  }
  window.OrangeMediaAdmin = {refreshProviders, editTool};
  $('add-api-tool-btn')?.addEventListener('click', () => editTool());
  $('logout-btn')?.addEventListener('click', () => {
    providers = []; $('api-providers-list')?.replaceChildren(); $('api-tool-editor')?.replaceChildren();
  });
})();
