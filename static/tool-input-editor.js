(() => {
  let drafts, switcher, loadVersion = 0;
  const fields = ['prompt', 'image', 'image2', 'width', 'height', 'seed', 'duration', 'outputText'];
  const host = document.createElement('section');
  host.id = 'tool-input-options';
  host.className = 'space-y-4 border border-zinc-800 rounded-xl p-4';
  const inputClass = 'w-full bg-zinc-950 border border-zinc-700 rounded-lg p-2 text-xs text-zinc-200';
  function el(tag, text, className) {
    const node = document.createElement(tag);
    if (text) node.textContent = text;
    if (className) node.className = className;
    return node;
  }
  function input(parent, label, id, value = '', type = 'text') {
    const wrap = el('label', label, 'block text-xs text-zinc-400 space-y-1');
    const node = el('input', '', inputClass);
    node.id = id; node.type = type; node.value = value;
    if (type === 'checkbox') { node.checked = Boolean(value); node.className = 'ml-2'; }
    wrap.append(node); parent.append(wrap); return node;
  }
  function selectInput(parent, label, id, choices, value) {
    const wrap = el('label', label, 'block text-xs text-zinc-400 space-y-1');
    const node = el('select', '', inputClass); node.id = id;
    if (!choices.some(([key]) => String(key) === String(value))) choices.push([value, String(value)]);
    for (const [key, title] of choices) { const option = el('option', title); option.value = key; node.append(option); }
    node.value = value; wrap.append(node); parent.append(wrap); return node;
  }
  function button(parent, label, action) {
    const node = el('button', label, 'text-xs text-orange-300 border border-zinc-700 rounded-lg px-3 py-2');
    node.type = 'button'; node.addEventListener('click', action); parent.append(node); return node;
  }
  function value(id) { return document.getElementById(id).value.trim(); }
  function number(id) {
    const result = Number(value(id));
    if (!Number.isInteger(result) || result <= 0) throw Error('Video timing, dimensions and output scale must be positive whole numbers.');
    return result;
  }
  function baseMappings(context = 'base') {
    const prefix = context === 'alternate' ? 'alt-' : '';
    const mapping = {};
    for (const key of fields) {
      if (key === 'width' || key === 'height') continue;
      if (!document.getElementById(`${prefix}map-${key}-enable`)?.checked) continue;
      const nodeId = document.getElementById(`${prefix}map-${key}-node`).value.trim();
      const field = document.getElementById(`${prefix}map-${key}-field`).value.trim();
      mapping[key] = {nodeId, field};
      if (key === 'seed' && mapping[key]) mapping[key].generateRandom = document.getElementById(prefix + 'map-seed-rand').checked;
    }
    if (document.getElementById(prefix + 'map-resolution-enable')?.checked) {
      for (const key of ['width', 'height']) mapping[key] = {
        nodeId: document.getElementById(prefix + 'map-resolution-node').value.trim(),
        field: document.getElementById(key === 'width' ? prefix + 'map-res-wfield' : prefix + 'map-res-hfield').value.trim(),
      };
    }
    return mapping;
  }
  function flushMappings() {
    if (drafts) { drafts.base = baseMappings('base'); if (document.getElementById('alternate-node-mappings')?.childElementCount) drafts.alternate = baseMappings('alternate'); }
  }
  async function showContext(context) {
    const prefix = context === 'alternate' ? 'alt-' : '';
    if (context === 'base') for (const id of ['tool-timing-settings', 'tool-resolution-settings']) { const panel = document.getElementById(id); if (panel) host.append(panel); }
    renderMappings(drafts[context], context);
    document.getElementById("tool-llm-overrides-container")?.classList.toggle("hidden", !drafts.base.prompt);
    placeSettings();
    for (const key of ['prompt','image','image2','resolution','seed','duration','outputText']) document.getElementById(`${prefix}map-${key}-enable`)?.addEventListener('change', () => { flushMappings(); showContext(context); });
    const version = loadVersion;
    const filename = context === 'base' ? document.getElementById('edit-tool-file').value : document.getElementById('tool-alternate-file').value;
    try {
      const response = await adminFetch(`/api/admin/workflows/${encodeURIComponent(filename)}`);
      if (!response.ok) { placeSettings(); return; }
      const graph = await response.json();
      if (version !== loadVersion) return;
      function dropdown(id, choices, change) {
        const old = document.getElementById(id);
        if (!old) return;
        const value = old.value;
        const select = document.createElement('select');
        select.id = old.id; select.className = old.className; select.disabled = old.disabled;
        if (value && !choices.some(([key]) => key === value)) choices.push([value, value]);
        for (const [key, title] of choices) { const option = el('option', title); option.value = key; select.append(option); }
        select.value = value;
        select.addEventListener('change', change || (() => {})); old.replaceWith(select);
      }
      function fieldOptions(nodeId) { return [['', 'Select input…'], ...Object.keys(graph[nodeId]?.inputs || {}).map(name => [name, name])]; }
      for (const key of ['prompt', 'image', 'image2', 'resolution', 'seed', 'duration', 'outputText']) {
        const nodeId = `${prefix}map-${key}-node`;
        const updateFields = () => {
          const node = document.getElementById(nodeId);
          if (!node) return;
          for (const fieldId of key === 'resolution' ? [prefix + 'map-res-wfield', prefix + 'map-res-hfield'] : [`${prefix}map-${key}-field`]) dropdown(fieldId, fieldOptions(node.value));
        };
        dropdown(nodeId, [['', 'Select workflow node…'], ...Object.entries(graph).map(([id, n]) => [id, `${n._meta?.title || n.class_type} · ${id}`])], updateFields);
        updateFields();
      }
    } catch (_) { /* Saved mappings remain editable if the workflow is unavailable. */ }
    placeSettings();
  }
  function placeSettings() {
    const resolution = document.getElementById('map-resolution-container');
    const duration = document.getElementById('map-duration-container');
    const timing = document.getElementById('tool-timing-settings');
    const output = document.getElementById('tool-resolution-settings');
    if (timing && duration) duration.append(timing);
    else if (timing) { host.append(timing); timing.hidden = true; }
    if (output && resolution) resolution.append(output);
    else if (output) { host.append(output); output.hidden = true; }
    if (timing) timing.hidden = !duration || document.getElementById('edit-tool-output-type')?.value !== 'video';
    if (output) output.hidden = !resolution;
  }
  function ratioRow(name = '', width = '', height = '') {
    const row = el('div', '', 'grid grid-cols-4 gap-2 items-end');
    row.dataset.ratioRow = 'true';
    input(row, 'Ratio label', '', name); input(row, 'Width', '', width, 'number'); input(row, 'Height', '', height, 'number');
    button(row, 'Remove', () => row.remove());
    document.getElementById('tool-ratio-rows').append(row);
  }
  function load(tool, files, globalRatios) {
    for (const id of ["tool-timing-settings", "tool-resolution-settings"]) document.getElementById(id)?.remove();
    host.replaceChildren();
    drafts = {base: structuredClone(tool.nodeMapping || {}), alternate: structuredClone((tool.referenceVariant || tool.imageVariant || {}).nodeMapping || {})};
    switcher?.remove();
    loadVersion += 1;
    switcher = el('section', '', 'tool-workflow-section'); switcher.id = 'tool-workflow-alternate';
    const alternateHeading = el('h4', '', 'tool-config-heading');
    const alternateHelp = el('p', '', 'tool-config-description');
    const alternateMappings = el('div', '', 'space-y-3'); alternateMappings.id = 'alternate-node-mappings';
    switcher.append(alternateHeading, alternateHelp, alternateMappings);
    document.getElementById('node-mappings-container').parentElement.insertAdjacentElement('afterend', switcher);
    const baseHeading = document.getElementById('node-mappings-container').parentElement.querySelector('h4');
    document.getElementById('node-mappings-container').parentElement.insertAdjacentElement('beforebegin', host);
    host.append(el('h4', 'Workflow inputs', 'text-sm font-semibold text-zinc-200'));
    host.append(el('p', 'Both workflows stay enabled. Orange picks the matching workflow automatically from the images uploaded in the generator.', 'text-xs text-zinc-500'));
    const modeLabel = el('label', 'Images users can upload', 'block text-xs text-zinc-400');
    const mode = el('select', '', inputClass); mode.id = 'tool-input-mode';
    for (const [id, label] of [['', 'No optional image'], ['imageVariant', 'Optional first frame / source image — both workflows enabled'], ['referenceVariant', 'Required source + optional reference — both workflows enabled']]) {
      const option = el('option', label); option.value = id; mode.append(option);
    }
    mode.value = tool.referenceVariant ? 'referenceVariant' : tool.imageVariant ? 'imageVariant' : '';
    modeLabel.append(mode); host.append(modeLabel);
    const alternate = el('div', '', 'space-y-3'); alternate.id = 'tool-alternate-panel'; host.append(alternate);
    const variant = tool[mode.value] || {};
    const file = selectInput(alternate, 'Workflow with optional image', 'tool-alternate-file', [['', 'Select workflow…'], ...files.map(name => [name, name])], variant.workflowFile || '');
    file.setAttribute('list', 'tool-workflow-files');
    const datalist = el('datalist'); datalist.id = 'tool-workflow-files';
    for (const name of files) { const option = el('option'); option.value = name; datalist.append(option); }
    host.append(datalist);
    const upload = input(alternate, 'Upload alternate API workflow', 'tool-alternate-upload', '', 'file'); upload.accept = '.json';
    const uploadStatus = el('p', '', 'text-xs text-zinc-400'); alternate.append(uploadStatus);
    upload.addEventListener('change', async () => {
      if (!upload.files[0]) return;
      const data = new FormData(); data.append('file', upload.files[0]); upload.disabled = true;
      try {
        const response = await adminFetch('/api/admin/workflows/upload', {method: 'POST', body: data});
        const result = await response.json();
        if (!response.ok) throw Error(result.detail || 'Upload failed');
        const filename = result.filename || upload.files[0].name;
        if (![...file.options].some(option => option.value === filename)) { const option = el('option', filename); option.value = filename; file.append(option); }
        file.value = filename;
        uploadStatus.textContent = 'Uploaded. Map the alternate workflow below.';
        file.dispatchEvent(new Event('change', {bubbles: true}));
      } catch (error) { uploadStatus.textContent = error.message; }
      finally { upload.disabled = false; }
    });

    const updateMode = () => {
      const reference = mode.value === 'referenceVariant';
      switcher.hidden = !mode.value;
      alternate.hidden = !mode.value;
      if (mode.value) {
        alternateHeading.textContent = reference ? '2. Source + reference image' : '2. With a first-frame image';
        alternateHelp.textContent = reference ? 'Runs automatically when a second reference image is uploaded. Map both images below.' : 'Runs automatically when a first-frame image is uploaded. Its image input is mapped below.';
        if (baseHeading) baseHeading.textContent = reference ? '1. Source image only' : '1. Without an image';
        switcher.insertBefore(alternate, alternateMappings);
        showContext('alternate');
      } else if (baseHeading) baseHeading.textContent = 'Node Mappings';
    };
    mode.addEventListener('change', () => {
      flushMappings();
      if (mode.value && !Object.keys(drafts.alternate).length) { drafts.alternate = structuredClone(drafts.base); drafts.alternate[mode.value === 'referenceVariant' ? 'image2' : 'image'] = {nodeId:'',field:'image'}; }
      updateMode();
    }); updateMode();
    const timing = el('div', '', 'space-y-3 border-t border-zinc-800 pt-3'); timing.id = 'tool-timing-settings'; host.append(timing);
    input(timing, 'Offer video length choices', 'tool-duration-enabled', Boolean(tool.duration), 'checkbox');
    const durationFields = el('div', '', 'grid grid-cols-2 gap-3'); timing.append(durationFields);
    const lengths = input(durationFields, 'Available lengths (seconds)', 'tool-duration-options', tool.duration?.options?.join(', ') || '2, 4, 6, 8');
    lengths.addEventListener('change', () => { const select = document.getElementById('tool-duration-default'); const previous = select.value; select.replaceChildren(); for (const n of lengths.value.split(',').map(s => Number(s.trim())).filter(n => Number.isInteger(n) && n > 0)) { const option = el('option', `${n} seconds`); option.value = n; select.append(option); } select.value = previous; });
    selectInput(durationFields, 'Default length', 'tool-duration-default', (tool.duration?.options || [2, 4, 6, 8]).map(n => [n, `${n} seconds`]), tool.duration?.default || 4);
    selectInput(durationFields, 'Frame rate', 'tool-duration-fps', [24, 25, 30, 48, 50, 60].map(n => [n, `${n} fps`]), tool.duration?.frameRate || 24);
    input(durationFields, 'Frame multiple (frames = multiple × n + 1)', 'tool-duration-multiple', tool.duration?.frameMultiple || 8, 'number');
    const updateTiming = () => { durationFields.hidden = !document.getElementById('tool-duration-enabled').checked; };
    document.getElementById('tool-duration-enabled').addEventListener('change', updateTiming); updateTiming();
    const output = el('div', '', 'space-y-3 border-t border-zinc-800 pt-3'); output.id = 'tool-resolution-settings'; host.append(output);
    selectInput(output, 'Workflow output scaling', 'tool-output-scale', [[1, 'No upscale'], [2, '2× width and height'], [4, '4× width and height']], tool.outputScale || 1);
    input(output, 'Use tool-specific aspect ratios', 'tool-ratios-enabled', Boolean(tool.aspectRatios), 'checkbox');
    const ratios = el('div', '', 'space-y-2'); output.append(ratios);
    const rows = el('div', '', 'space-y-2'); rows.id = 'tool-ratio-rows'; ratios.append(rows);
    for (const [name, size] of Object.entries(tool.aspectRatios || globalRatios || {})) ratioRow(name, size.width, size.height);
    button(ratios, 'Add ratio', () => ratioRow());
    const updateRatios = () => { ratios.hidden = !document.getElementById('tool-ratios-enabled').checked; };
    document.getElementById('tool-ratios-enabled').addEventListener('change', updateRatios); updateRatios();
    file.addEventListener('change', () => { flushMappings(); showContext('alternate'); });
    showContext('base');
  }
  function apply(tool) {
    flushMappings();
    tool.nodeMapping = structuredClone(drafts.base);
    for (const map of [drafts.base, ...(value("tool-input-mode") ? [drafts.alternate] : [])]) for (const [key, slot] of Object.entries(map)) if (!slot.nodeId || !slot.field) throw Error(`${key} needs a workflow node and input.`);
    delete tool.imageVariant; delete tool.referenceVariant; delete tool.duration; delete tool.aspectRatios; delete tool.outputScale;
    tool.workflowFile = value('edit-tool-file');
    const mode = value('tool-input-mode');
    if (mode) {
      const mapping = structuredClone(drafts.alternate);
      if (!value('tool-alternate-file') || !mapping.image) throw Error('The alternate workflow needs a file and an Image mapping.');
      if (mode === 'referenceVariant' && (!tool.nodeMapping.image || tool.nodeMapping.image2 || !mapping.image2)) throw Error('Optional reference needs Image in the base workflow and both Image and Image 2 in the alternate.');
      if (mode === 'imageVariant' && tool.nodeMapping.image) throw Error('For an optional first image, leave Image unmapped in the base workflow.');

      tool[mode] = {workflowFile: value('tool-alternate-file'), nodeMapping: mapping};
    }
    if (document.getElementById('tool-duration-enabled').checked) {
      const options = value('tool-duration-options').split(',').map(s => Number(s.trim()));
      const defaultLength = number('tool-duration-default');
      if (tool.outputType !== 'video' || !tool.nodeMapping.duration || !options.length || options.some(n => !Number.isInteger(n) || n <= 0) || !options.includes(defaultLength)) throw Error('Video length choices need video output, a Duration mapping, positive whole seconds, and a default in the list.');
      if (mode && !tool[mode].nodeMapping.duration) throw Error('Map Duration in the alternate workflow too.');
      tool.duration = {options, default: defaultLength, frameRate: number('tool-duration-fps'), frameMultiple: number('tool-duration-multiple')};
    }
    const scale = number('tool-output-scale'); if (scale !== 1) tool.outputScale = scale;
    if (document.getElementById('tool-ratios-enabled').checked) {
      tool.aspectRatios = {};
      for (const row of document.querySelectorAll('[data-ratio-row]')) {
        const [label, width, height] = row.querySelectorAll('input');
        const w = Number(width.value), h = Number(height.value), name = label.value.trim();
        if (!name || !Number.isInteger(w) || w <= 0 || !Number.isInteger(h) || h <= 0 || Object.hasOwn(tool.aspectRatios, name)) throw Error('Aspect ratios need unique labels and positive whole-number dimensions.');
        Object.defineProperty(tool.aspectRatios, name, {value: {width: w, height: h}, enumerable: true, configurable: true});
      }
      if (!Object.keys(tool.aspectRatios).length) throw Error('Add at least one aspect ratio or disable the override.');
    }
    return tool;
  }
  document.getElementById('edit-tool-output-type')?.addEventListener('change', placeSettings);
  document.getElementById('edit-tool-file')?.addEventListener('change', () => { if (drafts) { flushMappings(); showContext('base'); } });
  window.ToolInputEditor = {load, apply, summary: () => { flushMappings(); return {mapping: structuredClone(drafts?.base || {}), mode: document.getElementById('tool-input-mode')?.value || '', ratios: document.getElementById('tool-ratios-enabled')?.checked ? [...document.querySelectorAll('[data-ratio-row]')].map(row => row.querySelector('input')?.value || '') : Object.keys(typeof appConfig !== 'undefined' ? appConfig?.aspectRatios || {} : {}), duration: document.getElementById('tool-duration-enabled')?.checked ? (document.getElementById('tool-duration-options')?.value || '').split(',').map(s => s.trim()) : null}; }, currentMapping: baseMappings, refreshMappings: (context = 'base') => { flushMappings(); showContext(context); }};
})();
