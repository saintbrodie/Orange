(() => {
    const editorForm = document.getElementById('tool-editor-form');
    const mappingsContainer = document.getElementById('node-mappings-container');
    if (!editorForm || !mappingsContainer) return;

    const mappingSection = mappingsContainer.parentElement;
    const panel = document.createElement('div');
    panel.id = 'workflow-preflight-panel';
    panel.className = 'space-y-3';

    const header = document.createElement('div');
    header.className = 'flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-zinc-800 pb-2';

    const headingWrap = document.createElement('div');
    const heading = document.createElement('h4');
    heading.className = 'text-sm font-medium text-zinc-300 flex items-center gap-2';
    const headingIcon = document.createElement('i');
    headingIcon.setAttribute('data-lucide', 'stethoscope');
    headingIcon.className = 'w-4 h-4 text-orange-500';
    heading.appendChild(headingIcon);
    heading.appendChild(document.createTextNode(' Workflow Preflight'));

    const description = document.createElement('p');
    description.className = 'text-xs text-zinc-500 mt-1';
    description.textContent = 'Checks mappings, installed nodes, and backend compatibility without executing the workflow.';
    headingWrap.append(heading, description);

    const runButton = document.createElement('button');
    runButton.id = 'run-preflight-btn';
    runButton.type = 'button';
    runButton.className = 'shrink-0 bg-zinc-800 hover:bg-zinc-700 text-zinc-200 px-4 py-2 rounded-lg text-xs font-medium transition flex items-center justify-center gap-2 border border-zinc-700';
    const runIcon = document.createElement('i');
    runIcon.setAttribute('data-lucide', 'scan-search');
    runIcon.className = 'w-4 h-4';
    runButton.append(runIcon, document.createTextNode(' Check Workflow'));

    header.append(headingWrap, runButton);

    const results = document.createElement('div');
    results.id = 'workflow-preflight-results';
    results.className = 'hidden space-y-3';

    panel.append(header, results);
    mappingSection.insertAdjacentElement('afterend', panel);
    if (window.lucide) lucide.createIcons();

    const MAPPING_NAMES = ['prompt', 'image', 'image2', 'resolution', 'seed', 'outputText'];

    function collectNodeMapping() {
        const mapping = {};
        MAPPING_NAMES.forEach(type => {
            const enabled = document.getElementById(`map-${type}-enable`);
            const node = document.getElementById(`map-${type}-node`);
            if (!enabled || !enabled.checked || !node || !node.value.trim()) return;

            const nodeId = node.value.trim();
            if (type === 'resolution') {
                const widthField = document.getElementById('map-res-wfield')?.value.trim() || 'width';
                const heightField = document.getElementById('map-res-hfield')?.value.trim() || 'height';
                mapping.width = { nodeId, field: widthField };
                mapping.height = { nodeId, field: heightField };
                return;
            }

            const field = document.getElementById(`map-${type}-field`)?.value.trim();
            if (!field) return;
            mapping[type] = { nodeId, field };
            if (type === 'seed') {
                mapping[type].generateRandom = !!document.getElementById('map-seed-rand')?.checked;
            }
        });
        return mapping;
    }

    function makeElement(tag, className, text) {
        const element = document.createElement(tag);
        if (className) element.className = className;
        if (text !== undefined && text !== null) element.textContent = String(text);
        return element;
    }

    function statusClasses(status) {
        if (status === 'ready') return 'text-emerald-400 bg-emerald-950/30 border-emerald-900/50';
        if (status === 'warning') return 'text-amber-400 bg-amber-950/30 border-amber-900/50';
        return 'text-red-400 bg-red-950/30 border-red-900/50';
    }

    function statusLabel(status) {
        if (status === 'ready') return 'Ready';
        if (status === 'warning') return 'Needs Review';
        if (status === 'offline') return 'Offline';
        return 'Not Ready';
    }

    function appendIssues(parent, label, issues, tone) {
        if (!Array.isArray(issues) || issues.length === 0) return;
        const wrapper = makeElement('div', 'space-y-1.5');
        const title = makeElement('div', `text-[10px] uppercase tracking-wider font-bold ${tone}`, label);
        wrapper.appendChild(title);

        const visibleIssues = issues.slice(0, 12);
        visibleIssues.forEach(issue => {
            const row = makeElement('div', 'flex items-start gap-2 text-xs text-zinc-400');
            const bullet = makeElement('span', `${tone} mt-0.5`, '•');
            const message = makeElement('span', '', issue.message || issue.code || 'Unknown issue');
            row.append(bullet, message);
            wrapper.appendChild(row);
        });
        if (issues.length > visibleIssues.length) {
            wrapper.appendChild(
                makeElement('div', 'text-[10px] text-zinc-500 pl-4', `+${issues.length - visibleIssues.length} more`)
            );
        }
        parent.appendChild(wrapper);
    }

    function renderPreflight(data) {
        results.replaceChildren();
        results.classList.remove('hidden');

        const summary = data.summary || {};
        const workflow = data.workflow || {};
        const summaryCard = makeElement('div', `p-4 rounded-xl border ${statusClasses(summary.status)} flex flex-col sm:flex-row sm:items-center justify-between gap-2`);
        const summaryText = makeElement(
            'div',
            'font-semibold text-sm',
            summary.total_backends
                ? `${summary.compatible_backends || 0} of ${summary.total_backends} backends compatible`
                : 'No ComfyUI backends configured'
        );
        const detail = makeElement(
            'div',
            'text-[11px] opacity-80 font-mono',
            `${workflow.node_count || 0} nodes • ${workflow.class_count || 0} node classes`
        );
        const left = makeElement('div');
        left.append(summaryText, detail);
        const badge = makeElement('span', 'text-[10px] uppercase tracking-widest font-bold', statusLabel(summary.status));
        summaryCard.append(left, badge);
        results.appendChild(summaryCard);

        const local = data.local || {};
        if ((local.errors && local.errors.length) || (local.warnings && local.warnings.length)) {
            const localCard = makeElement('div', 'bg-zinc-950/60 border border-zinc-800 rounded-xl p-4 space-y-3');
            localCard.appendChild(makeElement('div', 'text-xs font-semibold text-zinc-300', 'Orange / Workflow Checks'));
            appendIssues(localCard, 'Errors', local.errors, 'text-red-400');
            appendIssues(localCard, 'Warnings', local.warnings, 'text-amber-400');
            results.appendChild(localCard);
        }

        (data.backends || []).forEach((backend, index) => {
            const card = makeElement('div', 'bg-zinc-950/60 border border-zinc-800 rounded-xl p-4 space-y-3');
            const cardHeader = makeElement('div', 'flex items-start justify-between gap-3');
            const identity = makeElement('div', 'min-w-0');
            identity.appendChild(makeElement('div', 'text-xs font-semibold text-zinc-300', `Backend ${index + 1} • Priority ${backend.priority ?? 1}`));
            identity.appendChild(makeElement('div', 'text-[11px] text-zinc-500 font-mono truncate', backend.url || 'No URL'));
            const backendBadge = makeElement('span', `shrink-0 border rounded-md px-2 py-1 text-[10px] font-bold uppercase tracking-wider ${statusClasses(backend.status)}`, statusLabel(backend.status));
            cardHeader.append(identity, backendBadge);
            card.appendChild(cardHeader);

            if (backend.reachable) {
                const stats = [];
                if (backend.available_node_classes !== null && backend.available_node_classes !== undefined) {
                    stats.push(`${backend.available_node_classes} installed node classes`);
                }
                if (backend.latency_ms !== null && backend.latency_ms !== undefined) {
                    stats.push(`${backend.latency_ms} ms`);
                }
                if (stats.length) card.appendChild(makeElement('div', 'text-[10px] text-zinc-600 font-mono', stats.join(' • ')));
            }

            appendIssues(card, 'Errors', backend.errors, 'text-red-400');
            appendIssues(card, 'Warnings', backend.warnings, 'text-amber-400');
            if ((!backend.errors || backend.errors.length === 0) && (!backend.warnings || backend.warnings.length === 0)) {
                card.appendChild(makeElement('div', 'text-xs text-emerald-400 flex items-center gap-2', '✓ Workflow is compatible with this backend.'));
            }
            results.appendChild(card);
        });
    }

    function renderFailure(message) {
        results.replaceChildren();
        results.classList.remove('hidden');
        const card = makeElement('div', 'bg-red-950/30 border border-red-900/50 text-red-300 rounded-xl p-4 text-xs', message);
        results.appendChild(card);
    }

    function markStale() {
        if (results.classList.contains('hidden') || results.childElementCount === 0) return;
        results.replaceChildren(
            makeElement('div', 'bg-zinc-950/60 border border-zinc-800 rounded-xl p-3 text-xs text-zinc-500', 'Workflow or mappings changed. Run preflight again to refresh diagnostics.')
        );
    }

    editorForm.addEventListener('input', event => {
        if (event.target.closest('#node-mappings-container') || event.target.id === 'edit-tool-file') markStale();
    });
    editorForm.addEventListener('change', event => {
        if (event.target.closest('#node-mappings-container') || event.target.id === 'edit-tool-file') markStale();
    });

    runButton.addEventListener('click', async () => {
        const workflowFile = document.getElementById('edit-tool-file')?.value.trim();
        if (!workflowFile) {
            renderFailure('Select or upload a workflow before running preflight.');
            return;
        }

        const originalText = runButton.textContent;
        runButton.disabled = true;
        runButton.classList.add('opacity-60', 'cursor-wait');
        runButton.replaceChildren();
        const spinner = document.createElement('i');
        spinner.setAttribute('data-lucide', 'loader-2');
        spinner.className = 'w-4 h-4 animate-spin';
        runButton.append(spinner, document.createTextNode(' Checking...'));
        if (window.lucide) lucide.createIcons();

        try {
            const response = await adminFetch('/api/admin/workflows/preflight', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    workflowFile,
                    nodeMapping: collectNodeMapping(),
                }),
            });
            const data = await response.json().catch(() => ({}));
            if (!response.ok) throw new Error(data.detail || `Preflight failed (${response.status})`);
            renderPreflight(data);
        } catch (error) {
            renderFailure(error.message || 'Workflow preflight failed.');
        } finally {
            runButton.disabled = false;
            runButton.classList.remove('opacity-60', 'cursor-wait');
            runButton.replaceChildren();
            const icon = document.createElement('i');
            icon.setAttribute('data-lucide', 'scan-search');
            icon.className = 'w-4 h-4';
            runButton.append(icon, document.createTextNode(originalText || ' Check Workflow'));
            if (window.lucide) lucide.createIcons();
        }
    });
})();
