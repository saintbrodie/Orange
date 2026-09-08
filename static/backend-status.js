(() => {
    const AUTO_REFRESH_MS = 1000;

    let statusPanel = null;
    let cardsContainer = null;
    let summaryText = null;
    let refreshButton = null;
    let refreshTimer = null;
    let requestInFlight = false;

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
        summaryText.textContent = 'Live ComfyUI health and queue state used for routing.';
        titleWrap.append(title, summaryText);

        refreshButton = document.createElement('button');
        refreshButton.type = 'button';
        refreshButton.className = 'text-xs bg-zinc-800 hover:bg-zinc-700 text-zinc-300 px-3 py-1.5 rounded-lg flex items-center gap-1 transition border border-zinc-700 shadow-sm';
        refreshButton.textContent = 'Refresh Now';
        refreshButton.addEventListener('click', () => loadBackendHealth(true, false));

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
        const available = !!backend.healthy && !backend.circuit_open;
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
        if (available) {
            badge.classList.add('text-emerald-300', 'bg-emerald-950/30', 'border-emerald-900/50');
            badge.textContent = 'Healthy';
        } else {
            badge.classList.add('text-red-300', 'bg-red-950/30', 'border-red-900/50');
            badge.textContent = 'Down';
        }
        header.append(identity, badge);
        card.appendChild(header);

        if (available) {
            const metrics = document.createElement('div');
            metrics.className = 'grid grid-cols-3 gap-2';
            metrics.append(
                makeMetric('Queue', backend.queue_total ?? 0),
                makeMetric('Active', backend.active_requests ?? 0),
                makeMetric('Latency', backend.latency_ms == null ? '—' : `${backend.latency_ms} ms`),
            );
            card.appendChild(metrics);
        } else {
            const message = document.createElement('p');
            message.className = 'text-xs text-zinc-500';
            message.textContent = 'Not responding. Orange will route around this backend until it recovers.';
            card.appendChild(message);
        }

        return card;
    }

    function settingsAreVisible() {
        const settingsContainer = document.getElementById('settings-container');
        return !!settingsContainer && !settingsContainer.classList.contains('hidden') && !document.hidden;
    }

    async function loadBackendHealth(forceRefresh = false, silent = true) {
        if (!ensurePanel() || typeof adminFetch !== 'function' || requestInFlight) return;

        requestInFlight = true;
        if (!silent) {
            refreshButton.disabled = true;
            refreshButton.textContent = 'Checking...';
        }

        try {
            const res = await adminFetch(`/api/admin/backends/status?refresh=${forceRefresh ? 'true' : 'false'}`);
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            const backends = Array.isArray(data.backends) ? data.backends : [];

            cardsContainer.replaceChildren();
            const healthyCount = backends.filter(item => item.healthy && !item.circuit_open).length;
            summaryText.textContent = `${healthyCount} of ${backends.length} backends available for routing.`;

            if (!backends.length) {
                const empty = document.createElement('p');
                empty.className = 'text-xs text-zinc-500';
                empty.textContent = 'No ComfyUI backends configured.';
                cardsContainer.appendChild(empty);
            } else {
                backends.forEach(backend => cardsContainer.appendChild(makeBackendCard(backend)));
            }
        } catch (error) {
            if (!silent) summaryText.textContent = `Could not load backend health: ${error.message}`;
        } finally {
            requestInFlight = false;
            if (!silent) {
                refreshButton.disabled = false;
                refreshButton.textContent = 'Refresh Now';
            }
        }
    }

    function startLiveMonitor() {
        if (refreshTimer) return;
        refreshTimer = window.setInterval(() => {
            if (settingsAreVisible()) {
                // Force a fresh queue/health probe while this panel is visible so
                // short-lived queue changes are visible instead of waiting for the
                // background monitor's next cached update.
                loadBackendHealth(true, true);
            }
        }, AUTO_REFRESH_MS);
    }

    const generalTab = document.getElementById('tab-general');
    if (generalTab) {
        generalTab.addEventListener('click', () => {
            window.setTimeout(() => loadBackendHealth(true, true), 0);
        });
    }

    document.addEventListener('visibilitychange', () => {
        if (settingsAreVisible()) loadBackendHealth(true, true);
    });

    ensurePanel();
    startLiveMonitor();
    if (settingsAreVisible()) {
        window.setTimeout(() => loadBackendHealth(true, true), 0);
    }

    window.loadBackendHealth = loadBackendHealth;
})();
