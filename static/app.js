document.addEventListener("DOMContentLoaded", () => {
    lucide.createIcons();

    const configUrl = '/api/workflows';
    let config = null;
    let selectedToolId = null;
    let selectedAspectRatio = null;
    let selectedImageFile = null;

    // DOM Elements
    const uiContainer = document.getElementById('ui-container');
    const generatingLayer = document.getElementById('generating-layer');
    const resultLayer = document.getElementById('result-layer');

    const toolTabs = document.getElementById('tool-tabs');
    const aspectRatios = document.getElementById('aspect-ratios');
    
    const promptContainer = document.getElementById('prompt-container');
    const promptInput = document.getElementById('prompt-input');
    
    const imageUploadContainer = document.getElementById('image-upload-container');
    const dropzone = document.getElementById('dropzone');
    const imageInput = document.getElementById('image-input');
    const imagePreview = document.getElementById('image-preview');
    const previewImg = document.getElementById('preview-img');
    const clearImageBtn = document.getElementById('clear-image-btn');

    const aspectRatioContainer = document.getElementById('aspect-ratio-container');
    const generateBtn = document.getElementById('generate-btn');
    const queueStatus = document.getElementById('queue-status');
    const resultImage = document.getElementById('result-image');
    const backBtn = document.getElementById('back-btn');
    const downloadBtn = document.getElementById('download-btn');
    const errorBanner = document.getElementById('error-banner');
    const errorMessage = document.getElementById('error-message');

    // Init
    fetch(configUrl).then(res => res.json()).then(data => {
        config = data;
        renderTools();
        selectTool(config.tools[0].id); // Select first tool
    }).catch(err => {
        showError("Failed to load tools.");
    });

    function renderTools() {
        toolTabs.innerHTML = '';
        config.tools.forEach(tool => {
            const btn = document.createElement('button');
            const isActive = tool.id === selectedToolId;
            btn.className = `w-full text-left px-4 py-3 rounded-xl text-sm font-medium transition-all border flex items-center justify-between group ${
                isActive 
                ? 'bg-orange-500/10 border-orange-500/30 text-orange-400' 
                : 'bg-zinc-900 border-zinc-800 text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200'
            }`;
            
            // Add icon/dot and text
            btn.innerHTML = `
                <span>${tool.name}</span>
                <i data-lucide="chevron-right" class="w-4 h-4 opacity-50 ${isActive ? 'text-orange-400 opacity-100' : 'group-hover:opacity-100'}"></i>
            `;
            
            btn.onclick = () => selectTool(tool.id);
            toolTabs.appendChild(btn);
        });
        // Re-init lucide for the dynamically added icons
        lucide.createIcons();
    }

    function renderAspectRatios() {
        aspectRatios.innerHTML = '';
        if(!config || !selectedToolId) return;
        const tool = config.tools.find(t => t.id === selectedToolId);
        let ratiosObj = config.aspectRatios || {};
        if(tool && tool.aspectRatios) {
            ratiosObj = tool.aspectRatios;
        }
        
        const ratios = Object.keys(ratiosObj);
        if(ratios.length === 0) return;

        // Ensure selected ratio is valid before rendering
        if(!selectedAspectRatio || !ratios.includes(selectedAspectRatio)) {
            selectedAspectRatio = ratios[0];
        }

        ratios.forEach(ratio => {
            const btn = document.createElement('button');
            const isSelected = ratio === selectedAspectRatio;
            btn.className = `py-3 rounded-xl flex items-center justify-center font-medium text-sm transition-all border ${isSelected ? 'bg-zinc-800 border-zinc-600 text-zinc-100' : 'bg-transparent border-zinc-800 text-zinc-500 hover:text-zinc-300 hover:border-zinc-700'}`;
            
            let iconClass = "border-2 rounded-sm border-current mr-2 ";
            if(ratio.includes('1:1') || ratio.toLowerCase().includes('square')) iconClass += "w-4 h-4";
            else if(ratio.includes('16') && ratio.startsWith('9')) iconClass += "w-3 h-5";
            else iconClass += "w-5 h-3";

            btn.innerHTML = `<div class="${iconClass}"></div> ${ratio}`;
            btn.onclick = () => {
                selectedAspectRatio = ratio;
                renderAspectRatios();
            };
            aspectRatios.appendChild(btn);
        });
    }

    function selectTool(toolId) {
        selectedToolId = toolId;
        renderTools();
        renderAspectRatios();
        
        const tool = config.tools.find(t => t.id === toolId);
        if(!tool) return;

        // Dynamic inputs visualization based on nodeMapping requirements
        const mapping = tool.nodeMapping;
        
        // Image
        if(mapping.image) {
            imageUploadContainer.classList.remove('hidden');
        } else {
            imageUploadContainer.classList.add('hidden');
            clearImage();
        }

        // Prompt
        if(mapping.prompt) {
            promptContainer.classList.remove('hidden');
        } else {
            promptContainer.classList.add('hidden');
        }

        // Aspect Ratio uses width/height
        if(mapping.width && mapping.height) {
            aspectRatioContainer.classList.remove('hidden');
        } else {
            aspectRatioContainer.classList.add('hidden');
        }
    }

    // Image Upload Logic
    dropzone.addEventListener('click', () => imageInput.click());
    dropzone.addEventListener('dragover', (e) => { e.preventDefault(); dropzone.classList.add('border-zinc-600'); });
    dropzone.addEventListener('dragleave', () => dropzone.classList.remove('border-zinc-600'));
    dropzone.addEventListener('drop', (e) => {
        e.preventDefault();
        dropzone.classList.remove('border-zinc-600');
        if(e.dataTransfer.files && e.dataTransfer.files[0]) {
            handleImageSelected(e.dataTransfer.files[0]);
        }
    });
    imageInput.addEventListener('change', (e) => {
        if(e.target.files && e.target.files[0]) {
            handleImageSelected(e.target.files[0]);
        }
    });

    function handleImageSelected(file) {
        selectedImageFile = file;
        const url = URL.createObjectURL(file);
        previewImg.src = url;
        dropzone.classList.add('hidden');
        imagePreview.classList.remove('hidden');
        errorBanner.classList.add('hidden');
    }

    function clearImage() {
        selectedImageFile = null;
        imageInput.value = '';
        previewImg.src = '';
        imagePreview.classList.add('hidden');
        dropzone.classList.remove('hidden');
    }
    clearImageBtn.addEventListener('click', clearImage);

    function showError(msg) {
        errorMessage.innerText = msg;
        errorBanner.classList.remove('hidden');
    }

    // Generation Logic
    generateBtn.addEventListener('click', async () => {
        errorBanner.classList.add('hidden');
        const tool = config.tools.find(t => t.id === selectedToolId);
        
        // Validation
        if(tool.nodeMapping.prompt && !promptInput.value.trim()) {
            return showError("Please enter a prompt.");
        }
        if(tool.nodeMapping.image && !selectedImageFile) {
            return showError("Please upload a reference image.");
        }

        // Setup Form Data
        const formData = new FormData();
        formData.append("tool_id", selectedToolId);
        if(tool.nodeMapping.prompt) formData.append("prompt", promptInput.value.trim());
        if(tool.nodeMapping.width && tool.nodeMapping.height) formData.append("aspect_ratio", selectedAspectRatio);
        if(tool.nodeMapping.image) formData.append("image", selectedImageFile);

        // UI Reset
        uiContainer.classList.add('hidden');
        generatingLayer.classList.remove('hidden');
        generatingLayer.classList.add('flex');
        
        const generatingTitle = document.getElementById('generating-title');
        const queueStatus = document.getElementById('queue-status');
        const progressContainer = document.getElementById('progress-container');
        
        progressContainer.classList.add('hidden');
        queueStatus.classList.remove('hidden');
        generatingTitle.innerText = "Initializing connection...";
        queueStatus.innerText = "Connecting to server";
        generateBtn.disabled = true;

        try {
            const res = await fetch('/api/generate', {
                method: 'POST',
                body: formData
            });

            if(!res.ok) {
                const err = await res.json();
                throw new Error(err.detail || "Failed to start generation");
            }

            const data = await res.json();
            const promptId = data.prompt_id;
            const clientId = data.client_id;
            
            // Start SSE listening
            listenToQueue(promptId, clientId);

        } catch (e) {
            showGenerationError(e.message);
        }
    });

    function listenToQueue(promptId, clientId) {
        const evtSource = new EventSource(`/api/status?prompt_id=${promptId}&client_id=${clientId}`);
        
        const progressBarFill = document.getElementById('progress-bar-fill');
        const progressContainer = document.getElementById('progress-container');
        const progressPercentage = document.getElementById('progress-percentage');
        const progressSteps = document.getElementById('progress-steps');
        const generatingTitle = document.getElementById('generating-title');
        const queueStatus = document.getElementById('queue-status');

        evtSource.onmessage = (event) => {
            const data = JSON.parse(event.data);
            if(data.status === 'queue') {
                generatingTitle.innerText = "Waiting in Queue...";
                queueStatus.innerText = `Queue position: ${data.position}`;
            } else if (data.status === 'generating') {
                generatingTitle.innerText = "Setting things up...";
                queueStatus.innerText = `Getting ready`;
            } else if (data.status === 'progress') {
                progressContainer.classList.remove('hidden');
                queueStatus.classList.add('hidden');
                generatingTitle.innerText = "Generating Image...";
                
                const percent = Math.round((data.value / data.max) * 100);
                progressBarFill.style.width = `${percent}%`;
                progressPercentage.innerText = `${percent}%`;
                progressSteps.innerText = `${data.value} / ${data.max}`;
                
            } else if (data.status === 'completed') {
                evtSource.close();
                fetchAndShowImage(promptId);
            } else if (data.status === 'error') {
                evtSource.close();
                showGenerationError(data.detail || "An error occurred during generation.");
            }
        };

        evtSource.onerror = (err) => {
            evtSource.close();
            // Try fetching final if crashed out of queue
            fetchAndShowImage(promptId).catch(() => {
                showGenerationError("Lost connection to server.");
            });
        };
    }

    async function fetchAndShowImage(promptId) {
        const generatingTitle = document.getElementById('generating-title');
        try {
            generatingTitle.innerText = `Finalizing Image...`;
            document.getElementById('queue-status').classList.remove('hidden');
            document.getElementById('queue-status').innerText = `Stripping metadata`;
            
            const imageRes = await fetch(`/api/image?prompt_id=${promptId}`);
            if(!imageRes.ok) throw new Error("Metadata stripped image not found");
            
            const blob = await imageRes.blob();
            const url = URL.createObjectURL(blob);
            resultImage.src = url;
            
            generatingLayer.classList.add('hidden');
            generatingLayer.classList.remove('flex');
            resultLayer.classList.remove('hidden');
            resultLayer.classList.add('flex');

            // Setup download
            downloadBtn.onclick = () => {
                const a = document.createElement('a');
                a.href = url;
                a.download = `creation-${promptId.substring(0,8)}.png`;
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
            };

        } catch (e) {
            showGenerationError("Failed to fetch final image. It might have failed on the server.");
        }
    }

    function showGenerationError(msg) {
        generatingLayer.classList.add('hidden');
        generatingLayer.classList.remove('flex');
        uiContainer.classList.remove('hidden');
        generateBtn.disabled = false;
        showError(msg);
    }

    backBtn.addEventListener('click', () => {
        resultLayer.classList.add('hidden');
        resultLayer.classList.remove('flex');
        uiContainer.classList.remove('hidden');
        generateBtn.disabled = false;
        
        // Reset progress visually
        document.getElementById('progress-bar-fill').style.width = '0%';
        document.getElementById('progress-percentage').innerText = '0%';
        document.getElementById('progress-steps').innerText = '0 / 0';
    });

});
