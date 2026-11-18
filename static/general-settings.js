/* Keep the existing controls and save handler; group them into focused panels. */
(() => {
  const $ = id => document.getElementById(id);
  function initialize() {
    const sections = $('general-settings-sections');
    if (!sections) return;
    const navigation = document.createElement('div');
    navigation.className = 'tool-config-tabs mb-6 flex-wrap';
    navigation.setAttribute('role', 'tablist'); navigation.setAttribute('aria-label', 'General settings sections');
    sections.before(navigation);
    const groups = [
      ['generation', 'Generation', []],
      ['backends', 'Backends', ['comfy-servers-container', 'backend-health-panel', 'managed-comfyui-card']],
      ['enhancement', 'Prompt Enhancement', ['setting-llm-enabled']],
      ['keys', 'API Keys', ['setting-hf-token', 'api-providers-section']],
      ['system', 'System', ['setting-admin-key', 'backup-db-btn', 'check-update-btn']],
    ];
    const panels = new Map();
    const children = [...sections.children];
    let active = 'generation';
    for (const [id, title] of groups) {
      const panel = document.createElement('section'); panel.id = `settings-panel-${id}`; panel.className = 'space-y-6';
      panel.setAttribute('role', 'tabpanel'); panel.setAttribute('aria-labelledby', `settings-tab-${id}`);
      sections.append(panel); panels.set(id, panel);
      const button = document.createElement('button'); button.type = 'button'; button.textContent = title;
      button.id = `settings-tab-${id}`; button.setAttribute('role', 'tab'); button.setAttribute('aria-controls', panel.id);
      button.addEventListener('click', () => show(id)); navigation.append(button);
    }
    for (const child of children) {
      const group = groups.find(([, , ids]) => ids.some(id => child.id === id || child.querySelector(`#${id}`))) || groups[0];
      panels.get(group[0]).append(child);
      // Each panel starts cleanly instead of inheriting separators from a long page.
      child.classList.remove('border-t', 'pt-4');
    }
    const hf = $('setting-hf-token')?.closest('.space-y-3');
    if (hf) {
      const details = document.createElement('details'); details.className = 'bg-zinc-950/50 border border-zinc-800 rounded-xl p-4';
      const summary = document.createElement('summary'); summary.textContent = 'Hugging Face'; summary.className = 'cursor-pointer text-sm font-medium text-zinc-100';
      hf.before(details); details.append(summary, hf); hf.classList.add('pt-4');
    }
    const modelProviders = document.createElement('section'); modelProviders.id = 'model-providers-section'; modelProviders.className = 'space-y-3';
    const heading = document.createElement('h3'); heading.textContent = 'Model Providers'; heading.className = 'text-sm font-semibold text-zinc-300';
    const help = document.createElement('p'); help.textContent = 'Keys for model downloads from Hugging Face and Civitai.'; help.className = 'text-xs text-zinc-500';
    modelProviders.append(heading, help);
    for (const id of ['setting-hf-token', 'civitai-api-key']) {
      const card = $(id)?.closest('details'); if (card) modelProviders.append(card);
    }
    panels.get('keys').append(modelProviders);
    function show(id) {
      active = id;
      for (const [name, panel] of panels) panel.hidden = name !== id;
      for (const button of navigation.children) {
        const selected = button.id === `settings-tab-${id}`;
        button.setAttribute('aria-selected', String(selected)); button.tabIndex = selected ? 0 : -1;
      }
    }
    navigation.addEventListener('keydown', event => {
      const ids = [...panels.keys()]; let index = ids.indexOf(active);
      if (event.key === 'ArrowRight') index = (index + 1) % ids.length;
      else if (event.key === 'ArrowLeft') index = (index + ids.length - 1) % ids.length;
      else if (event.key === 'Home') index = 0;
      else if (event.key === 'End') index = ids.length - 1;
      else return;
      event.preventDefault(); show(ids[index]); navigation.children[index].focus();
    });
    show(active);
  }
  async function request(method, body, suffix = '') {
    const response = await adminFetch('/api/admin/credentials/civitai' + suffix, {method, headers: {'Content-Type': 'application/json'}, ...(body ? {body: JSON.stringify(body)} : {})});
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Could not update Civitai credential.');
    return data;
  }
  async function refresh() {
    try {
      const status = await request('GET');
      $('civitai-api-key').placeholder = status.configured ? '••••••••••••••••' : 'Enter API credential';
      $('civitai-key-status').textContent = status.configured ? `Credential configured (${status.source}).` : 'No credential configured.';
    } catch (error) { $('civitai-key-status').textContent = error.message; }
  }
  async function act(method, test = false) {
    try {
      const input = $('civitai-api-key'); const key = input.value; input.value = '';
      if (method === 'DELETE') await request('DELETE');
      else if (key) await request('PUT', {apiKey: key});
      else if (!test) throw new Error('Enter a Civitai API key.');
      await refresh();
      if (test) { await request('POST', null, '/test'); $('civitai-key-status').textContent = 'Connected to Civitai.'; }
    } catch (error) { $('civitai-key-status').textContent = error.message; }
  }
  $('save-civitai-key')?.addEventListener('click', () => act('PUT'));
  $('test-civitai-key')?.addEventListener('click', () => act('PUT', true));
  $('remove-civitai-key')?.addEventListener('click', () => act('DELETE'));
  window.OrangeCredentials = {refresh};
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initialize, {once: true}); else initialize();
})();
