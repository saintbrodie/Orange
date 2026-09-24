(() => {
    function shortSha(value) {
        return value ? String(value).slice(0, 8) : 'Unknown';
    }

    function escapeHtml(value) {
        return String(value ?? '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    function formatDate(value) {
        if (!value) return '';
        const date = new Date(value);
        if (Number.isNaN(date.getTime())) return String(value);
        return new Intl.DateTimeFormat(undefined, {year: 'numeric', month: 'short', day: 'numeric'}).format(date);
    }

    function ensureCard() {
        let card = document.getElementById('managed-comfyui-card');
        if (card) return card;

        const heading = Array.from(document.querySelectorAll('h3')).find(
            el => el.textContent.trim() === 'System Management'
        );
        const section = heading ? heading.closest('.pt-4') : null;
        if (!section) return null;

        card = document.createElement('div');
        card.id = 'managed-comfyui-card';
        card.className = 'hidden mt-4 rounded-2xl border border-sky-900/50 bg-sky-950/10 p-4';
        section.appendChild(card);
        return card;
    }

    function channelBadge(data) {
        if (data.matchesTested) {
            return '<span class="rounded-full border border-emerald-900/60 bg-emerald-950/40 px-2 py-1 text-[10px] font-bold uppercase tracking-wider text-emerald-400">Orange-tested</span>';
        }
        if (data.channel === 'latest') {
            return '<span class="rounded-full border border-amber-900/60 bg-amber-950/40 px-2 py-1 text-[10px] font-bold uppercase tracking-wider text-amber-400">Upstream</span>';
        }
        return '<span class="rounded-full border border-zinc-700 bg-zinc-900 px-2 py-1 text-[10px] font-bold uppercase tracking-wider text-zinc-400">Custom</span>';
    }

    function firstFinding(tool) {
        const finding = [...(tool?.errors || []), ...(tool?.warnings || [])]
            .find(item => item && item.message);
        return finding?.message || 'Workflow Preflight reported an incompatibility.';
    }

    function validationMarkup(data) {
        const validation = data.validation;
        const tools = Array.isArray(data.tools) ? data.tools : [];
        if (!validation) return '<span class="text-zinc-500">Not yet validated</span>';
        if (validation === 'pending') return '<span class="text-amber-400">Pending</span>';
        if (validation === 'passed') {
            return `<span class="text-emerald-400">Passed${tools.length ? ` · ${tools.length} tool${tools.length === 1 ? '' : 's'} checked` : ''}</span>`;
        }
        const failed = tools.filter(tool => tool && tool.compatible === false);
        return `<span class="text-red-400">Needs attention${failed.length ? ` · ${failed.length} tool${failed.length === 1 ? '' : 's'}` : ''}</span>`;
    }

    function failedToolsMarkup(data) {
        const failed = (data.tools || []).filter(tool => tool && tool.compatible === false);
        if (data.validation !== 'failed' && !data.validationError) return '';
        return `
            <div class="mt-4 rounded-xl border border-red-500/25 bg-red-500/5 p-3">
                <div class="flex items-start gap-2">
                    <i data-lucide="triangle-alert" class="mt-0.5 h-4 w-4 shrink-0 text-red-400"></i>
                    <div class="min-w-0 flex-1">
                        <div class="text-xs font-semibold text-red-300">ComfyUI changed, but Orange found compatibility problems.</div>
                        ${data.validationError ? `<p class="mt-1 text-[11px] text-red-300/80">${escapeHtml(data.validationError)}</p>` : ''}
                        ${failed.length ? `<div class="mt-2 space-y-2">${failed.map(tool => `
                            <div class="rounded-lg border border-red-500/15 bg-black/15 px-3 py-2">
                                <div class="text-[11px] font-semibold text-zinc-200">${escapeHtml(tool.name || tool.id || 'Tool')}</div>
                                <div class="mt-0.5 text-[10px] leading-relaxed text-zinc-500">${escapeHtml(firstFinding(tool))}</div>
                            </div>
                        `).join('')}</div>` : ''}
                        <div class="mt-3 flex flex-wrap gap-2">
                            <button id="managed-comfy-open-library" class="rounded-lg border border-zinc-700 bg-zinc-800 px-3 py-2 text-[11px] font-semibold text-zinc-200 hover:bg-zinc-700">Open Curated Library</button>
                            ${data.canRollback ? '<span class="self-center text-[10px] text-zinc-500">Rollback is available from the Pinokio launcher.</span>' : ''}
                        </div>
                    </div>
                </div>
            </div>`;
    }

    function commitLine(label, sha, date) {
        const when = formatDate(date);
        return `<div><span class="text-zinc-500">${escapeHtml(label)}:</span> <span class="font-mono text-zinc-300">${shortSha(sha)}</span>${when ? `<span class="text-zinc-600"> · ${escapeHtml(when)}</span>` : ''}</div>`;
    }

    function wireActions(card, data) {
        card.querySelector('#managed-comfy-refresh')?.addEventListener('click', loadStatus);
        card.querySelectorAll('#managed-comfy-open-library').forEach(button => {
            button.addEventListener('click', () => {
                document.getElementById('tab-tools')?.click();
                setTimeout(() => document.getElementById('tools-subtab-curated')?.click(), 50);
            });
        });
        card.querySelector('#managed-comfy-return-tested')?.addEventListener('click', () => {
            const help = card.querySelector('#managed-comfy-pinokio-help');
            help?.classList.remove('hidden');
        });
    }

    function render(card, data) {
        if (!data.managed) {
            card.classList.add('hidden');
            card.innerHTML = '';
            return;
        }

        const testedDate = data.testedCommitDate || data.testedDate;
        card.innerHTML = `
            <div class="flex flex-wrap items-start justify-between gap-3">
                <div>
                    <div class="flex flex-wrap items-center gap-2">
                        <i data-lucide="server-cog" class="h-4 w-4 text-sky-400"></i>
                        <h4 class="text-sm font-semibold text-zinc-200">Managed ComfyUI Runtime</h4>
                        ${channelBadge(data)}
                    </div>
                    <p class="mt-1 text-xs text-zinc-500">The image-generation runtime managed by Pinokio. Orange reports its version and validates installed tools against it.</p>
                </div>
                <button id="managed-comfy-refresh" class="rounded-lg border border-sky-900/40 bg-sky-950/20 p-2 text-sky-500/70 hover:text-sky-300" title="Refresh runtime status"><i data-lucide="refresh-cw" class="h-3.5 w-3.5"></i></button>
            </div>

            <div class="mt-4 grid grid-cols-1 gap-2 text-xs sm:grid-cols-2">
                ${commitLine('Current', data.currentCommit, data.currentCommitDate)}
                ${commitLine('Orange-tested', data.testedCommit, testedDate)}
                ${data.canRollback ? commitLine('Previous', data.previousCommit, data.previousCommitDate) : ''}
                <div><span class="text-zinc-500">Preflight:</span> ${validationMarkup(data)}</div>
            </div>

            ${failedToolsMarkup(data)}

            <div class="mt-4 flex flex-wrap items-center gap-2 border-t border-sky-900/30 pt-3">
                ${data.returnToTestedAvailable ? '<button id="managed-comfy-return-tested" class="rounded-lg border border-sky-500/30 bg-sky-500/10 px-3 py-2 text-[11px] font-semibold text-sky-300 hover:bg-sky-500/15">Return to Orange-tested</button>' : ''}
                ${data.canRollback ? '<span class="text-[10px] text-zinc-600">A one-click rollback is available in Pinokio.</span>' : ''}
                ${data.matchesTested ? '<span class="text-[10px] text-emerald-500/80">This is the ComfyUI revision Orange currently ships as known-good.</span>' : ''}
            </div>
            <div id="managed-comfy-pinokio-help" class="hidden mt-3 rounded-lg border border-sky-500/20 bg-sky-500/5 p-3 text-[11px] leading-relaxed text-zinc-400">
                Stop Orange in Pinokio, then choose <span class="font-semibold text-sky-300">Update ComfyUI (Orange-tested)</span>. Start Orange again and it will automatically rerun Workflow Preflight against the installed tools.
            </div>
        `;
        card.classList.remove('hidden');
        wireActions(card, data);
        if (window.lucide) window.lucide.createIcons();
    }

    async function loadStatus() {
        const card = ensureCard();
        const key = localStorage.getItem('orange_admin_key');
        if (!card || !key) return;

        try {
            const response = await fetch('/api/admin/system/comfyui', {
                headers: { Authorization: `Bearer ${key}` },
                cache: 'no-store'
            });
            if (!response.ok) return;
            render(card, await response.json());
        } catch (_) {
            // Runtime status is supplemental; do not disrupt the rest of Admin.
        }
    }

    document.addEventListener('DOMContentLoaded', () => {
        ensureCard();
        setTimeout(loadStatus, 500);
        document.getElementById('tab-general')?.addEventListener('click', () => setTimeout(loadStatus, 50));
        window.addEventListener('focus', loadStatus);
    });
})();
