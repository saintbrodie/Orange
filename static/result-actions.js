(() => {
    const nativeFetch = window.fetch.bind(window);
    let latestPromptId = null;
    let latestMediaType = 'image';

    // Keep the large legacy generator bundle stable while routing its existing
    // /api/output calls through the normalized media endpoint. Text output is
    // routed too, but it does not overwrite the media type used by the gallery.
    window.fetch = function orangeFetch(input, init) {
        if (typeof input === 'string' && input.startsWith('/api/output?')) {
            const url = new URL(input, window.location.origin);
            const promptId = url.searchParams.get('prompt_id');
            const outputType = (url.searchParams.get('type') || 'image').toLowerCase();
            if (promptId) latestPromptId = promptId;
            if (outputType !== 'text') latestMediaType = outputType;
            url.pathname = '/api/media';
            return nativeFetch(`${url.pathname}${url.search}`, init);
        }
        return nativeFetch(input, init);
    };

    const resultLayer = document.getElementById('result-layer');
    const promptInput = document.getElementById('prompt-input');
    const outputTextContainer = document.getElementById('output-text-container');
    const backButton = document.getElementById('back-btn');
    const generateButton = document.getElementById('generate-btn');
    const downloadButton = document.getElementById('download-btn');

    if (!resultLayer || !backButton || !generateButton || !downloadButton) return;

    const actionRow = backButton.parentElement;
    if (actionRow) actionRow.id = 'result-actions-bar';

    const promptCard = document.createElement('div');
    promptCard.id = 'result-prompt-card';
    promptCard.className = 'hidden w-full max-w-2xl bg-zinc-950/45 border border-zinc-800 rounded-2xl px-5 py-4';

    const promptHeader = document.createElement('div');
    promptHeader.className = 'flex items-center gap-2 text-zinc-500 mb-2';
    const promptIcon = document.createElement('i');
    promptIcon.setAttribute('data-lucide', 'message-square-text');
    promptIcon.className = 'w-4 h-4 text-orange-500';
    const promptLabel = document.createElement('span');
    promptLabel.className = 'text-[10px] font-bold uppercase tracking-widest';
    promptLabel.textContent = 'Prompt';
    promptHeader.append(promptIcon, promptLabel);

    const promptText = document.createElement('div');
    promptText.className = 'text-sm text-zinc-300 leading-relaxed whitespace-pre-wrap break-words max-h-32 overflow-y-auto';
    promptCard.append(promptHeader, promptText);

    if (outputTextContainer) {
        resultLayer.insertBefore(promptCard, outputTextContainer);
    } else {
        resultLayer.insertBefore(promptCard, actionRow || null);
    }

    const outputGallery = document.createElement('section');
    outputGallery.id = 'multi-output-gallery';
    outputGallery.className = 'hidden w-full max-w-3xl space-y-3';

    const galleryHeader = document.createElement('div');
    galleryHeader.className = 'flex items-center justify-between px-1';
    const galleryTitle = document.createElement('div');
    galleryTitle.className = 'flex items-center gap-2 text-xs font-bold uppercase tracking-widest text-zinc-500';
    const galleryIcon = document.createElement('i');
    galleryIcon.setAttribute('data-lucide', 'layout-grid');
    galleryIcon.className = 'w-4 h-4 text-orange-500';
    const galleryTitleText = document.createElement('span');
    galleryTitleText.textContent = 'Outputs';
    const galleryCount = document.createElement('span');
    galleryCount.className = 'text-[10px] font-mono text-zinc-600';
    galleryTitle.append(galleryIcon, galleryTitleText);
    galleryHeader.append(galleryTitle, galleryCount);

    const galleryGrid = document.createElement('div');
    galleryGrid.className = 'grid grid-cols-2 sm:grid-cols-3 gap-3';
    outputGallery.append(galleryHeader, galleryGrid);
    resultLayer.insertBefore(outputGallery, promptCard);

    const regenerateButton = document.createElement('button');
    regenerateButton.id = 'regenerate-btn';
    regenerateButton.type = 'button';
    regenerateButton.className = 'bg-orange-950/50 border border-orange-800/50 text-orange-300 font-medium rounded-2xl py-4 px-6 hover:bg-orange-900/50 hover:text-orange-200 hover:border-orange-700 transition-all flex items-center justify-center gap-2';
    const regenIcon = document.createElement('i');
    regenIcon.setAttribute('data-lucide', 'refresh-cw');
    regenIcon.className = 'w-5 h-5';
    regenerateButton.append(regenIcon, document.createTextNode(' Regenerate'));

    actionRow?.insertBefore(regenerateButton, downloadButton);

    let galleryVersion = 0;
    let galleryRequestKey = '';

    function updatePromptCard() {
        const prompt = promptInput?.value?.trim() || '';
        if (!prompt) {
            promptText.textContent = '';
            promptCard.classList.add('hidden');
            return;
        }
        promptText.textContent = prompt;
        promptCard.classList.remove('hidden');
    }

    function outputUrl(promptId, type, index) {
        const params = new URLSearchParams({
            prompt_id: promptId,
            type,
            index: String(index),
        });
        return `/api/media?${params.toString()}`;
    }

    function makeOutputCard(item, promptId, type) {
        const card = document.createElement('div');
        card.className = 'bg-zinc-950/65 border border-zinc-800 rounded-xl overflow-hidden min-w-0';

        const preview = document.createElement('div');
        preview.className = 'aspect-square bg-black/40 flex items-center justify-center overflow-hidden';
        const src = outputUrl(promptId, type, item.index);
        const mediaType = String(item.media_type || '');

        if (mediaType.startsWith('image/')) {
            const image = document.createElement('img');
            image.src = src;
            image.alt = `Output ${item.index + 1}`;
            image.loading = 'lazy';
            image.className = 'w-full h-full object-cover';
            preview.appendChild(image);
        } else if (mediaType.startsWith('video/')) {
            const video = document.createElement('video');
            video.src = src;
            video.muted = true;
            video.loop = true;
            video.playsInline = true;
            video.preload = 'metadata';
            video.className = 'w-full h-full object-cover';
            video.addEventListener('mouseenter', () => video.play().catch(() => {}));
            video.addEventListener('mouseleave', () => video.pause());
            preview.appendChild(video);
        } else {
            const icon = document.createElement('i');
            icon.setAttribute('data-lucide', mediaType.startsWith('audio/') ? 'music' : 'file');
            icon.className = 'w-8 h-8 text-orange-500/70';
            preview.appendChild(icon);
        }

        const footer = document.createElement('div');
        footer.className = 'flex items-center justify-between gap-2 p-2.5';
        const text = document.createElement('div');
        text.className = 'min-w-0';
        const label = document.createElement('div');
        label.className = 'text-[10px] uppercase tracking-wider font-bold text-zinc-400';
        label.textContent = `Output ${item.index + 1}`;
        const filename = document.createElement('div');
        filename.className = 'text-[10px] text-zinc-600 truncate font-mono';
        filename.textContent = item.filename || '';
        text.append(label, filename);

        const download = document.createElement('a');
        download.href = src;
        download.download = item.filename || `output-${item.index + 1}`;
        download.title = `Download output ${item.index + 1}`;
        download.className = 'shrink-0 p-2 rounded-lg text-zinc-500 hover:text-orange-300 hover:bg-orange-950/30 transition';
        const downloadIcon = document.createElement('i');
        downloadIcon.setAttribute('data-lucide', 'download');
        downloadIcon.className = 'w-4 h-4';
        download.appendChild(downloadIcon);

        footer.append(text, download);
        card.append(preview, footer);
        return card;
    }

    async function renderOutputGallery() {
        if (!latestPromptId || latestMediaType === 'text') return;
        const requestKey = `${latestPromptId}:${latestMediaType}`;
        if (requestKey === galleryRequestKey) return;
        galleryRequestKey = requestKey;
        const version = ++galleryVersion;

        try {
            const params = new URLSearchParams({ prompt_id: latestPromptId, type: latestMediaType });
            const response = await nativeFetch(`/api/outputs?${params.toString()}`);
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const data = await response.json();
            if (version !== galleryVersion) return;
            const items = Array.isArray(data.items) ? data.items : [];

            galleryGrid.replaceChildren();
            if (items.length <= 1) {
                outputGallery.classList.add('hidden');
                return;
            }

            galleryCount.textContent = `${items.length} files`;
            items.forEach(item => galleryGrid.appendChild(makeOutputCard(item, latestPromptId, latestMediaType)));
            outputGallery.classList.remove('hidden');
            if (window.lucide) lucide.createIcons();
        } catch (error) {
            if (version === galleryVersion) {
                outputGallery.classList.add('hidden');
                galleryGrid.replaceChildren();
            }
        }
    }

    function resetGallery() {
        galleryVersion += 1;
        galleryRequestKey = '';
        outputGallery.classList.add('hidden');
        galleryGrid.replaceChildren();
    }

    // Revoke stale blob URLs created by the legacy app whenever a preview/result
    // element moves on to a new source. This keeps repeated editing/regeneration
    // sessions from accumulating browser-held blobs.
    function watchBlobSource(element) {
        if (!element) return;
        const observer = new MutationObserver(mutations => {
            mutations.forEach(mutation => {
                const oldValue = mutation.oldValue || '';
                const current = element.getAttribute('src') || '';
                if (oldValue.startsWith('blob:') && oldValue !== current) {
                    URL.revokeObjectURL(oldValue);
                }
            });
        });
        observer.observe(element, { attributes: true, attributeFilter: ['src'], attributeOldValue: true });
    }

    ['preview-img', 'preview-img2', 'result-image', 'result-video'].forEach(id => {
        watchBlobSource(document.getElementById(id));
    });

    regenerateButton.addEventListener('click', () => {
        regenerateButton.disabled = true;
        resetGallery();
        backButton.click();
        window.setTimeout(() => {
            generateButton.click();
            regenerateButton.disabled = false;
        }, 0);
    });

    backButton.addEventListener('click', resetGallery);

    const observer = new MutationObserver(() => {
        if (!resultLayer.classList.contains('hidden')) {
            updatePromptCard();
            renderOutputGallery();
        }
    });
    observer.observe(resultLayer, { attributes: true, attributeFilter: ['class'] });

    window.addEventListener('pagehide', () => {
        ['preview-img', 'preview-img2', 'result-image', 'result-video'].forEach(id => {
            const src = document.getElementById(id)?.getAttribute('src') || '';
            if (src.startsWith('blob:')) URL.revokeObjectURL(src);
        });
    });

    if (window.lucide) lucide.createIcons();
})();
