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
        card.className = 'hidden mt-4 rounded-2xl border border-zinc-800 bg-zinc-950/70 p-4';
        section.appendChild(card);
        return card;
    }

    function validationMarkup(data) {
        const validation = data.validation;
        if (!validation) {
            return '<span class="text-zinc-500">Not yet validated</span>';
        }
        if (validation === 'pending') {
            return '<span class="text-amber-400">Validation pending</span>';
        }
        if (validation === 'passed') {
            const count = Array.isArray(data.tools) ? data.tools.length : 0;
            return `<span class="text-emerald-400">Passed${count ? ` · ${count} tool${count === 1 ? '' : 's'} checked` : ''}</span>`;
        }
        const failed = (data.tools || []).filter(tool => tool && tool.compatible === false);
        const names = failed.map(tool => escapeHtml(tool.name || tool.id)).join(', ');
        return `<span class="text-red-400">Failed${names ? ` · ${names}` : ''}</span>`;
    }

    function render(card, data) {
        if (!data.managed) {
            card.classList.add('hidden');
            card.innerHTML = '';
            return;
        }

        const tested = data.matchesTested;
        const channelLabel = tested
            ? '<span class="rounded-full border border-emerald-900/60 bg-emerald-950/40 px-2 py-1 text-[10px] font-bold uppercase tracking-wider text-emerald-400">Orange tested</span>'
            : data.channel === 'latest'
                ? '<span class="rounded-full border border-amber-900/60 bg-amber-950/40 px-2 py-1 text-[10px] font-bold uppercase tracking-wider text-amber-400">Upstream / untested</span>'
                : '<span class="rounded-full border border-zinc-700 bg-zinc-900 px-2 py-1 text-[10px] font-bold uppercase tracking-wider text-zinc-400">Custom version</span>';

        const testedDate = data.testedDate ? ` · ${escapeHtml(data.testedDate)}` : '';
        const previous = data.previousCommit
            ? `<div><span class="text-zinc-500">Previous:</span> <span class="font-mono text-zinc-300">${shortSha(data.previousCommit)}</span></div>`
            : '';
        const validationError = data.validationError
            ? `<p class="mt-2 text-xs text-amber-400/90">${escapeHtml(data.validationError)}</p>`
            : '';

        card.innerHTML = `
            <div class="flex flex-wrap items-start justify-between gap-3">
                <div>
                    <div class="flex items-center gap-2">
                        <i data-lucide="cpu" class="h-4 w-4 text-orange-500"></i>
                        <h4 class="text-sm font-semibold text-zinc-200">Managed ComfyUI</h4>
                        ${channelLabel}
                    </div>
                    <p class="mt-1 text-xs text-zinc-500">Pinned and updated separately from Orange by the Pinokio launcher.</p>
                </div>
            </div>
            <div class="mt-4 grid grid-cols-1 gap-2 text-xs sm:grid-cols-2">
                <div><span class="text-zinc-500">Current:</span> <span class="font-mono text-zinc-300">${shortSha(data.currentCommit)}</span></div>
                <div><span class="text-zinc-500">Orange tested:</span> <span class="font-mono text-zinc-300">${shortSha(data.testedCommit)}</span><span class="text-zinc-600">${testedDate}</span></div>
                ${previous}
                <div><span class="text-zinc-500">Preflight:</span> ${validationMarkup(data)}</div>
            </div>
            ${validationError}
            <p class="mt-3 text-[11px] text-zinc-600">Stop Orange in Pinokio to update ComfyUI, try upstream latest, or roll back to the previous revision.</p>
        `;
        card.classList.remove('hidden');
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
