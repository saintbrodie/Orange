document.addEventListener("DOMContentLoaded", () => {
    lucide.createIcons();

    const configUrl = '/api/workflows';
    let config = null;
    let selectedToolId = null;
    let selectedAspectRatio = null;
    let selectedImageFile = null;
    let selectedImage2File = null;
    let currentOutputType = 'image';

    // DOM Elements
    const uiContainer = document.getElementById('ui-container');
    const generatingLayer = document.getElementById('generating-layer');
    const resultLayer = document.getElementById('result-layer');

    const toolTabs = document.getElementById('tool-tabs');
    const aspectRatios = document.getElementById('aspect-ratios');
    
    const promptContainer = document.getElementById('prompt-container');
    const promptInput = document.getElementById('prompt-input');
    
    const imageUploadContainer = document.getElementById('image-upload-container');
    const image1Box = document.getElementById('image1-box');
    const image2Box = document.getElementById('image2-box');

    const dropzone = document.getElementById('dropzone');
    const imageInput = document.getElementById('image-input');
    const imagePreview = document.getElementById('image-preview');
    const previewImg = document.getElementById('preview-img');
    const clearImageBtn = document.getElementById('clear-image-btn');

    const dropzone2 = document.getElementById('dropzone2');
    const image2Input = document.getElementById('image2-input');
    const image2Preview = document.getElementById('image2-preview');
    const previewImg2 = document.getElementById('preview-img2');
    const clearImage2Btn = document.getElementById('clear-image2-btn');

    const aspectRatioContainer = document.getElementById('aspect-ratio-container');
    const generateBtn = document.getElementById('generate-btn');
    const queueStatus = document.getElementById('queue-status');
    const resultImage = document.getElementById('result-image');
    const resultVideo = document.getElementById('result-video');
    const resultAudio = document.getElementById('result-audio');
    const backBtn = document.getElementById('back-btn');
    const downloadBtn = document.getElementById('download-btn');
    const downloadBtnText = document.getElementById('download-btn-text');
    const errorBanner = document.getElementById('error-banner');
    const errorMessage = document.getElementById('error-message');

    // Init
    fetch(configUrl).then(res => res.json()).then(data => {
        config = data;
        renderTools();
        selectTool(config.tools[0].id);
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
            
            // Choose icon based on output type
            let iconName = 'chevron-right';
            
            btn.innerHTML = `
                <span>${tool.name}</span>
                <i data-lucide="${iconName}" class="w-4 h-4 opacity-50 ${isActive ? 'text-orange-400 opacity-100' : 'group-hover:opacity-100'}"></i>
            `;
            
            btn.onclick = () => selectTool(tool.id);
            toolTabs.appendChild(btn);
        });
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

        // Track output type
        currentOutputType = tool.outputType || 'image';

        const mapping = tool.nodeMapping;
        
        // Image 1
        if(mapping.image) {
            imageUploadContainer.classList.remove('hidden');
            image1Box.classList.remove('hidden');
        } else {
            imageUploadContainer.classList.add('hidden');
            image1Box.classList.add('hidden');
            clearImage();
        }

        // Image 2
        if(mapping.image2) {
            imageUploadContainer.classList.remove('hidden');
            image2Box.classList.remove('hidden');
        } else {
            image2Box.classList.add('hidden');
            clearImage2();
        }

        // If neither image mapping, hide the whole container
        if(!mapping.image && !mapping.image2) {
            imageUploadContainer.classList.add('hidden');
        }

        // Prompt
        if(mapping.prompt) {
            promptContainer.classList.remove('hidden');
        } else {
            promptContainer.classList.add('hidden');
        }

        // Aspect Ratio
        if(mapping.width && mapping.height) {
            aspectRatioContainer.classList.remove('hidden');
        } else {
            aspectRatioContainer.classList.add('hidden');
        }
    }

    // Image 1 Upload Logic
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

    // Image 2 Upload Logic
    dropzone2.addEventListener('click', () => image2Input.click());
    dropzone2.addEventListener('dragover', (e) => { e.preventDefault(); dropzone2.classList.add('border-zinc-600'); });
    dropzone2.addEventListener('dragleave', () => dropzone2.classList.remove('border-zinc-600'));
    dropzone2.addEventListener('drop', (e) => {
        e.preventDefault();
        dropzone2.classList.remove('border-zinc-600');
        if(e.dataTransfer.files && e.dataTransfer.files[0]) {
            handleImage2Selected(e.dataTransfer.files[0]);
        }
    });
    image2Input.addEventListener('change', (e) => {
        if(e.target.files && e.target.files[0]) {
            handleImage2Selected(e.target.files[0]);
        }
    });

    function handleImage2Selected(file) {
        selectedImage2File = file;
        const url = URL.createObjectURL(file);
        previewImg2.src = url;
        dropzone2.classList.add('hidden');
        image2Preview.classList.remove('hidden');
        errorBanner.classList.add('hidden');
    }

    function clearImage2() {
        selectedImage2File = null;
        image2Input.value = '';
        previewImg2.src = '';
        image2Preview.classList.add('hidden');
        dropzone2.classList.remove('hidden');
    }
    clearImage2Btn.addEventListener('click', clearImage2);

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
            return showError("Please upload an image.");
        }
        if(tool.nodeMapping.image2 && !selectedImage2File) {
            return showError("Please upload a second image.");
        }

        // Setup Form Data
        const formData = new FormData();
        formData.append("tool_id", selectedToolId);
        if(tool.nodeMapping.prompt) formData.append("prompt", promptInput.value.trim());
        if(tool.nodeMapping.width && tool.nodeMapping.height) formData.append("aspect_ratio", selectedAspectRatio);
        if(tool.nodeMapping.image) formData.append("image", selectedImageFile);
        if(tool.nodeMapping.image2) formData.append("image2", selectedImage2File);

        // UI Reset
        uiContainer.classList.add('hidden');
        generatingLayer.classList.remove('hidden');
        generatingLayer.classList.add('flex');
        
        const generatingTitle = document.getElementById('generating-title');
        const queueStatus = document.getElementById('queue-status');
        const progressContainer = document.getElementById('progress-container');
        
        const spinner = document.getElementById('loading-spinner');
        const previewContainer = document.getElementById('live-preview-container');
        const previewImage = document.getElementById('live-preview-image');
        if (spinner) spinner.classList.remove('hidden');
        if (previewContainer) {
            previewContainer.classList.add('hidden');
            previewContainer.classList.remove('opacity-100');
        }
        if (previewImage) previewImage.src = '';
        
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
            
            listenToQueue(promptId, clientId, selectedToolId);

        } catch (e) {
            showGenerationError(e.message);
        }
    });

    function listenToQueue(promptId, clientId, toolId) {
        const evtSource = new EventSource(`/api/status?prompt_id=${promptId}&client_id=${clientId}&tool_id=${toolId}`);
        
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
            } else if (data.status === 'executing') {
                generatingTitle.innerText = data.message;
            } else if (data.status === 'preview') {
                const spinner = document.getElementById('loading-spinner');
                const previewContainer = document.getElementById('live-preview-container');
                const previewImage = document.getElementById('live-preview-image');
                
                if (spinner) spinner.classList.add('hidden');
                if (previewContainer) {
                    previewContainer.classList.remove('hidden');
                    setTimeout(() => previewContainer.classList.add('opacity-100'), 10);
                }
                if (previewImage) {
                    previewImage.src = 'data:image/jpeg;base64,' + data.image;
                }
            } else if (data.status === 'progress') {
                progressContainer.classList.remove('hidden');
                queueStatus.classList.add('hidden');

                const typeLabel = currentOutputType === 'video' ? 'Video' : currentOutputType === 'audio' ? 'Audio' : 'Image';
                generatingTitle.innerText = `Generating ${typeLabel}...`;
                
                const percent = Math.round((data.value / data.max) * 100);
                progressBarFill.style.width = `${percent}%`;
                progressPercentage.innerText = `${percent}%`;
                progressSteps.innerText = `${data.value} / ${data.max}`;
                
            } else if (data.status === 'completed') {
                evtSource.close();
                fetchAndShowResult(promptId);
            } else if (data.status === 'error') {
                evtSource.close();
                showGenerationError(data.detail || "An error occurred during generation.");
            }
        };

        evtSource.onerror = (err) => {
            evtSource.close();
            fetchAndShowResult(promptId).catch(() => {
                showGenerationError("Lost connection to server.");
            });
        };
    }

    async function fetchAndShowResult(promptId) {
        const generatingTitle = document.getElementById('generating-title');
        const typeLabel = currentOutputType === 'video' ? 'Video' : currentOutputType === 'audio' ? 'Audio' : 'Image';
        
        try {
            generatingTitle.innerText = `Finalizing ${typeLabel}...`;
            document.getElementById('queue-status').classList.remove('hidden');
            document.getElementById('queue-status').innerText = currentOutputType === 'image' ? 'Stripping metadata' : 'Preparing file';
            
            const outputRes = await fetch(`/api/output?prompt_id=${promptId}&type=${currentOutputType}`);
            if(!outputRes.ok) throw new Error(`${typeLabel} not found`);
            
            const blob = await outputRes.blob();
            const url = URL.createObjectURL(blob);
            
            // Reset all result elements
            resultImage.classList.add('hidden');
            resultVideo.classList.add('hidden');
            resultAudio.classList.add('hidden');
            resultImage.src = '';
            resultVideo.src = '';
            resultAudio.src = '';

            // File extension and download label
            let ext = '.jpg';
            let downloadLabel = 'Download Image';

            if (currentOutputType === 'video') {
                resultVideo.src = url;
                resultVideo.classList.remove('hidden');
                ext = '.mp4';
                downloadLabel = 'Download Video';
            } else if (currentOutputType === 'audio') {
                resultAudio.src = url;
                resultAudio.classList.remove('hidden');
                ext = '.flac';
                downloadLabel = 'Download Audio';
            } else {
                resultImage.src = url;
                resultImage.classList.remove('hidden');
                ext = '.jpg';
                downloadLabel = 'Download Image';
            }

            downloadBtnText.innerText = downloadLabel;
            
            generatingLayer.classList.add('hidden');
            generatingLayer.classList.remove('flex');
            resultLayer.classList.remove('hidden');
            resultLayer.classList.add('flex');

            // Setup download
            downloadBtn.onclick = () => {
                const a = document.createElement('a');
                a.href = url;
                a.download = `creation-${promptId.substring(0,8)}${ext}`;
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
            };

        } catch (e) {
            showGenerationError(`Failed to fetch final ${typeLabel.toLowerCase()}. It might have failed on the server.`);
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
        // Stop video/audio playback
        resultVideo.pause();
        resultAudio.pause();
    });

    // AI Status Polling
    const aiStatusDot = document.getElementById('ai-status-dot');
    const aiStatusText = document.getElementById('ai-status-text');

    async function checkAiStatus() {
        try {
            const res = await fetch('/api/health');
            if(res.ok) {
                const resData = await res.json();
                aiStatusDot.className = 'w-2 h-2 rounded-full bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.5)]';
                aiStatusText.innerText = 'AI Ready';
                generateBtn.disabled = false;
                generateBtn.classList.remove('opacity-50', 'cursor-not-allowed');
                
                const vramWarning = document.getElementById('vram-warning');
                if (vramWarning) {
                    if (resData.vram_warning) {
                        vramWarning.classList.remove('hidden');
                    } else {
                        vramWarning.classList.add('hidden');
                    }
                }
            } else {
                aiStatusDot.className = 'w-2 h-2 rounded-full bg-red-500 shadow-[0_0_8px_rgba(239,68,68,0.5)] animate-pulse';
                aiStatusText.innerText = 'AI Offline';
                generateBtn.disabled = true;
                generateBtn.classList.add('opacity-50', 'cursor-not-allowed');
            }
        } catch(e) {
            aiStatusDot.className = 'w-2 h-2 rounded-full bg-red-500 shadow-[0_0_8px_rgba(239,68,68,0.5)] animate-pulse';
            aiStatusText.innerText = 'AI Offline';
            generateBtn.disabled = true;
            generateBtn.classList.add('opacity-50', 'cursor-not-allowed');
        }
    }

    // Check immediately and then every 10 seconds
    if (aiStatusDot && aiStatusText) {
        checkAiStatus();
        setInterval(checkAiStatus, 10000);
    }
});
