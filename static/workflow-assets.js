(() => {
    const workflowField = document.getElementById('edit-tool-file');
    if (!workflowField || !workflowField.parentElement) return;

    const panel = document.createElement('div');
    panel.id = 'workflow-assets-panel';
    panel.className = 'space-y-3 bg-zinc-950/40 border border-zinc-800 rounded-xl p-4';

    const header = document.createElement('div');
    header.className = 'flex flex-col sm:flex-row sm:items-start justify-between gap-3';

    const titleWrap = document.createElement('div');
    const title = document.createElement('h4');
    title.className = 'text-sm font-medium text-zinc-300 flex items-center gap-2';
    const icon = document.createElement('i');
    icon.setAttribute('data-lucide', 'images');
    icon.className = 'w-4 h-4 text-orange-500';
    title.append(icon, document.createTextNode(' Workflow Assets'));

    const help = document.createElement('p');
    help.className = 'text-xs text-zinc-500 mt-1 max-w-xl leading-relaxed';
    help.textContent = 'Fixed images that are part of this workflow. Keep the same filename in an unmapped workflow image input; Orange will upload it automatically to whichever backend runs the job.';
    titleWrap.append(title, help);

    const uploadButton = document.createElement('button');
    uploadButton.type = 'button';
    uploadButton.className = 'shrink-0 bg-zinc-800 hover:bg-zinc-700 text-zinc-300 px-3 py-2 rounded-lg text-xs font-medium border border-zinc-700 transition flex items-center gap-2';
    const uploadIcon = document.createElement('i');
    uploadIcon.setAttribute('data-lucide', 'upload');
    uploadIcon.className = 'w-3.5 h-3.5';
    uploadButton.append(uploadIcon, document.createTextNode(' Add Image'));

    const fileInput = document.createElement('input');
    fileInput.type = 'file';
    fileInput.accept = 'image/jpeg,image/png,image/webp,image/gif';
    fileInput.className = 'hidden';

    header.append(titleWrap, uploadButton, fileInput);

    const status = document.createElement('div');
    status.className = 'text-xs text-zinc-600';
    status.textContent = 'Select a workflow to manage its fixed assets.';

    const assetList = document.createElement('div');
    assetList.className = 'space-y-2';

    panel.append(header, status, assetList);
    workflowField.parentElement.insertAdjacentElement('afterend', panel);

    let requestVersion = 0;

    function workflowName() {
        return workflowField.value.trim();
    }

    function resetPanel(message = 'Select a workflow to manage its fixed assets.') {
        requestVersion += 1;
        assetList.replaceChildren();
        status.textContent = message;
        uploadButton.disabled = !workflowName();
        uploadButton.classList.toggle('opacity-50', uploadButton.disabled);
    }

    function makeAssetRow(name) {
        const row = document.createElement('div');
        row.className = 'flex items-center justify-between gap-3 bg-zinc-900/70 border border-zinc-800 rounded-lg p-3';

        const left = document.createElement('div');
        left.className = 'min-w-0 flex items-center gap-2';
        const itemIcon = document.createElement('i');
        itemIcon.setAttribute('data-lucide', 'image');
        itemIcon.className = 'w-4 h-4 text-zinc-500 shrink-0';
        const filename = document.createElement('span');
        filename.className = 'text-xs text-zinc-300 font-mono truncate';
        filename.textContent = name;
        left.append(itemIcon, filename);

        const remove = document.createElement('button');
        remove.type = 'button';
        remove.className = 'text-zinc-500 hover:text-red-400 p-1.5 rounded-md hover:bg-red-950/20 transition shrink-0';
        remove.title = `Delete ${name}`;
        const removeIcon = document.createElement('i');
        removeIcon.setAttribute('data-lucide', 'trash-2');
        removeIcon.className = 'w-3.5 h-3.5';
        remove.appendChild(removeIcon);
        remove.addEventListener('click', async () => {
            const currentWorkflow = workflowName();
            if (!currentWorkflow || !confirm(`Delete workflow asset "${name}"?`)) return;
            remove.disabled = true;
            try {
                const response = await adminFetch(
                    `/api/admin/workflows/${encodeURIComponent(currentWorkflow)}/assets/${encodeURIComponent(name)}`,
                    { method: 'DELETE' },
                );
                const data = await response.json().catch(() => ({}));
                if (!response.ok) throw new Error(data.detail || `Delete failed (${response.status})`);
                window.resetWorkflowPreflight?.();
                await loadAssets();
            } catch (error) {
                status.textContent = error.message || 'Could not delete workflow asset.';
            } finally {
                remove.disabled = false;
            }
        });

        row.append(left, remove);
        return row;
    }

    function renderAssets(names) {
        assetList.replaceChildren();
        if (!names.length) {
            status.textContent = 'No fixed images attached to this workflow.';
            const empty = document.createElement('div');
            empty.className = 'text-[11px] text-zinc-600 bg-zinc-900/40 border border-dashed border-zinc-800 rounded-lg p-3';
            empty.textContent = 'Example: if an unmapped LoadImage node references style-reference.png, upload style-reference.png here.';
            assetList.appendChild(empty);
        } else {
            status.textContent = `${names.length} fixed workflow image${names.length === 1 ? '' : 's'} managed by Orange.`;
            names.forEach(name => assetList.appendChild(makeAssetRow(name)));
        }
        if (window.lucide) lucide.createIcons();
    }

    async function loadAssets() {
        const currentWorkflow = workflowName();
        if (!currentWorkflow || typeof adminFetch !== 'function') {
            resetPanel();
            return;
        }

        const version = ++requestVersion;
        uploadButton.disabled = false;
        uploadButton.classList.remove('opacity-50');
        status.textContent = 'Loading workflow assets...';
        assetList.replaceChildren();

        try {
            const response = await adminFetch(`/api/admin/workflows/${encodeURIComponent(currentWorkflow)}/assets`);
            const data = await response.json().catch(() => ({}));
            if (version !== requestVersion) return;
            if (!response.ok) throw new Error(data.detail || `Could not load assets (${response.status})`);
            renderAssets(Array.isArray(data.assets) ? data.assets : []);
        } catch (error) {
            if (version === requestVersion) {
                status.textContent = error.message || 'Could not load workflow assets.';
            }
        }
    }

    uploadButton.addEventListener('click', () => {
        if (workflowName()) fileInput.click();
    });

    fileInput.addEventListener('change', async () => {
        const file = fileInput.files?.[0];
        const currentWorkflow = workflowName();
        if (!file || !currentWorkflow) return;

        const originalText = uploadButton.textContent;
        uploadButton.disabled = true;
        uploadButton.textContent = 'Uploading...';
        status.textContent = `Uploading ${file.name}...`;

        try {
            const form = new FormData();
            form.append('file', file);
            const response = await adminFetch(
                `/api/admin/workflows/${encodeURIComponent(currentWorkflow)}/assets`,
                { method: 'POST', body: form },
            );
            const data = await response.json().catch(() => ({}));
            if (!response.ok) throw new Error(data.detail || `Upload failed (${response.status})`);
            window.resetWorkflowPreflight?.();
            renderAssets(Array.isArray(data.assets) ? data.assets : []);
        } catch (error) {
            status.textContent = error.message || 'Could not upload workflow asset.';
        } finally {
            fileInput.value = '';
            uploadButton.disabled = false;
            uploadButton.textContent = originalText || 'Add Image';
            if (window.lucide) lucide.createIcons();
        }
    });

    workflowField.addEventListener('change', () => {
        requestVersion += 1;
        window.setTimeout(loadAssets, 0);
    });

    if (window.lucide) lucide.createIcons();
    resetPanel();
    if (workflowName()) window.setTimeout(loadAssets, 0);
    window.loadWorkflowAssets = loadAssets;
})();
