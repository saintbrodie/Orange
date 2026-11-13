(() => {
    function element(tag, classes, text) {
        const node = document.createElement(tag);
        node.className = classes;
        if (text != null) node.textContent = text;
        return node;
    }

    function render(parent, backendUrl, workflowFile, models, onSaved) {
        if (!models?.length) return;
        const section = element('div', 'space-y-3 border-t border-zinc-800 pt-3');
        section.appendChild(element('h5', 'text-xs font-semibold text-zinc-300', 'Model locations'));
        section.appendChild(element('p', 'text-xs text-zinc-500', 'Orange resolves these filenames for this backend. Saved bindings apply to this backend across tools; workflow files stay unchanged.'));
        // Shared loaders can reference the same logical model more than once.
        const seen = new Set();
        for (const model of models) {
            const identity = JSON.stringify([model.category, model.filename]);
            if (seen.has(identity)) continue;
            seen.add(identity);
            const row = element('div', 'space-y-2 min-w-0');
            row.appendChild(element('div', 'text-xs text-zinc-300 break-all', `${model.filename} · ${model.category}`));
            if (!model.options.length) {
                row.appendChild(element('p', 'text-xs text-amber-300', 'Missing from this loader’s model inventory. Add the exact model, then scan again.'));
                section.appendChild(row);
                continue;
            }
            if (model.options.length === 1 && !model.binding) {
                row.appendChild(element('p', 'text-xs text-emerald-400 break-all', `Automatic → ${model.resolved || model.options[0]}`));
                section.appendChild(row);
                continue;
            }
            const controls = element('div', 'flex flex-col sm:flex-row gap-2 min-w-0');
            const select = element('select', 'min-w-0 w-full bg-zinc-950 border border-zinc-700 rounded-lg px-3 py-2 text-xs text-zinc-200');
            select.setAttribute('aria-label', `Backend path for ${model.filename}`);
            select.appendChild(new Option(model.resolved ? `Automatic (workflow path or unique filename)` : 'Select a path for this backend…', ''));
            model.options.forEach(path => select.appendChild(new Option(path, path)));
            select.value = model.reason === 'binding' ? model.resolved : '';
            const save = element('button', 'shrink-0 bg-zinc-800 hover:bg-zinc-700 border border-zinc-700 text-orange-400 rounded-lg px-3 py-2 text-xs', 'Save model binding');
            save.type = 'button';
            const updateSave = () => { save.disabled = !select.value && !model.binding; };
            select.addEventListener('change', updateSave);
            updateSave();
            const message = element('p', 'text-xs text-zinc-500 break-all');
            message.setAttribute('aria-live', 'polite');
            message.textContent = model.stale_binding
                ? `Saved path is no longer available: ${model.binding}. ${model.resolved ? `Automatically resolved to ${model.resolved}.` : 'Select its new location.'}`
                : model.reason === 'binding' ? `Saved for this backend → ${model.resolved}`
                : model.resolved ? `Using workflow path → ${model.resolved}` : 'Several files share this name. Orange needs your choice.';
            save.addEventListener('click', async () => {
                save.disabled = true;
                select.disabled = true;
                try {
                    const response = await adminFetch('/api/admin/workflows/model-binding', {
                        method: 'POST', headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({backendUrl, workflowFile, nodeId: model.node_id,
                            field: model.field, filename: model.filename, path: select.value || null}),
                    });
                    const data = await response.json();
                    if (!response.ok) throw new Error(data.detail || 'Could not save model binding');
                    message.textContent = select.value ? 'Model binding saved for this backend.' : 'Saved binding removed. Orange will resolve automatically.';
                    await onSaved?.();
                } catch (error) {
                    message.textContent = error.message || 'Could not save model binding';
                } finally {
                    select.disabled = false;
                    updateSave();
                }
            });
            controls.append(select, save);
            row.append(controls, message);
            section.appendChild(row);
        }
        parent.appendChild(section);
    }

    window.ModelBindings = {render};
})();
