(() => {
  function initialize() {
    const form = document.getElementById('tool-editor-form');
    if (!form) return;
    form.classList.add('tool-config');
    const make = (tag, text, className = '') => {
      const node = document.createElement(tag); node.textContent = text; node.className = className; return node;
    };
    const header = document.getElementById('tool-editor-title').parentElement;
    const title = document.getElementById('tool-editor-title');
    const subheading = make('p', 'Define what this tool does, connect its inputs, then check compatibility.', 'tool-config-subtitle');
    const titleGroup = make('div', ''); title.replaceWith(titleGroup); titleGroup.append(title, subheading);
    const navigation = make('div', '', 'tool-config-tabs'); navigation.setAttribute('role', 'tablist'); navigation.setAttribute('aria-label', 'Tool configuration');
    header.insertAdjacentElement('afterend', navigation);
    const panels = new Map(); let activeTab = 'overview';
    for (const [id, label] of [['overview', 'Overview'], ['inputs', 'Inputs & workflow'], ['check', 'Check & save']]) {
      const panel = make('section', '', 'tool-config-panel'); panel.id = `tool-config-${id}`; panel.setAttribute('role', 'tabpanel'); panel.setAttribute('aria-labelledby', `tool-config-tab-${id}`);
      form.append(panel); panels.set(id, panel);
      const tab = make('button', label); tab.type = 'button'; tab.id = `tool-config-tab-${id}`; tab.setAttribute('role', 'tab'); tab.setAttribute('aria-controls', panel.id);
      tab.addEventListener('click', () => show(id)); navigation.append(tab);
    }
    function show(id) {
      activeTab = id;
      for (const [name, panel] of panels) panel.hidden = name !== id;
      for (const tab of navigation.children) {
        const selected = tab.id === `tool-config-tab-${id}`;
        tab.setAttribute('aria-selected', String(selected)); tab.tabIndex = selected ? 0 : -1;
      }
    }
    navigation.addEventListener('keydown', event => {
      const ids = [...panels.keys()]; let index = ids.indexOf(activeTab);
      if (event.key === 'ArrowRight') index = (index + 1) % ids.length;
      else if (event.key === 'ArrowLeft') index = (index + ids.length - 1) % ids.length;
      else if (event.key === 'Home') index = 0;
      else if (event.key === 'End') index = ids.length - 1;
      else return;
      event.preventDefault(); show(ids[index]); navigation.children[index].focus();
    });
    const intro = (parent, heading, copy) => { parent.append(make('h4', heading, 'tool-config-heading'), make('p', copy, 'tool-config-description')); };
    const overview = panels.get('overview'), inputs = panels.get('inputs'), check = panels.get('check');
    intro(overview, 'What are you making?', 'Give the tool a recognizable name and select its result type.');
    const identity = document.getElementById('edit-tool-name').parentElement.parentElement;
    const identifier = document.getElementById('edit-tool-id').parentElement;
    identity.className = 'tool-config-identity';
    overview.append(identity);
    const nameField = document.getElementById('edit-tool-name').parentElement;
    identifier.classList.add('tool-config-identifier'); nameField.append(identifier);
    const preview = make('div', '', 'tool-config-preview'); overview.append(preview);
    const enhancement = document.getElementById('tool-llm-overrides-container');
    if (enhancement) {
      const wrapper = make('section', '', 'tool-config-open-section'); wrapper.append(enhancement); overview.append(wrapper);
    }
    intro(inputs, 'Connect the workflow', 'Select the workflow, decide which images users provide, and connect only the inputs this tool needs.');
    const workflowFile = document.getElementById('edit-tool-file').parentElement; inputs.append(workflowFile);
    const mappings = document.getElementById('node-mappings-container'); const mappingSection = mappings.parentElement;
    inputs.append(mappingSection);
    mappingSection.insertBefore(workflowFile, mappings);
    const assets = document.getElementById('workflow-assets-panel');
    if (assets) {
      const wrapper = make('section', '', 'tool-config-open-section'); wrapper.append(assets); inputs.append(wrapper);
    }
    intro(check, 'Ready to use?', 'Check the workflow against your connected backends. Optional-image tools are checked in both modes.');
    const preflight = document.getElementById('workflow-preflight-panel'); if (preflight) check.append(preflight);
    const checkHelp = make('div', 'Save publishes these settings to the generator. You can return to any section without losing your edits.', 'tool-config-note'); check.append(checkHelp);
    const footer = document.getElementById('save-tool-btn').parentElement.parentElement;
    footer.classList.add('tool-config-footer'); form.append(footer);
    const status = make('span', 'No unsaved changes', 'tool-config-dirty'); footer.prepend(status);
    function updatePreview() {
      title.textContent = document.getElementById('edit-tool-name').value.trim() || 'New tool';
      preview.replaceChildren(make('div', 'GENERATOR PREVIEW', 'tool-config-eyebrow'));
      preview.append(make('h5', title.textContent));
      const snapshot = window.ToolInputEditor?.summary?.(); const mapping = snapshot?.mapping || {};
      if (enhancement) enhancement.parentElement.hidden = !mapping.prompt;
      const output = document.getElementById('edit-tool-output-type').value;
      preview.append(make('p', `Creates ${output === 'audio' ? 'audio' : output === 'video' ? 'video' : 'images'}`, 'tool-config-description'));
      if (mapping.prompt) { const field = make('div', 'Describe what you want to create…', 'tool-config-preview-prompt'); preview.append(field); }
      const uploads = make('div', '', 'tool-config-preview-uploads');
      if (mapping.image) uploads.append(make('div', 'Source image · required'));
      if (snapshot?.mode === 'imageVariant') uploads.append(make('div', 'First image / frame · optional'));
      if (mapping.image2) uploads.append(make('div', 'Second image · required'));
      if (snapshot?.mode === 'referenceVariant') uploads.append(make('div', 'Reference image · optional'));
      if (uploads.childElementCount) preview.append(uploads);
      const chips = make('div', '', 'tool-config-preview-chips');
      if (mapping.width && mapping.height) for (const ratio of snapshot.ratios) chips.append(make('span', ratio));
      if (snapshot?.duration) chips.append(make('span', `${snapshot.duration.join(' / ')} seconds`));
      if (chips.childElementCount) preview.append(chips);
      if (!mapping.prompt && !uploads.childElementCount) preview.append(make('p', 'Add the inputs this tool needs in Inputs & workflow.', 'tool-config-description'));
    }
    function decorateMappings() {
      const options = document.getElementById('tool-input-options');
      if (options && options.parentElement !== inputs) mappingSection.insertAdjacentElement('beforebegin', options);
      updatePreview();
    }
    let scheduled = false;
    new MutationObserver(() => {
      if (scheduled) return; scheduled = true;
      queueMicrotask(() => { scheduled = false; decorateMappings(); });
    }).observe(mappings, {childList: true, subtree: true});
    function markDirty(event) {
      // Backend bindings save independently; they are not part of Save Tool.
      if (event.target.closest('#workflow-preflight-panel')) return;
      status.textContent = 'Unsaved changes'; updatePreview();
    }
    form.addEventListener('input', markDirty);
    form.addEventListener('change', markDirty);
    new MutationObserver(() => { if (!document.getElementById('save-status').classList.contains('hidden')) status.textContent = 'All changes saved'; }).observe(document.getElementById('save-status'), {attributes: true});
    const originalSelect = window.selectTool;
    window.selectTool = async function (...args) {
      await originalSelect.apply(this, args); show('overview'); status.textContent = 'No unsaved changes'; decorateMappings();
    };
    decorateMappings(); show('overview');
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initialize, {once: true});
  else initialize();
})();
