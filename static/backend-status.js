(() => {
    let statusPanel = null;
    let cardsContainer = null;
    let summaryText = null;
    let refreshButton = null;

    function ensurePanel() {
        if (statusPanel) return statusPanel;

        const serversContainer = document.getElementById('comfy-servers-container');
        if (!serversContainer || !serversContainer.parentElement) return null;

        statusPanel = document.createElement('div');
        statusPanel.id = 'backend-health-panel';
        statusPanel.className = 'pt-4 border-t border-zinc-800/50';

        const header = document.createElement('div');
        header.className = 'flex justify-between items-center gap-3 mb-3';

        const titleWrap = document.createElement('div');
        const title = document.createElement('h3');
        title.className = 'text-sm font-semibold text-zinc-300';
        title.textContent = 'Backend Health';
        summaryText = document.createElement('p');
        summaryText.className = 'text-xs text-zinc-500 mt-1';
        summaryText.textContent = 'Cached ComfyUI health and queue state used for routing.';
        titleWrap.append(title, summaryText);

        refreshButton = document.createElement('button');
        refreshButton.type = 'button';
        refreshButton.className = 'text-xs bg-zinc-800 hover:bg-zinc-700 text-zinc-300 px-3 py-1.5 rounded-lg flex items-center gap-1 transition border border-zinc-700 shadow-sm';
        refreshButton.textContent = 'Refresh';
        refreshButton.addEventListener('click', () => loadBackendHealth(true));

        header.append(titleWrap, refreshButton);

        cardsContainer = document.createElement('div');
        cardsContainer.className = 'grid grid-cols-1 md:grid-cols-2 gap-3';

        statusPanel.append(header, cardsContainer);
        serversContainer.parentElement.insertAdjacentElement('afterend', statusPanel);
        return statusPanel;
    }

    function makeMetric(label, value) {
        const wrap = document.createElement('div');
        wrap.className = 'bg-zinc-950/70 border border-zinc-800 rounded-lg p-2';
        const key = document.createElement('div');
        key.className = 'text-[9px] uppercase tracking-wider text-zinc-600 font-bold';
        key.textContent = label;
        const val = document.createElement('div');
        val.className = 'text-xs text-zinc-300 font-mono mt-0.5';
        val.textContent = String(value);
        wrap.append(key, val);
        return wrap;
    }

    function makeBackendCard(backend) {
        const card = document.createElement('div');
        card.className = 'bg-zinc-800/35 border border-zinc-700/50 rounded-xl p-4 space-y-3';

        const header = document.createElement('div');
        header.className = 'flex items-start justify-between gap-3';

        const identity = document.createElement('div');
        const url = document.createElement('div');
        url.className = 'font-mono text-xs text-zinc-300 break-all';
        url.textContent = backend.url || 'Unknown backend';
        const priority = document.createElement('div');
        priority.className = 'text-[10px] text-zinc-600 mt-1';
        priority.textContent = `Priority ${backend.priority ?? 1}`;
        identity.append(url, priority);

        const badge = document.createElement('span');
        badge.className = 'text-[10px] uppercase tracking-wider font-bold px-2 py-1 rounded border';
        if (backend.circuit_open) {
            badge.classList.add('text-amber-300', 'bg-amber-950/30', 'border-amber-900/50');
            badge.textContent = 'Backoff';
        } else if (backend.healthy) {
            badge.classList.add('text-emerald-300', 'bg-emerald-950/30', 'border-emerald-900/50');
            badge.textContent = 'Healthy';
        } else {
            badge.classList.add('text-red-300', 'bg-red-950/30', 'border-red-900/50');
            badge.textContent = 'Offline';
        }
        header.append(identity, badge);

        const metrics = document.createElement('div');
        metrics.className = 'grid grid-cols-4 gap-2';
        metrics.append(
            makeMetric('Queue', backend.queue_total ?? 0),
            makeMetric('Active', backend.active_requests ?? 0),
            makeMetric('Latency', backend.latency_ms == null ? '—' : `${backend.latency_ms} ms`),
            makeMetric('Failures', backend.consecutive_failures ?? 0),
        );

        card.append(header, metrics);

        if (backend.circuit_open) {
            const backoff = document.createElement('p');
            backoff.className = 'text-xs text-amber-400';
            backoff.textContent = `Temporarily skipped for about ${backend.circuit_seconds_remaining ?? 0}s.`;
            card.appendChild(backoff);
        } else if (backend.last_error) {
            const error = document.createElement('p');
            error.className = 'text-xs text-red-400 break-words';
            error.textContent = backend.last_error;
            card.appendChild(error);
        }

        if (backend.last_checked_age_seconds != null) {
            const checked = document.createElement('p');
            checked.className = 'text-[10px] text-zinc-600';
            checked.textContent = `Checked ${backend.last_checked_age_seconds}s ago`;
            card.appendChild(checked);
        }

        return card;
    }

    async function loadBackendHealth(forceRefresh = false) {
        if (!ensurePanel() || typeof adminFetch !== 'function') return;

        refreshButton.disabled = true;
        refreshButton.textContent = 'Checking...';
        try {
            const res = await adminFetch(`/api/admin/backends/status?refresh=${forceRefresh ? 'true' : 'false'}`);
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            const backends = Array.isArray(data.backends) ? data.backends : [];

            cardsContainer.replaceChildren();
            const healthyCount = backends.filter(item => item.healthy && !item.circuit_open).length;
            summaryText.textContent = `${healthyCount} of ${backends.length} backends currently available for routing.`;

            if (!backends.length) {
                const empty = document.createElement('p');
                empty.className = 'text-xs text-zinc-500';
                empty.textContent = 'No ComfyUI backends configured.';
                cardsContainer.appendChild(empty);
            } else {
                backends.forEach(backend => cardsContainer.appendChild(makeBackendCard(backend)));
            }
        } catch (error) {
            summaryText.textContent = `Could not load backend health: ${error.message}`;
        } finally {
            refreshButton.disabled = false;
            refreshButton.textContent = 'Refresh';
        }
    }

    const generalTab = document.getElementById('tab-general');
    if (generalTab) {
        generalTab.addEventListener('click', () => {
            window.setTimeout(() => loadBackendHealth(false), 0);
        });
    }

    window.loadBackendHealth = loadBackendHealth;
})();
