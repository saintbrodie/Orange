(function () {
    const originalPopulate = window.populateModelSelect;
    if (typeof originalPopulate !== 'function') return;

    function cacheKey(provider, baseUrl) {
        return `orange_llm_models::${provider || 'openai'}::${(baseUrl || '').trim()}`;
    }

    function loadCachedModels(provider, baseUrl) {
        try {
            const parsed = JSON.parse(localStorage.getItem(cacheKey(provider, baseUrl)) || '[]');
            return Array.isArray(parsed) ? parsed.filter(Boolean) : [];
        } catch (_) {
            return [];
        }
    }

    function saveCachedModels(provider, baseUrl, models) {
        try {
            localStorage.setItem(cacheKey(provider, baseUrl), JSON.stringify(models || []));
        } catch (_) { }
    }

    function currentBaseUrl() {
        return document.getElementById('setting-llm-baseurl')?.value?.trim() || '';
    }

    window.populateModelSelect = function (selectEl, customContainerId, customInputId, provider, activeValue, fetchedModels = []) {
        const baseUrl = currentBaseUrl();
        let models = Array.isArray(fetchedModels) ? fetchedModels.filter(Boolean) : [];

        if (models.length > 0) {
            saveCachedModels(provider, baseUrl, models);
        } else {
            models = loadCachedModels(provider, baseUrl);
            // A saved model should remain a normal selection even before this
            // browser has fetched/cached the provider's model list.
            if (models.length === 0 && activeValue && activeValue !== '__custom__') {
                models = [activeValue];
            }
        }

        originalPopulate(selectEl, customContainerId, customInputId, provider, activeValue, models);

        if (selectEl) {
            const customOption = Array.from(selectEl.options).find(option => option.value === '__custom__');
            if (customOption) customOption.textContent = 'Enter model ID...';
        }
    };

    function repopulateFromCache() {
        const select = document.getElementById('setting-llm-model');
        const providerEl = document.getElementById('setting-llm-provider');
        if (!select || !providerEl) return;
        const activeValue = select.value === '__custom__'
            ? (document.getElementById('setting-llm-model-custom')?.value || '')
            : select.value;
        window.populateModelSelect(
            select,
            'setting-llm-model-custom-container',
            'setting-llm-model-custom',
            providerEl.value,
            activeValue,
            []
        );
    }

    document.getElementById('setting-llm-provider')?.addEventListener('change', () => {
        setTimeout(repopulateFromCache, 0);
    });
    document.getElementById('setting-llm-baseurl')?.addEventListener('change', repopulateFromCache);
})();
