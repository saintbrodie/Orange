(() => {
    const resultLayer = document.getElementById('result-layer');
    const promptInput = document.getElementById('prompt-input');
    const outputTextContainer = document.getElementById('output-text-container');
    const backButton = document.getElementById('back-btn');
    const generateButton = document.getElementById('generate-btn');
    const downloadButton = document.getElementById('download-btn');

    if (!resultLayer || !backButton || !generateButton || !downloadButton) return;

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
        const actionRow = backButton.parentElement;
        resultLayer.insertBefore(promptCard, actionRow || null);
    }

    const regenerateButton = document.createElement('button');
    regenerateButton.id = 'regenerate-btn';
    regenerateButton.type = 'button';
    regenerateButton.className = 'bg-orange-950/50 border border-orange-800/50 text-orange-300 font-medium rounded-2xl py-4 px-6 hover:bg-orange-900/50 hover:text-orange-200 hover:border-orange-700 transition-all flex items-center justify-center gap-2';
    const regenIcon = document.createElement('i');
    regenIcon.setAttribute('data-lucide', 'refresh-cw');
    regenIcon.className = 'w-5 h-5';
    regenerateButton.append(regenIcon, document.createTextNode(' Regenerate'));

    downloadButton.parentElement?.insertBefore(regenerateButton, downloadButton);

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

    regenerateButton.addEventListener('click', () => {
        regenerateButton.disabled = true;
        // The form state remains intact behind the result view. Returning to it
        // and immediately submitting again reuses the prompt/images/format while
        // Orange's existing random-seed mapping produces a fresh seed.
        backButton.click();
        window.setTimeout(() => {
            generateButton.click();
            regenerateButton.disabled = false;
        }, 0);
    });

    const observer = new MutationObserver(() => {
        if (!resultLayer.classList.contains('hidden')) updatePromptCard();
    });
    observer.observe(resultLayer, { attributes: true, attributeFilter: ['class'] });

    if (window.lucide) lucide.createIcons();
})();
