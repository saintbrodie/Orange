(() => {
    const PRESET_RATIOS = [
        '1:1',
        '3:2', '4:3', '5:4', '16:9', '21:9',
        '2:3', '3:4', '4:5', '9:16', '9:21',
    ];
    const SLOT_COUNT = 3;
    const PIXELS_PER_MP = 1024 * 1024;

    function currentTool() {
        if (typeof appConfig === 'undefined' || !appConfig || !Array.isArray(appConfig.tools)) return null;
        if (typeof editingToolIndex !== 'undefined' && editingToolIndex >= 0 && appConfig.tools[editingToolIndex]) {
            return appConfig.tools[editingToolIndex];
        }
        const id = document.getElementById('edit-tool-id')?.value.trim();
        return appConfig.tools.find(tool => tool.id === id) || null;
    }

    function ratioValue(name) {
        const parts = String(name || '').split(':').map(Number);
        if (parts.length !== 2 || !parts[0] || !parts[1]) return null;
        let value = parts[0] / parts[1];
        // Preserve Orange's existing model-friendly sizing convention.
        if (name === '16:9') value = 1.75;
        else if (name === '9:16') value = 1 / 1.75;
        else if (name === '21:9') value = 2.39;
        else if (name === '9:21') value = 1 / 2.39;
        return value;
    }

    function dimensionsFor(name, megapixels) {
        const ratio = ratioValue(name);
        if (!ratio || !Number.isFinite(megapixels) || megapixels <= 0) return null;
        const totalPixels = megapixels * PIXELS_PER_MP;
        const rawHeight = Math.sqrt(totalPixels / ratio);
        const height = Math.max(16, Math.round(rawHeight / 16) * 16);
        const width = Math.max(16, Math.round((height * ratio) / 16) * 16);
        return { width, height };
    }

    function estimateMegapixels(ratios) {
        const values = Object.values(ratios || {}).filter(item => item && item.width && item.height);
        if (!values.length) {
            const globalMp = typeof appConfig !== 'undefined' ? parseFloat(appConfig?.targetMegapixels) : NaN;
            return Number.isFinite(globalMp) && globalMp > 0 ? globalMp : 1.0;
        }
        const average = values.reduce((sum, item) => sum + ((item.width * item.height) / PIXELS_PER_MP), 0) / values.length;
        return Math.max(0.1, Math.round(average * 10) / 10);
    }

    function option(select, value, label = value) {
        const item = document.createElement('option');
        item.value = value;
        item.textContent = label;
        select.appendChild(item);
    }

    function updateCalculatedValues(container) {
        const mp = parseFloat(container.querySelector('#tool-ratio-mp')?.value);
        container.querySelectorAll('[data-ratio-slot]').forEach(slot => {
            const select = slot.querySelector('select');
            const preview = slot.querySelector('[data-ratio-preview]');
            const dims = dimensionsFor(select.value, mp);
            slot.dataset.width = dims ? String(dims.width) : '';
            slot.dataset.height = dims ? String(dims.height) : '';
            preview.textContent = dims ? `${dims.width} × ${dims.height}` : 'Not used';
            preview.className = dims
                ? 'text-[11px] text-zinc-400 font-mono text-center mt-2'
                : 'text-[11px] text-zinc-600 font-mono text-center mt-2';
        });
    }

    function syncEnabledState() {
        const resolutionEnabled = !!document.getElementById('map-resolution-enable')?.checked;
        const checkbox = document.getElementById('map-res-custom-ar');
        const arInputs = document.getElementById('ar-inputs');
        if (!checkbox || !arInputs) return;
        if (!resolutionEnabled) {
            checkbox.disabled = true;
            arInputs.classList.add('hidden');
            arInputs.querySelectorAll('input, select').forEach(control => { control.disabled = true; });
            return;
        }
        checkbox.disabled = false;
        arInputs.querySelectorAll('input, select').forEach(control => { control.disabled = !checkbox.checked; });
        arInputs.classList.toggle('hidden', !checkbox.checked);
    }

    function enhanceRatioEditor() {
        const arInputs = document.getElementById('ar-inputs');
        const checkbox = document.getElementById('map-res-custom-ar');
        if (!arInputs || !checkbox || arInputs.dataset.smartRatioUi === '1') return;

        arInputs.dataset.smartRatioUi = '1';
        arInputs.className = arInputs.className.replace('grid grid-cols-3 gap-2', 'space-y-3');
        arInputs.replaceChildren();

        const tool = currentTool();
        const ownRatios = tool?.aspectRatios || null;
        const sourceRatios = ownRatios || (typeof appConfig !== 'undefined' ? appConfig?.aspectRatios : null) || {};
        const selectedNames = Object.keys(sourceRatios).slice(0, SLOT_COUNT);
        const megapixels = estimateMegapixels(sourceRatios);

        const topRow = document.createElement('div');
        topRow.className = 'flex flex-col sm:flex-row sm:items-center justify-between gap-3 bg-zinc-900/50 border border-zinc-800 rounded-lg p-3';
        const description = document.createElement('div');
        const label = document.createElement('div');
        label.className = 'text-[10px] text-zinc-500 font-bold uppercase tracking-wider';
        label.textContent = 'Target Resolution';
        const help = document.createElement('div');
        help.className = 'text-xs text-zinc-500 mt-1';
        help.textContent = 'Choose the formats this tool should expose. Orange calculates model-friendly dimensions automatically.';
        description.append(label, help);

        const mpWrap = document.createElement('label');
        mpWrap.className = 'flex items-center gap-2 shrink-0 text-[10px] text-zinc-500 font-bold uppercase tracking-wider';
        mpWrap.appendChild(document.createTextNode('Megapixels'));
        const mpInput = document.createElement('input');
        mpInput.id = 'tool-ratio-mp';
        mpInput.type = 'number';
        mpInput.min = '0.1';
        mpInput.max = '20';
        mpInput.step = '0.1';
        mpInput.value = String(megapixels);
        mpInput.className = 'w-20 bg-zinc-950 border border-zinc-800 rounded-lg p-2 text-xs text-zinc-300 outline-none focus:border-orange-500 normal-case';
        mpWrap.appendChild(mpInput);
        topRow.append(description, mpWrap);
        arInputs.appendChild(topRow);

        const slots = document.createElement('div');
        slots.className = 'grid grid-cols-1 sm:grid-cols-3 gap-2';

        for (let index = 0; index < SLOT_COUNT; index += 1) {
            const slot = document.createElement('div');
            slot.dataset.ratioSlot = String(index);
            slot.className = 'bg-zinc-900/50 p-3 rounded-lg border border-zinc-800';

            const slotLabel = document.createElement('div');
            slotLabel.className = 'text-[9px] text-zinc-600 font-bold uppercase tracking-wider mb-2';
            slotLabel.textContent = `Format ${index + 1}`;

            const select = document.createElement('select');
            select.className = 'w-full bg-zinc-950 border border-zinc-800 rounded-lg p-2 text-xs text-zinc-300 outline-none focus:border-orange-500';
            option(select, '', 'Not used');
            PRESET_RATIOS.forEach(name => option(select, name));

            const selected = selectedNames[index] || '';
            if (selected && !PRESET_RATIOS.includes(selected)) option(select, selected);
            select.value = selected;

            const preview = document.createElement('div');
            preview.dataset.ratioPreview = '1';
            slot.append(slotLabel, select, preview);
            slots.appendChild(slot);
        }

        arInputs.appendChild(slots);
        arInputs.addEventListener('change', () => updateCalculatedValues(arInputs));
        arInputs.addEventListener('input', () => updateCalculatedValues(arInputs));
        checkbox.addEventListener('change', syncEnabledState);
        document.getElementById('map-resolution-enable')?.addEventListener('change', () => queueMicrotask(syncEnabledState));
        updateCalculatedValues(arInputs);
        syncEnabledState();
    }

    function collectRatioOverride() {
        const resolutionEnabled = !!document.getElementById('map-resolution-enable')?.checked;
        const checkbox = document.getElementById('map-res-custom-ar');
        const arInputs = document.getElementById('ar-inputs');
        if (!resolutionEnabled || !checkbox?.checked || !arInputs || arInputs.dataset.smartRatioUi !== '1') return null;

        const result = {};
        arInputs.querySelectorAll('[data-ratio-slot]').forEach(slot => {
            const name = slot.querySelector('select')?.value;
            const width = parseInt(slot.dataset.width || '', 10);
            const height = parseInt(slot.dataset.height || '', 10);
            if (name && Number.isFinite(width) && Number.isFinite(height)) {
                result[name] = { width, height };
            }
        });
        return result;
    }

    const mappings = document.getElementById('node-mappings-container');
    if (mappings) {
        let scheduled = false;
        const observer = new MutationObserver(() => {
            if (scheduled) return;
            scheduled = true;
            queueMicrotask(() => {
                scheduled = false;
                enhanceRatioEditor();
            });
        });
        observer.observe(mappings, { childList: true, subtree: true });
    }

    const saveButton = document.getElementById('save-tool-btn');
    if (saveButton) {
        // admin.js performs its synchronous mapping collection before its first
        // await. Because this listener was registered later, we can replace the
        // legacy fixed-key aspect ratio result with our smarter calculated set
        // before saveConfigToBackend resumes and writes the config.
        saveButton.addEventListener('click', () => {
            if (typeof appConfig === 'undefined' || typeof editingToolIndex === 'undefined' || editingToolIndex < 0) return;
            const tool = appConfig?.tools?.[editingToolIndex];
            if (!tool) return;
            const override = collectRatioOverride();
            if (override !== null) {
                if (Object.keys(override).length) tool.aspectRatios = override;
                else delete tool.aspectRatios;
            }
        });
    }

    enhanceRatioEditor();
})();
