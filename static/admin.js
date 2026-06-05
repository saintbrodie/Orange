lucide.createIcons();

        window.roundTo16 = function(el) {
            let val = parseInt(el.value);
            if (isNaN(val)) return;
            el.value = Math.round(val / 16) * 16;
        };

        window.handleRatioChange = function(slot) {
            const name = document.getElementById(`setting-ar-slot-${slot}-name`).value;
            const mp = parseFloat(document.getElementById('setting-target-mp').value);
            if (name === 'custom' || isNaN(mp)) return;
            
            // Parse ratio (e.g. "16:9" -> 16/9)
            const parts = name.split(':');
            if (parts.length !== 2) return;
            const wRatio = parseInt(parts[0]);
            const hRatio = parseInt(parts[1]);
            const ratio = wRatio / hRatio;

            // Math: TotalPixels = MP * (1024 * 1024)
            // This multiplier (1048576) aligns 1.0 MP @ 1:1 exactly to 1024x1024
            const totalPixels = mp * 1048576;
            
            // Adjust ratio for common standards (e.g. SDXL/Flux standards)
            let effectiveRatio = ratio;
            if (name === '16:9') effectiveRatio = 1.75;
            else if (name === '9:16') effectiveRatio = 1 / 1.75;
            else if (name === '21:9') effectiveRatio = 2.39;
            else if (name === '9:21') effectiveRatio = 1 / 2.39;
            
            const hRaw = Math.sqrt(totalPixels / effectiveRatio);
            const h = Math.round(hRaw / 16) * 16;
            const w = Math.round((h * effectiveRatio) / 16) * 16;

            // Round to nearest multiple of 16
            document.getElementById(`setting-ar-slot-${slot}-h`).value = h;
            document.getElementById(`setting-ar-slot-${slot}-w`).value = w;
        };

        window.handleMPChange = function() {
            [1, 2, 3].forEach(slot => handleRatioChange(slot));
        };

        window.toggleModifyTool = function() {
            const cb = document.getElementById('setting-modify-enabled');
            const select = document.getElementById('setting-modify-tool');
            const dot = document.getElementById('modify-toggle-dot');
            if (cb.checked) {
                select.disabled = false;
                dot.classList.add('translate-x-3');
                dot.classList.replace('bg-white', 'bg-orange-500');
            } else {
                select.disabled = true;
                select.value = '';
                dot.classList.remove('translate-x-3');
                dot.classList.replace('bg-orange-500', 'bg-white');
            }
        };

        window.toggleGlobalLlm = function() {
            const cb = document.getElementById('setting-llm-enabled');
            const fields = document.getElementById('llm-settings-fields');
            const dot = document.getElementById('llm-toggle-dot');
            if (cb.checked) {
                fields.classList.remove('hidden');
                dot.classList.add('translate-x-3');
                dot.classList.replace('bg-white', 'bg-orange-500');
            } else {
                fields.classList.add('hidden');
                dot.classList.remove('translate-x-3');
                dot.classList.replace('bg-orange-500', 'bg-white');
            }
        };

        window.handleModelSelectChange = function() {
            const select = document.getElementById('setting-llm-model');
            const customContainer = document.getElementById('setting-llm-model-custom-container');
            const customInput = document.getElementById('setting-llm-model-custom');
            if (select.value === '__custom__') {
                customContainer.classList.remove('hidden');
            } else {
                customContainer.classList.add('hidden');
                customInput.value = '';
            }
        };

        window.handleToolModelSelectChange = function() {
            const select = document.getElementById('edit-tool-llm-model');
            const customContainer = document.getElementById('edit-tool-llm-model-custom-container');
            const customInput = document.getElementById('edit-tool-llm-model-custom');
            if (select.value === '__custom__') {
                customContainer.classList.remove('hidden');
            } else {
                customContainer.classList.add('hidden');
                customInput.value = '';
            }
        };

        window.populateModelSelect = function(selectEl, customContainerId, customInputId, provider, activeValue, fetchedModels = []) {
            if (!selectEl) return;
            selectEl.innerHTML = '';
            
            const isOverride = selectEl.id === 'edit-tool-llm-model';
            const defaultOpt = document.createElement('option');
            defaultOpt.value = '';
            defaultOpt.textContent = isOverride ? 'Use default global model' : 'Select a model...';
            selectEl.appendChild(defaultOpt);

            const allModels = Array.from(new Set([...fetchedModels]));

            allModels.forEach(m => {
                const opt = document.createElement('option');
                opt.value = m;
                opt.textContent = m;
                selectEl.appendChild(opt);
            });

            const customOpt = document.createElement('option');
            customOpt.value = '__custom__';
            customOpt.textContent = 'Custom Model...';
            selectEl.appendChild(customOpt);

            const customContainer = document.getElementById(customContainerId);
            const customInput = document.getElementById(customInputId);

            if (!activeValue) {
                selectEl.value = '';
                customContainer.classList.add('hidden');
                customInput.value = '';
            } else if (allModels.includes(activeValue)) {
                selectEl.value = activeValue;
                customContainer.classList.add('hidden');
                customInput.value = '';
            } else {
                selectEl.value = '__custom__';
                customContainer.classList.remove('hidden');
                customInput.value = activeValue;
            }
        };


        const loginContainer = document.getElementById('login-container');
        const dashboardContainer = document.getElementById('dashboard-container');
        const loginBtn = document.getElementById('login-btn');
        const logoutBtn = document.getElementById('logout-btn');
        const adminMenu = document.getElementById('admin-menu');
        const adminKeyInput = document.getElementById('admin-key');
        const loginError = document.getElementById('login-error');

        let currentKey = localStorage.getItem('orange_admin_key');
        let currentPeriod = 'all';
        let currentAnalyticsLogs = [];
        
        let activeFetchedModels = [];

        // Period filter events
        document.querySelectorAll('.period-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                document.querySelectorAll('.period-btn').forEach(b => {
                    b.className = "period-btn px-3 py-1.5 rounded-md text-xs font-medium text-zinc-400 hover:text-zinc-200 transition-colors";
                });
                e.target.className = "period-btn px-3 py-1.5 rounded-md text-xs font-medium bg-zinc-800 text-zinc-100 shadow-sm transition-colors";
                currentPeriod = e.target.getAttribute('data-period');
                if (currentKey) {
                    fetchData(currentKey);
                }
            });
        });

        if (currentKey) {
            fetchData(currentKey);
        }

        loginBtn.addEventListener('click', () => {
            const key = adminKeyInput.value.trim();
            if (!key) return;
            fetchData(key);
        });

        adminKeyInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                loginBtn.click();
            }
        });

        logoutBtn.addEventListener('click', () => {
            localStorage.removeItem('orange_admin_key');
            currentKey = null;
            dashboardContainer.classList.add('hidden');
            settingsContainer.classList.add('hidden');
            toolsContainer.classList.add('hidden');
            if(galleryContainer) galleryContainer.classList.add('hidden');
            logoutBtn.classList.add('hidden');
            adminMenu.classList.add('hidden');
            adminMenu.classList.remove('flex');
            loginContainer.classList.remove('hidden');
            adminKeyInput.value = '';
        });

        async function fetchData(key) {
            const originalBtnText = loginBtn.innerHTML;
            loginBtn.innerHTML = '<i data-lucide="loader-2" class="w-5 h-5 animate-spin"></i> Authenticating...';
            lucide.createIcons();

            try {
                const res = await fetch('/api/admin/usage?period=' + currentPeriod, {
                    headers: { 'Authorization': 'Bearer ' + key }
                });
                if (res.status === 401) {
                    throw new Error("Unauthorized");
                }
                const data = await res.json();

                // Login Success
                localStorage.setItem('orange_admin_key', key);
                currentKey = key;
                loginError.classList.add('hidden');

                if (!loginContainer.classList.contains('hidden')) {
                    loginContainer.classList.add('hidden');
                    logoutBtn.classList.remove('hidden');
                    adminMenu.classList.remove('hidden');
                    adminMenu.classList.add('flex');
                    const savedTab = localStorage.getItem('orange_admin_tab') || 'general';
                    const tabMap = { general: tabGeneral, tools: tabTools, analytics: tabAnalytics, gallery: document.getElementById('tab-gallery') };
                    (tabMap[savedTab] || tabGeneral).click();
                }

                renderDashboard(data);
            } catch (e) {
                loginError.classList.remove('hidden');
                localStorage.removeItem('orange_admin_key');
            } finally {
                loginBtn.innerHTML = originalBtnText;
                lucide.createIcons();
            }
        }

        function renderDashboard(data) {
            const { logs, tools_summary, ip_summary } = data;
            currentAnalyticsLogs = logs;

            // Total Gen
            const total = tools_summary.reduce((acc, curr) => acc + curr.count, 0);
            document.getElementById('total-count').innerText = total;

            // Tools list
            const toolsList = document.getElementById('tools-list');
            toolsList.innerHTML = '';
            tools_summary.sort((a, b) => b.count - a.count).forEach(t => {
                toolsList.innerHTML += `<li class="flex justify-between items-center py-2 border-b border-zinc-800/50 last:border-0"><span class="text-zinc-300 font-medium">${t.tool_id}</span> <strong class="bg-zinc-800/50 text-orange-400 border border-zinc-700/50 px-2 py-1 rounded-md text-xs">${t.count}</strong></li>`;
            });

            // IP list
            const ipList = document.getElementById('ip-list');
            ipList.innerHTML = '';
            ip_summary.sort((a, b) => b.count - a.count).forEach(ip => {
                ipList.innerHTML += `<li class="flex justify-between items-center py-2 border-b border-zinc-800/50 last:border-0"><span class="text-zinc-300 font-mono text-sm">${ip.client_ip}</span> <strong class="bg-zinc-800/50 text-orange-400 border border-zinc-700/50 px-2 py-1 rounded-md text-xs">${ip.count}</strong></li>`;
            });

            // Logs
            const logsBody = document.getElementById('logs-body');
            logsBody.innerHTML = '';
            logs.forEach(log => {
                let localTime = 'Unknown Time';
                try {
                    let ds = log.timestamp.endsWith('Z') ? log.timestamp : log.timestamp + "Z";
                    const d = new Date(ds);
                    localTime = d.toLocaleString();
                } catch (e) { }

                const promptSnippet = log.prompt ? log.prompt : '<em class="text-zinc-600">None</em>';
                logsBody.innerHTML += `
                    <tr class="hover:bg-zinc-800/30 transition-colors">
                        <td class="px-6 py-3 text-zinc-500 font-mono">#${log.id}</td>
                        <td class="px-6 py-3 text-zinc-400">${localTime}</td>
                        <td class="px-6 py-3 font-mono text-zinc-300">${log.client_ip}</td>
                        <td class="px-6 py-3 font-medium text-orange-400">${log.tool_id}</td>
                        <td class="px-6 py-3 text-zinc-400 max-w-xs truncate" title="${log.prompt || ''}">${promptSnippet}</td>
                    </tr>
                `;
            });
        }


        document.getElementById('export-csv-btn').addEventListener('click', async () => {
            const btn = document.getElementById('export-csv-btn');
            const originalBtnText = btn.innerHTML;
            btn.innerHTML = '<i data-lucide="loader-2" class="w-5 h-5 animate-spin inline-block align-text-bottom"></i> Exporting...';
            lucide.createIcons();

            try {
                const res = await adminFetch('/api/admin/usage?period=' + currentPeriod + '&export=true');
                if (!res.ok) throw new Error("Failed to fetch full logs");
                const data = await res.json();
                const logsToExport = data.logs;

                if (!logsToExport || logsToExport.length === 0) {
                    alert('No data to export.');
                    return;
                }

                const headers = ['ID', 'Timestamp', 'Client IP', 'Tool ID', 'Prompt'];

                const escapeCSV = (str) => {
                    if (str === null || str === undefined) return '';
                    const stringified = String(str);
                    if (stringified.includes(',') || stringified.includes('"') || stringified.includes('\n')) {
                        return '"' + stringified.replace(/"/g, '""') + '"';
                    }
                    return stringified;
                };

                const rows = logsToExport.map(log => [
                    escapeCSV(log.id),
                    escapeCSV(log.timestamp),
                    escapeCSV(log.client_ip),
                    escapeCSV(log.tool_id),
                    escapeCSV(log.prompt)
                ]);

                const csvContent = [headers.map(escapeCSV).join(','), ...rows.map(r => r.join(','))].join('\n');

                const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
                const url = URL.createObjectURL(blob);

                const link = document.createElement('a');
                link.setAttribute('href', url);
                link.setAttribute('download', `orange_analytics_${currentPeriod}.csv`);
                link.style.visibility = 'hidden';
                document.body.appendChild(link);
                link.click();
                document.body.removeChild(link);
            } catch (e) {
                alert('Export failed: ' + e);
            } finally {
                btn.innerHTML = originalBtnText;
                lucide.createIcons();
            }
        });


        // Helper for authenticated fetches
        function adminFetch(url, options = {}) {
            options.headers = options.headers || {};
            options.headers['Authorization'] = 'Bearer ' + currentKey;
            return fetch(url, options);
        }

        document.getElementById('backup-db-btn').addEventListener('click', async () => {
            try {
                const res = await adminFetch('/api/admin/db/backup');
                if (!res.ok) throw new Error('Backup failed');
                const blob = await res.blob();
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = 'usage_logs_backup.db';
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                URL.revokeObjectURL(url);
            } catch (e) {
                alert('Backup failed: ' + e.message);
            }
        });

        const restoreInput = document.getElementById('restore-db-input');
        document.getElementById('restore-db-btn').addEventListener('click', () => {
            restoreInput.click();
        });

        restoreInput.addEventListener('change', async (e) => {
            const file = e.target.files[0];
            if (!file) return;

            if (!confirm('Are you sure you want to restore the database? This will overwrite current usage logs.')) {
                e.target.value = '';
                return;
            }

            const formData = new FormData();
            formData.append('file', file);

            try {
                const res = await adminFetch('/api/admin/db/restore', {
                    method: 'POST',
                    body: formData
                });
                if (res.ok) {
                    alert('Database restored successfully!');
                } else {
                    const data = await res.json();
                    alert('Restore failed: ' + (data.detail || 'Unknown error'));
                }
            } catch (err) {
                alert('Restore failed: ' + err);
            }

            e.target.value = '';
        });

        if(document.getElementById('restore-defaults-btn')) {
            document.getElementById('restore-defaults-btn').addEventListener('click', async () => {
                if (!confirm('Are you sure you want to restore default workflows? This will copy default .json files to your active folder.')) return;
                
                const overwrite = confirm('Do you want to overwrite existing workflows that share the same name as the defaults? (Click Cancel to only restore missing workflows)');
                
                const btn = document.getElementById('restore-defaults-btn');
                const orig = btn.innerHTML;
                btn.innerHTML = '<i data-lucide="loader-2" class="w-4 h-4 animate-spin"></i> Restoring...';
                
                try {
                    const res = await adminFetch(`/api/admin/workflows/restore-defaults?overwrite=${overwrite}`, { method: 'POST' });
                    const data = await res.json();
                    if (res.ok) {
                        alert('Defaults restored successfully! Refreshing tools...');
                        await loadEditorData();
                    } else {
                        alert('Restore failed: ' + data.detail);
                    }
                } catch(e) {
                    alert('Error restoring defaults: ' + e);
                }
                
                btn.innerHTML = orig;
                lucide.createIcons();
            });
        }

        // LLM Provider Base URL Defaults & Fetching Logic
        const llmDefaults = {
            openai: "https://api.openai.com/v1",
            ollama: "http://127.0.0.1:11434",
            gemini: "https://generativelanguage.googleapis.com",
            anthropic: "https://api.anthropic.com"
        };

        if (document.getElementById('setting-llm-provider')) {
            document.getElementById('setting-llm-provider').addEventListener('change', (e) => {
                const provider = e.target.value;
                const urlInput = document.getElementById('setting-llm-baseurl');
                const currentUrl = urlInput.value.trim();
                
                const defaultUrls = Object.values(llmDefaults);
                if (!currentUrl || defaultUrls.includes(currentUrl)) {
                    urlInput.value = llmDefaults[provider] || '';
                }

                // Re-populate global model select with presets for the new provider
                populateModelSelect(
                    document.getElementById('setting-llm-model'),
                    'setting-llm-model-custom-container',
                    'setting-llm-model-custom',
                    provider,
                    document.getElementById('setting-llm-model').value,
                    activeFetchedModels
                );
            });
        }

        if (document.getElementById('setting-llm-model')) {
            document.getElementById('setting-llm-model').addEventListener('change', handleModelSelectChange);
        }
        if (document.getElementById('edit-tool-llm-model')) {
            document.getElementById('edit-tool-llm-model').addEventListener('change', handleToolModelSelectChange);
        }

        if (document.getElementById('fetch-models-btn')) {
            document.getElementById('fetch-models-btn').addEventListener('click', async (e) => {
                e.preventDefault();
                const btn = document.getElementById('fetch-models-btn');
                const provider = document.getElementById('setting-llm-provider').value;
                const baseUrl = document.getElementById('setting-llm-baseurl').value.trim();
                const apiKey = document.getElementById('setting-llm-apikey').value.trim();
                
                const origHTML = btn.innerHTML;
                btn.innerHTML = '<i data-lucide="loader-2" class="w-3.5 h-3.5 animate-spin"></i>';
                btn.disabled = true;
                lucide.createIcons();

                try {
                    const res = await adminFetch('/api/admin/llm/models', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ provider, baseUrl, apiKey })
                    });

                    if (!res.ok) {
                        const data = await res.json();
                        throw new Error(data.detail || "Failed to fetch models");
                    }

                    const data = await res.json();
                    if (data.models && data.models.length > 0) {
                        activeFetchedModels = data.models;

                        // Re-populate global model select with active fetched models
                        const currentGlobalModelVal = document.getElementById('setting-llm-model').value === '__custom__'
                            ? document.getElementById('setting-llm-model-custom').value
                            : document.getElementById('setting-llm-model').value;
                        populateModelSelect(
                            document.getElementById('setting-llm-model'),
                            'setting-llm-model-custom-container',
                            'setting-llm-model-custom',
                            provider,
                            currentGlobalModelVal,
                            activeFetchedModels
                        );

                        // If tool is actively editing, also re-populate its override select
                        if (editingToolIndex !== -1) {
                            const activeToolModelVal = document.getElementById('edit-tool-llm-model').value === '__custom__'
                                ? document.getElementById('edit-tool-llm-model-custom').value
                                : document.getElementById('edit-tool-llm-model').value;
                            populateModelSelect(
                                document.getElementById('edit-tool-llm-model'),
                                'edit-tool-llm-model-custom-container',
                                'edit-tool-llm-model-custom',
                                provider,
                                activeToolModelVal,
                                activeFetchedModels
                            );
                        }

                        alert(`Successfully loaded ${data.models.length} models! Choose one from the dropdown menu.`);
                    } else {
                        alert("No models returned by provider.");
                    }
                } catch (err) {
                    alert("Error fetching models: " + err.message);
                } finally {
                    btn.innerHTML = origHTML;
                    btn.disabled = false;
                    lucide.createIcons();
                }
            });
        }

        // Added Tool Editor JS
        const tabGeneral = document.getElementById('tab-general');
        const tabAnalytics = document.getElementById('tab-analytics');
        const tabTools = document.getElementById('tab-tools');
        const tabGallery = document.getElementById('tab-gallery');
        const settingsContainer = document.getElementById('settings-container');
        const toolsContainer = document.getElementById('tools-container');
        const galleryContainer = document.getElementById('gallery-container');

        const galleryModal = document.getElementById('gallery-modal');
        const galleryModalClose = document.getElementById('gallery-modal-close');
        const galleryModalPrev = document.getElementById('gallery-modal-prev');
        const galleryModalNext = document.getElementById('gallery-modal-next');
        const galleryModalMediaContainer = document.getElementById('gallery-modal-media-container');
        const galleryModalAnalytics = document.getElementById('gallery-modal-analytics');
        const galleryModalDownload = document.getElementById('gallery-modal-download');
        const galleryModalOpen = document.getElementById('gallery-modal-open');
        const galleryModalDelete = document.getElementById('gallery-modal-delete');

        let rawGalleryItems = [];
        let filteredGalleryItems = [];
        let galleryGroups = [];
        let currentGalleryIndex = 0;
        let renderedGroupsCount = 0;
        let selectedPromptIds = new Set();
        let lastSelectedGlobalIndex = null;
        const GROUPS_PER_PAGE = 3;
        
        const galleryToolFilter = document.getElementById('gallery-tool-filter');
        const galleryLoadingSentinel = document.getElementById('gallery-loading-sentinel');

        let appConfig = null;
        let availableWorkflowFiles = [];
        let editingToolIndex = -1;
        let parsedNodes = {}; // Cache of nodes from currently selected workflow json
        const MAPPING_TYPES = ['prompt', 'image', 'image2', 'resolution', 'seed', 'outputText'];

        function resetTabs() {
            const defaultClass = "admin-tab flex items-center gap-2 text-zinc-400 hover:text-zinc-200 px-4 py-2 rounded-lg text-sm font-medium transition";
            tabGeneral.className = defaultClass;
            tabTools.className = defaultClass;
            tabAnalytics.className = defaultClass;
            if(tabGallery) tabGallery.className = defaultClass;

            settingsContainer.classList.add('hidden');
            toolsContainer.classList.add('hidden');
            dashboardContainer.classList.add('hidden');
            if(galleryContainer) {
                galleryContainer.classList.add('hidden');
                galleryContainer.classList.remove('flex');
            }
        }

        const activeClass = "admin-tab active flex items-center gap-2 bg-zinc-800 text-orange-400 px-4 py-2 rounded-lg text-sm font-medium shadow-sm border border-zinc-700 transition";

        tabGeneral.addEventListener('click', async () => {
            resetTabs();
            tabGeneral.className = activeClass;
            settingsContainer.classList.remove('hidden');
            localStorage.setItem('orange_admin_tab', 'general');
            await loadEditorData();
        });

        tabTools.addEventListener('click', async () => {
            resetTabs();
            tabTools.className = activeClass;
            toolsContainer.classList.remove('hidden');
            localStorage.setItem('orange_admin_tab', 'tools');
            await loadEditorData();
        });

        tabAnalytics.addEventListener('click', () => {
            resetTabs();
            tabAnalytics.className = activeClass;
            dashboardContainer.classList.remove('hidden');
            localStorage.setItem('orange_admin_tab', 'analytics');
        });

        if(tabGallery) {
            tabGallery.addEventListener('click', async () => {
                resetTabs();
                tabGallery.className = activeClass;
                galleryContainer.classList.remove('hidden');
                galleryContainer.classList.add('flex');
                localStorage.setItem('orange_admin_tab', 'gallery');
                await loadGallery();
            });
        }
        
        if(document.getElementById('refresh-gallery-btn')) {
            document.getElementById('refresh-gallery-btn').addEventListener('click', loadGallery);
        }

        async function loadGallery() {
            const empty = document.getElementById('gallery-empty');
            const btn = document.getElementById('refresh-gallery-btn');
            
            btn.innerHTML = '<i data-lucide="loader-2" class="w-4 h-4 animate-spin"></i> Loading...';
            lucide.createIcons();
            
            try {
                const res = await adminFetch('/api/admin/media');
                if (res.ok) {
                    const data = await res.json();
                    if (data.media && data.media.length > 0) {
                        rawGalleryItems = data.media;
                        
                        // Populate tool filter dropdown
                        const tools = new Set();
                        rawGalleryItems.forEach(item => {
                            if (item.analytics && item.analytics.tool_id) {
                                tools.add(item.analytics.tool_id);
                            }
                        });
                        
                        const currentVal = galleryToolFilter.value;
                        galleryToolFilter.innerHTML = '<option value="all">All Tools</option>';
                        Array.from(tools).sort().forEach(t => {
                            const opt = document.createElement('option');
                            opt.value = t;
                            opt.textContent = t;
                            galleryToolFilter.appendChild(opt);
                        });
                        if (tools.has(currentVal)) {
                            galleryToolFilter.value = currentVal;
                        }
                        
                        applyGalleryFilters();
                    } else {
                        rawGalleryItems = [];
                        applyGalleryFilters();
                    }
                }
            } catch (e) {
                console.error("Gallery load error", e);
            }
            
            btn.innerHTML = '<i data-lucide="refresh-cw" class="w-4 h-4"></i> Refresh';
            lucide.createIcons();
        }

        function updateBulkActionsUI() {
            const bar = document.getElementById('gallery-bulk-actions');
            const countEl = document.getElementById('bulk-select-count');
            const count = selectedPromptIds.size;
            
            if (count > 0) {
                bar.classList.remove('hidden');
                bar.classList.add('flex');
                countEl.innerText = `${count} Items Selected`;
            } else {
                bar.classList.add('hidden');
                bar.classList.remove('flex');
            }
        }

        function renderSelectionStates() {
            // Find all gallery items and update their visual state
            document.querySelectorAll('[data-prompt-id]').forEach(el => {
                const pid = el.getAttribute('data-prompt-id');
                const checkbox = el.querySelector('.gallery-item-checkbox');
                if (selectedPromptIds.has(pid)) {
                    el.classList.add('border-orange-500', 'bg-orange-500/10');
                    el.classList.remove('border-zinc-800');
                    if(checkbox) checkbox.checked = true;
                } else {
                    el.classList.remove('border-orange-500', 'bg-orange-500/10');
                    el.classList.add('border-zinc-800');
                    if(checkbox) checkbox.checked = false;
                }
            });
        }

        window.toggleSelect = function(globalIndex, event) {
            if (event) event.stopPropagation();
            const item = filteredGalleryItems[globalIndex];
            const isSelected = selectedPromptIds.has(item.prompt_id);
            
            if (event && event.shiftKey && lastSelectedGlobalIndex !== null) {
                const start = Math.min(globalIndex, lastSelectedGlobalIndex);
                const end = Math.max(globalIndex, lastSelectedGlobalIndex);
                // If the one we just clicked was selected, we are range selecting ON
                // If it was unselected, we are range selecting OFF
                // But usually shift-click is for ADDING to selection
                for (let i = start; i <= end; i++) {
                    selectedPromptIds.add(filteredGalleryItems[i].prompt_id);
                }
            } else {
                if (isSelected) {
                    selectedPromptIds.delete(item.prompt_id);
                } else {
                    selectedPromptIds.add(item.prompt_id);
                }
            }
            
            lastSelectedGlobalIndex = globalIndex;
            updateBulkActionsUI();
            renderSelectionStates();
        };

        window.toggleGroupSelect = function(groupIndex, event) {
            if(event) event.stopPropagation();
            const group = galleryGroups[groupIndex];
            const allSelected = group.items.every(item => selectedPromptIds.has(item.prompt_id));
            if (allSelected) {
                group.items.forEach(item => selectedPromptIds.delete(item.prompt_id));
            } else {
                group.items.forEach(item => selectedPromptIds.add(item.prompt_id));
            }
            updateBulkActionsUI();
            renderSelectionStates();
        };

        if(document.getElementById('bulk-clear-btn')) {
            document.getElementById('bulk-clear-btn').addEventListener('click', () => {
                selectedPromptIds.clear();
                updateBulkActionsUI();
                renderSelectionStates();
            });
        }

        if(document.getElementById('bulk-delete-btn')) {
            document.getElementById('bulk-delete-btn').addEventListener('click', async () => {
                const count = selectedPromptIds.size;
                if (!confirm(`Are you sure you want to delete ${count} selected generations?`)) return;
                
                const btn = document.getElementById('bulk-delete-btn');
                const origHTML = btn.innerHTML;
                btn.innerHTML = '<i data-lucide="loader-2" class="w-4 h-4 animate-spin"></i> Deleting...';
                btn.disabled = true;
                
                try {
                    const res = await adminFetch('/api/admin/bulk-delete', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ prompt_ids: Array.from(selectedPromptIds) })
                    });
                    if (res.ok) {
                        selectedPromptIds.clear();
                        updateBulkActionsUI();
                        loadGallery(); // Full refresh
                    } else {
                        alert("Bulk delete failed.");
                    }
                } catch(e) { alert("Error during bulk delete."); }
                
                btn.innerHTML = origHTML;
                btn.disabled = false;
                lucide.createIcons();
            });
        }

        function applyGalleryFilters() {
            const filterVal = galleryToolFilter.value;
            const empty = document.getElementById('gallery-empty');
            const grid = document.getElementById('gallery-grid');
            
            if (filterVal === 'all') {
                filteredGalleryItems = [...rawGalleryItems];
            } else {
                filteredGalleryItems = rawGalleryItems.filter(i => i.analytics && i.analytics.tool_id === filterVal);
            }
            
            if (filteredGalleryItems.length === 0) {
                grid.innerHTML = '';
                galleryGroups = [];
                if(galleryLoadingSentinel) galleryLoadingSentinel.classList.add('hidden');
                empty.classList.remove('hidden');
                empty.classList.add('flex');
                return;
            }
            
            empty.classList.add('hidden');
            empty.classList.remove('flex');
            
            const groupsMap = {};
            filteredGalleryItems.forEach((item, index) => {
                let dateStr = 'Unknown Date';
                if (item.analytics && item.analytics.timestamp) {
                    try {
                        const d = new Date(item.analytics.timestamp.endsWith('Z') ? item.analytics.timestamp : item.analytics.timestamp + "Z");
                        const today = new Date();
                        const yesterday = new Date(today);
                        yesterday.setDate(yesterday.getDate() - 1);
                        
                        if (d.toDateString() === today.toDateString()) {
                            dateStr = 'Today';
                        } else if (d.toDateString() === yesterday.toDateString()) {
                            dateStr = 'Yesterday';
                        } else {
                            dateStr = d.toLocaleDateString(undefined, { month: 'long', day: 'numeric', year: 'numeric' });
                        }
                    } catch(e) {}
                }
                if (!groupsMap[dateStr]) groupsMap[dateStr] = [];
                groupsMap[dateStr].push({ ...item, globalIndex: index });
            });
            
            galleryGroups = Object.keys(groupsMap).map(k => ({ label: k, items: groupsMap[k] }));
            
            grid.innerHTML = '';
            renderedGroupsCount = 0;
            renderNextGalleryGroups();
        }

        function renderNextGalleryGroups() {
            if (renderedGroupsCount >= galleryGroups.length) {
                if(galleryLoadingSentinel) galleryLoadingSentinel.classList.add('hidden');
                return;
            }
            
            const grid = document.getElementById('gallery-grid');
            const limit = Math.min(renderedGroupsCount + GROUPS_PER_PAGE, galleryGroups.length);
            
            for (let i = renderedGroupsCount; i < limit; i++) {
                const group = galleryGroups[i];
                let groupHtml = `<div class="space-y-4 animate-in fade-in duration-500">
                    <h3 class="text-sm font-semibold text-zinc-400 border-b border-zinc-800 pb-2 flex justify-between items-center cursor-pointer hover:text-zinc-200 transition-colors group/header" onclick="toggleGroupSelect(${i}, event)">
                        <span>${group.label}</span>
                        <span class="text-[10px] uppercase tracking-widest opacity-0 group-hover/header:opacity-50 transition-opacity font-bold">Click to select all</span>
                    </h3>
                    <div class="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-3">
                `;
                
                group.items.forEach(item => {
                    let mediaEl = '';
                    const url = `/api/output?prompt_id=${item.prompt_id}&type=${item.type}`;
                    
                    if (item.type === 'video') {
                        mediaEl = `<video src="${url}" class="w-full h-full object-cover rounded-xl" autoplay loop muted playsinline></video>`;
                    } else if (item.type === 'audio') {
                        mediaEl = `
                            <div class="w-full h-full flex flex-col items-center justify-center bg-zinc-800 rounded-xl p-4 gap-2">
                                <i data-lucide="music" class="w-6 h-6 text-orange-500"></i>
                            </div>
                        `;
                    } else {
                        mediaEl = `<img src="${url}" class="w-full h-full object-cover rounded-xl shadow-lg border border-zinc-800/50" loading="lazy">`;
                    }
                    
                    const isSelected = selectedPromptIds.has(item.prompt_id);
                    groupHtml += `
                        <div class="aspect-square relative group overflow-hidden rounded-xl bg-zinc-900 border ${isSelected ? 'border-orange-500 bg-orange-500/10' : 'border-zinc-800'} hover:border-orange-500/50 transition-colors cursor-pointer" 
                             data-prompt-id="${item.prompt_id}"
                             onclick="openGalleryModal(${item.globalIndex})">
                            ${mediaEl}
                            
                            <!-- Checkbox Overlay -->
                            <div class="absolute top-2 left-2 z-10 opacity-0 group-hover:opacity-100 transition-opacity ${isSelected ? 'opacity-100' : ''}">
                                <input type="checkbox" class="gallery-item-checkbox w-5 h-5 rounded border-zinc-700 bg-zinc-900 text-orange-600 focus:ring-orange-500 focus:ring-offset-zinc-900 transition-all cursor-pointer" 
                                       ${isSelected ? 'checked' : ''} 
                                       onclick="toggleSelect(${item.globalIndex}, event)">
                            </div>

                            <div class="absolute inset-0 bg-gradient-to-t from-black/80 via-black/0 to-black/0 opacity-0 group-hover:opacity-100 transition-opacity flex flex-col justify-end p-2 pointer-events-none">
                                <span class="text-[10px] font-mono text-zinc-300 truncate">${item.filename || item.prompt_id}</span>
                            </div>
                        </div>
                    `;
                });
                
                groupHtml += `</div></div>`;
                const wrapper = document.createElement('div');
                wrapper.innerHTML = groupHtml;
                grid.appendChild(wrapper.firstElementChild);
            }
            
            renderedGroupsCount = limit;
            lucide.createIcons();
            
            if (renderedGroupsCount < galleryGroups.length) {
                if(galleryLoadingSentinel) galleryLoadingSentinel.classList.remove('hidden');
            } else {
                if(galleryLoadingSentinel) galleryLoadingSentinel.classList.add('hidden');
            }
        }

        if(galleryToolFilter) {
            galleryToolFilter.addEventListener('change', applyGalleryFilters);
        }

        // Setup Intersection Observer for Infinite Scroll
        if (galleryLoadingSentinel) {
            const observer = new IntersectionObserver((entries) => {
                if (entries[0].isIntersecting) {
                    renderNextGalleryGroups();
                }
            }, { rootMargin: '200px' });
            observer.observe(galleryLoadingSentinel);
        }

        window.openGalleryModal = function(index) {
            if (index < 0 || index >= filteredGalleryItems.length) return;
            currentGalleryIndex = index;
            const item = filteredGalleryItems[index];
            const url = `/api/output?prompt_id=${item.prompt_id}&type=${item.type}`;
            
            let mediaEl = '';
            if (item.type === 'video') {
                mediaEl = `<video src="${url}" class="max-w-full max-h-full object-contain rounded-lg shadow-lg" autoplay loop muted playsinline controls></video>`;
            } else if (item.type === 'audio') {
                mediaEl = `<audio src="${url}" controls class="w-full max-w-sm"></audio>`;
            } else {
                mediaEl = `<img src="${url}" class="max-w-full max-h-full object-contain rounded-lg shadow-lg">`;
            }
            galleryModalMediaContainer.innerHTML = mediaEl;
            
            let analyticsHtml = '';
            if (item.analytics) {
                const a = item.analytics;
                let localTime = 'Unknown';
                try {
                    localTime = new Date(a.timestamp.endsWith('Z') ? a.timestamp : a.timestamp + "Z").toLocaleString();
                } catch(e){}
                
                let backendDisplay = a.backend_url || 'N/A';
                if (a.backend_url && appConfig && appConfig.comfyServers) {
                    const srv = appConfig.comfyServers.find(s => s.url === a.backend_url);
                    if (srv) backendDisplay = `Server ${srv.priority} (${a.backend_url})`;
                }
                
                analyticsHtml = `
                    <div class="space-y-1">
                        <label class="text-[10px] text-zinc-500 uppercase font-bold tracking-wider">Timestamp</label>
                        <div class="text-zinc-300 font-mono text-xs bg-zinc-950 p-2 rounded border border-zinc-800">${localTime}</div>
                    </div>
                    <div class="space-y-1">
                        <label class="text-[10px] text-zinc-500 uppercase font-bold tracking-wider">Client IP</label>
                        <div class="text-zinc-300 font-mono text-xs bg-zinc-950 p-2 rounded border border-zinc-800">${a.client_ip || 'N/A'}</div>
                    </div>
                    <div class="space-y-1">
                        <label class="text-[10px] text-zinc-500 uppercase font-bold tracking-wider">Tool ID</label>
                        <div class="text-orange-400 font-medium text-xs bg-zinc-950 p-2 rounded border border-zinc-800">${a.tool_id || 'N/A'}</div>
                    </div>
                    <div class="space-y-1">
                        <label class="text-[10px] text-zinc-500 uppercase font-bold tracking-wider">Backend Server</label>
                        <div class="text-zinc-300 font-mono text-xs bg-zinc-950 p-2 rounded border border-zinc-800">${backendDisplay}</div>
                    </div>
                    <div class="space-y-1">
                        <label class="text-[10px] text-zinc-500 uppercase font-bold tracking-wider">Prompt</label>
                        <div class="text-zinc-300 text-xs bg-zinc-950 p-2 rounded border border-zinc-800 max-h-40 overflow-y-auto whitespace-pre-wrap">${a.prompt || 'None'}</div>
                    </div>
                `;
            } else {
                analyticsHtml = `<div class="text-zinc-500 text-center py-4 italic">No analytics data found for this generation.</div>`;
            }
            
            galleryModalAnalytics.innerHTML = analyticsHtml;
            galleryModalDownload.href = url;
            galleryModalOpen.href = url;
            
            galleryModal.classList.remove('hidden');
            document.body.style.overflow = 'hidden';
            
            galleryModalPrev.style.display = index > 0 ? 'block' : 'none';
            galleryModalNext.style.display = index < filteredGalleryItems.length - 1 ? 'block' : 'none';
        };

        window.closeGalleryModal = function() {
            galleryModal.classList.add('hidden');
            document.body.style.overflow = '';
            galleryModalMediaContainer.innerHTML = '';
        };

        if(galleryModalClose) {
            galleryModalClose.addEventListener('click', closeGalleryModal);
            galleryModal.addEventListener('click', closeGalleryModal);
            galleryModalPrev.addEventListener('click', (e) => { e.stopPropagation(); openGalleryModal(currentGalleryIndex - 1); });
            galleryModalNext.addEventListener('click', (e) => { e.stopPropagation(); openGalleryModal(currentGalleryIndex + 1); });
            
            document.addEventListener('keydown', (e) => {
                if (!galleryModal.classList.contains('hidden')) {
                    if (e.key === 'Escape') closeGalleryModal();
                    if (e.key === 'ArrowLeft') openGalleryModal(currentGalleryIndex - 1);
                    if (e.key === 'ArrowRight') openGalleryModal(currentGalleryIndex + 1);
                }
            });
        }

        if (galleryModalDelete) {
            galleryModalDelete.addEventListener('click', async (e) => {
                e.stopPropagation();
                const item = filteredGalleryItems[currentGalleryIndex];
                if (!confirm("Are you sure you want to delete this generation from history?")) return;
                
                galleryModalDelete.innerHTML = '<i data-lucide="loader-2" class="w-4 h-4 animate-spin"></i> Deleting...';
                lucide.createIcons();

                try {
                    const res = await adminFetch(`/api/admin/media/${item.prompt_id}`, { method: 'DELETE' });
                    if (res.ok) {
                        closeGalleryModal();
                        loadGallery(); // Refresh gallery
                    } else {
                        alert("Failed to delete.");
                    }
                } catch(e) { alert("Error deleting."); }
                
                galleryModalDelete.innerHTML = '<i data-lucide="trash-2" class="w-4 h-4"></i> Delete Generation';
                lucide.createIcons();
            });
        }

        async function loadEditorData() {
            try {
                // Config
                const cRes = await adminFetch('/api/admin/config');
                if (cRes.ok) {
                    appConfig = await cRes.json();

                    // Populate General Settings
                    if (!appConfig.comfyServers) {
                        appConfig.comfyServers = [];
                        if (appConfig.comfyServerUrl) {
                            appConfig.comfyServers.push({ url: appConfig.comfyServerUrl, priority: 1 });
                            delete appConfig.comfyServerUrl;
                        }
                    }
                    renderComfyServers();

                    document.getElementById('setting-admin-key').value = appConfig.adminKey || '';
                    document.getElementById('setting-target-mp').value = appConfig.targetMegapixels || '1.0';

                    // Populate global LLM settings
                    const llm = appConfig.llm || {};
                    document.getElementById('setting-llm-enabled').checked = !!llm.enabled;
                    document.getElementById('setting-llm-provider').value = llm.provider || 'openai';
                    document.getElementById('setting-llm-baseurl').value = llm.baseUrl || '';
                    document.getElementById('setting-llm-apikey').value = llm.apiKey || '';
                    
                    try {
                        const gpRes = await adminFetch('/api/admin/prompts/global');
                        if (gpRes.ok) {
                            const gpData = await gpRes.json();
                            document.getElementById('setting-llm-systemprompt').value = gpData.prompt || '';
                        } else {
                            document.getElementById('setting-llm-systemprompt').value = '';
                        }
                    } catch(e) {
                        document.getElementById('setting-llm-systemprompt').value = '';
                    }

                    populateModelSelect(
                        document.getElementById('setting-llm-model'),
                        'setting-llm-model-custom-container',
                        'setting-llm-model-custom',
                        llm.provider || 'openai',
                        llm.model || '',
                        activeFetchedModels
                    );

                    toggleGlobalLlm();

                    if (appConfig.aspectRatios) {
                        const keys = Object.keys(appConfig.aspectRatios);
                        [1, 2, 3].forEach((slot, i) => {
                            const key = keys[i];
                            const select = document.getElementById(`setting-ar-slot-${slot}-name`);
                            const hInput = document.getElementById(`setting-ar-slot-${slot}-h`);
                            const wInput = document.getElementById(`setting-ar-slot-${slot}-w`);
                            
                            if (key) {
                                // Find if this key is in our preset list
                                let found = false;
                                for (let opt of select.options) {
                                    if (opt.value === key) {
                                        select.value = key;
                                        found = true;
                                        break;
                                    }
                                }
                                if (!found) select.value = 'custom';
                                
                                hInput.value = appConfig.aspectRatios[key].height;
                                wInput.value = appConfig.aspectRatios[key].width;
                            }
                        });
                    }

                    // Populate Modify Image Tool dropdown
                    const modifySelect = document.getElementById('setting-modify-tool');
                    const modifyCb = document.getElementById('setting-modify-enabled');
                    const modifyDot = document.getElementById('modify-toggle-dot');
                    modifySelect.innerHTML = '<option value="">Select a tool...</option>';
                    // Only show tools that accept image input
                    (appConfig.tools || []).forEach(t => {
                        if (t.nodeMapping && t.nodeMapping.image) {
                            modifySelect.innerHTML += `<option value="${t.id}">${t.name} (${t.id})</option>`;
                        }
                    });
                    if (appConfig.modifyTool) {
                        modifyCb.checked = true;
                        modifySelect.disabled = false;
                        modifySelect.value = appConfig.modifyTool;
                        modifyDot.classList.add('translate-x-3');
                        modifyDot.classList.replace('bg-white', 'bg-orange-500');
                    } else {
                        modifyCb.checked = false;
                        modifySelect.disabled = true;
                        modifyDot.classList.remove('translate-x-3');
                        modifyDot.classList.replace('bg-orange-500', 'bg-white');
                    }
                }

                // Workflows
                const wRes = await adminFetch('/api/admin/workflows');
                if (wRes.ok) {
                    const data = await wRes.json();
                    availableWorkflowFiles = data.files || [];
                }

                renderToolsList();
                updateWorkflowDropdown();
            } catch (e) { console.error("Error loading tools data."); }
        }

        let draggedItemIndex = null;
        let dragSourceNode = null;

        function handleDragStart(e) {
            const node = e.target.closest('[draggable]');
            dragSourceNode = node;
            draggedItemIndex = Array.from(node.parentNode.children).indexOf(node);
            e.dataTransfer.effectAllowed = 'move';
            // Use a small timeout to allow the drag image to be created before we change the style
            setTimeout(() => { if (dragSourceNode) dragSourceNode.classList.add('opacity-10'); }, 0);
        }

        function handleDragOver(e) {
            e.preventDefault();
            e.dataTransfer.dropEffect = 'move';
            
            const targetNode = e.target.closest('[draggable]');
            if (!targetNode || targetNode === dragSourceNode || !dragSourceNode) return;
            
            const list = dragSourceNode.parentNode;
            const overIndex = Array.from(list.children).indexOf(targetNode);
            draggedItemIndex = Array.from(list.children).indexOf(dragSourceNode);
            
            if (draggedItemIndex === overIndex) return;
            
            // Move item in array in real-time
            const tools = appConfig.tools;
            const movedItem = tools.splice(draggedItemIndex, 1)[0];
            tools.splice(overIndex, 0, movedItem);
            
            // Move DOM node
            const isMovingDown = draggedItemIndex < overIndex;
            if (isMovingDown) {
                list.insertBefore(dragSourceNode, targetNode.nextSibling);
            } else {
                list.insertBefore(dragSourceNode, targetNode);
            }
            
            // Maintain selection
            const selectedToolId = appConfig.tools[editingToolIndex]?.id;
            if (selectedToolId) {
                editingToolIndex = appConfig.tools.findIndex(t => t.id === selectedToolId);
            }
        }

        function handleDragLeave(e) { }

        function handleDragEnd(e) {
            if (dragSourceNode) dragSourceNode.classList.remove('opacity-10');
            dragSourceNode = null;
            draggedItemIndex = null;
            renderToolsList(); // Final cleanup render
        }

        function handleDrop(e) {
            e.preventDefault();
            e.stopPropagation();
            if (dragSourceNode) dragSourceNode.classList.remove('opacity-10');
            dragSourceNode = null;
            draggedItemIndex = null;
            
            renderToolsList(); // Full re-render to ensure classes are correct
            syncToolsOrder();
        }

        function renderToolsList() {
            const list = document.getElementById('admin-tools-list');
            list.innerHTML = '';

            if (!appConfig || !appConfig.tools) return;

            appConfig.tools.forEach((tool, index) => {
                const isSelected = index === editingToolIndex;
                const isDragging = index === draggedItemIndex;
                const activeClass = isSelected ? 'bg-orange-600/20 border-orange-600/50 text-orange-200' : 'bg-zinc-800/40 border-zinc-700 text-zinc-300 hover:bg-zinc-800';
                const draggingClass = isDragging ? 'opacity-10 pointer-events-none' : '';

                list.innerHTML += `
                    <div class="p-3 rounded-xl border ${activeClass} transition flex items-center gap-3 group" 
                         draggable="true" 
                         ondragstart="handleDragStart(event)" 
                         ondragend="handleDragEnd(event)"
                         ondragover="handleDragOver(event)"
                         ondragleave="handleDragLeave(event)"
                         ondrop="handleDrop(event)"
                         onclick="selectTool(${index})">
                        <div class="cursor-grab active:cursor-grabbing text-zinc-600 group-hover:text-zinc-400 transition-colors">
                            <i data-lucide="grip-vertical" class="w-4 h-4"></i>
                        </div>
                        <div class="flex flex-col flex-1 cursor-pointer">
                            <span class="font-medium text-sm">${tool.name}</span>
                            <span class="text-xs opacity-60 font-mono">${tool.id}</span>
                        </div>
                        <i data-lucide="terminal" class="w-4 h-4 opacity-30"></i>
                    </div>
                `;
            });
            lucide.createIcons();
        }

        function updateWorkflowDropdown() {
            const select = document.getElementById('edit-tool-file');
            select.innerHTML = '<option value="">Select workflow...</option>';
            availableWorkflowFiles.forEach(file => {
                select.innerHTML += `<option value="${file}">${file}</option>`;
            });
        }

        document.getElementById('edit-tool-file').addEventListener('change', async (e) => {
            const filename = e.target.value;
            if (!filename) { parsedNodes = {}; return; }
            try {
                const res = await adminFetch(`/api/admin/workflows/${filename}`);
                if (res.ok) {
                    const data = await res.json();
                    const datalist = document.getElementById('nodes-list');
                    datalist.innerHTML = '';
                    parsedNodes = data;
                    Object.keys(data).forEach(nodeId => {
                        const node = data[nodeId];
                        if (node.class_type && node._meta && node._meta.title) {
                            datalist.innerHTML += `<option value="${nodeId}">${nodeId} (${node._meta.title} - ${node.class_type})</option>`;
                        } else {
                            datalist.innerHTML += `<option value="${nodeId}">${nodeId} (${node.class_type})</option>`;
                        }
                    });
                }
            } catch (e) { }
        });

        async function selectTool(index) {
            editingToolIndex = index;
            renderToolsList();
            document.getElementById('tool-editor-empty').classList.add('hidden');
            document.getElementById('tool-editor-form').classList.remove('hidden');
            document.getElementById('tool-editor-form').classList.add('flex');
            document.getElementById('save-status').classList.add('hidden');

            const tool = appConfig.tools[index];
            document.getElementById('edit-tool-id').value = tool.id || '';
            document.getElementById('edit-tool-name').value = tool.name || '';
            document.getElementById('edit-tool-output-type').value = tool.outputType || 'image';
            document.getElementById('edit-tool-file').value = tool.workflowFile || '';

            // Populate tool LLM overrides
            const toolEnhance = tool.promptEnhance || {};
            document.getElementById('edit-tool-llm-enabled').checked = toolEnhance.enabled !== false;
            
            try {
                const tpRes = await adminFetch(`/api/admin/prompts/${encodeURIComponent(tool.id)}`);
                if (tpRes.ok) {
                    const tpData = await tpRes.json();
                    document.getElementById('edit-tool-llm-systemprompt').value = tpData.prompt || '';
                } else {
                    document.getElementById('edit-tool-llm-systemprompt').value = '';
                }
            } catch(e) {
                document.getElementById('edit-tool-llm-systemprompt').value = '';
            }

            const toolProvider = toolEnhance.provider || (appConfig.llm && appConfig.llm.provider) || 'openai';
            populateModelSelect(
                document.getElementById('edit-tool-llm-model'),
                'edit-tool-llm-model-custom-container',
                'edit-tool-llm-model-custom',
                toolProvider,
                toolEnhance.model || '',
                activeFetchedModels
            );

            // Trigger change to load nodes
            if (tool.workflowFile) {
                const ev = new Event('change');
                document.getElementById('edit-tool-file').dispatchEvent(ev);
            }

            renderMappings(tool.nodeMapping || {});
        }

        window.toggleMapping = function (type) {
            const cb = document.getElementById(`map-${type}-enable`);
            const isEnabled = cb.checked;
            const container = document.getElementById(`map-${type}-container`);
            const nodeInput = document.getElementById(`map-${type}-node`);
            const dot = cb.nextElementSibling.nextElementSibling;

            if (isEnabled) {
                container.classList.remove('opacity-50', 'grayscale');
                nodeInput.disabled = false;
                dot.classList.add('translate-x-3');
                dot.classList.replace('bg-white', 'bg-orange-500');
                if (type === 'resolution') {
                    document.getElementById('map-res-wfield').disabled = false;
                    document.getElementById('map-res-hfield').disabled = false;
                    const customArCheckbox = document.getElementById('map-res-custom-ar');
                    if (customArCheckbox) customArCheckbox.disabled = false;
                    Object.keys(appConfig.aspectRatios || {}).forEach(r => {
                        const idSuffix = r.replace(':', '');
                        const arw = document.getElementById(`ar-${idSuffix}-w`);
                        const arh = document.getElementById(`ar-${idSuffix}-h`);
                        if (arw) arw.disabled = false;
                        if (arh) arh.disabled = false;
                    });
                } else {
                    const fieldInput = document.getElementById(`map-${type}-field`);
                    if (fieldInput) fieldInput.disabled = false;
                    const seedRand = document.getElementById('map-seed-rand');
                    if (type === 'seed' && seedRand) seedRand.disabled = false;
                }
            } else {
                container.classList.add('opacity-50', 'grayscale');
                nodeInput.disabled = true;
                dot.classList.remove('translate-x-3');
                dot.classList.replace('bg-orange-500', 'bg-white');
                if (type === 'resolution') {
                    document.getElementById('map-res-wfield').disabled = true;
                    document.getElementById('map-res-hfield').disabled = true;
                    const customArCheckbox = document.getElementById('map-res-custom-ar');
                    if (customArCheckbox) customArCheckbox.disabled = true;
                    Object.keys(appConfig.aspectRatios || {}).forEach(r => {
                        const idSuffix = r.replace(':', '');
                        const arw = document.getElementById(`ar-${idSuffix}-w`);
                        const arh = document.getElementById(`ar-${idSuffix}-h`);
                        if (arw) arw.disabled = true;
                        if (arh) arh.disabled = true;
                    });
                } else {
                    const fieldInput = document.getElementById(`map-${type}-field`);
                    if (fieldInput) fieldInput.disabled = true;
                    const seedRand = document.getElementById('map-seed-rand');
                    if (type === 'seed' && seedRand) seedRand.disabled = true;
                }
            }

            if (type === 'prompt') {
                const overrides = document.getElementById('tool-llm-overrides-container');
                if (isEnabled) {
                    overrides.classList.remove('hidden');
                } else {
                    overrides.classList.add('hidden');
                }
            }
        };

        window.autoDetectField = function (type, nodeId) {
            if (!parsedNodes || !parsedNodes[nodeId]) return;
            const node = parsedNodes[nodeId];
            const classType = node.class_type;

            if (type === 'seed') {
                const field = document.getElementById('map-seed-field');
                if (field && !field.value) {
                    if (classType === 'RandomNoise' || classType === 'KSampler' || classType === 'KSamplerAdvanced') {
                        field.value = 'seed';
                    } else if (classType === 'PrimitiveNode') {
                        field.value = 'value';
                    }
                }
            } else if (type === 'prompt') {
                const field = document.getElementById('map-prompt-field');
                if (field && !field.value) {
                    if (classType === 'CLIPTextEncode') field.value = 'text';
                    else if (classType === 'PrimitiveNode' || classType === 'StringLiteral') field.value = 'value';
                }
            } else if (type === 'image' || type === 'image2') {
                const field = document.getElementById(`map-${type}-field`);
                if (field && !field.value) {
                    if (classType === 'LoadImage') field.value = 'image';
                }
            } else if (type === 'resolution') {
                const wf = document.getElementById('map-res-wfield');
                const hf = document.getElementById('map-res-hfield');
                if (wf && !wf.value && hf && !hf.value) {
                    if (classType.includes('LatentImage') || classType.includes('EmptyLatent')) {
                        wf.value = 'width';
                        hf.value = 'height';
                    }
                }
            }
        };

        function renderMappings(mappings) {
            const container = document.getElementById('node-mappings-container');
            container.innerHTML = '';

            MAPPING_TYPES.forEach(type => {
                let mapData, isEnabled, fieldUI, extraUI = '';

                if (type === 'resolution') {
                    mapData = {
                        nodeId: (mappings.width && mappings.width.nodeId) || (mappings.height && mappings.height.nodeId) || '',
                        wField: (mappings.width && mappings.width.field) || 'width',
                        hField: (mappings.height && mappings.height.field) || 'height'
                    };
                    isEnabled = !!(mappings.width || mappings.height);

                    fieldUI = `
                        <div class="flex-1">
                            <label class="text-[10px] uppercase text-zinc-500 font-bold tracking-wider">Width Field</label>
                            <input type="text" id="map-res-wfield" value="${mapData.wField}" class="w-full bg-zinc-900 border border-zinc-700 rounded-lg p-2 text-sm focus:border-orange-500 outline-none text-zinc-300 font-mono" ${!isEnabled ? 'disabled' : ''}>
                        </div>
                        <div class="flex-1">
                            <label class="text-[10px] uppercase text-zinc-500 font-bold tracking-wider">Height Field</label>
                            <input type="text" id="map-res-hfield" value="${mapData.hField}" class="w-full bg-zinc-900 border border-zinc-700 rounded-lg p-2 text-sm focus:border-orange-500 outline-none text-zinc-300 font-mono" ${!isEnabled ? 'disabled' : ''}>
                        </div>
                    `;

                    const tool = appConfig.tools[editingToolIndex] || {};
                    const ar = tool.aspectRatios || {};
                    const hasCustomAR = !!tool.aspectRatios;

                    extraUI = `
                    <div class="mt-4 pt-3 border-t border-zinc-700/50">
                        <div class="flex justify-between items-center mb-2">
                            <label class="text-xs text-zinc-300 font-medium flex items-center gap-2 cursor-pointer">
                                <input type="checkbox" id="map-res-custom-ar" ${hasCustomAR ? 'checked' : ''} class="rounded bg-zinc-900 border-zinc-700 text-orange-500 focus:ring-orange-500" ${!isEnabled ? 'disabled' : ''} onchange="document.getElementById('ar-inputs').classList.toggle('hidden');">
                                Override Default Aspect Ratios
                            </label>
                        </div>
                        <div id="ar-inputs" class="grid grid-cols-3 gap-2 ${(!hasCustomAR || !isEnabled) ? 'hidden' : ''}">
                            ${Object.keys(appConfig.aspectRatios || {}).map(r => `
                                <div class="bg-zinc-900/50 p-2 rounded border border-zinc-800">
                                    <div class="text-[10px] text-zinc-500 mb-2 text-center font-bold">${r}</div>
                                    <div class="flex items-center gap-1 mb-1">
                                        <span class="text-[10px] text-zinc-500 font-medium w-4 text-center">H</span>
                                        <input type="number" id="ar-${r.replace(':', '')}-h" value="${ar[r]?.height || ''}" class="w-full bg-zinc-950 border border-zinc-800 text-xs p-1 rounded text-center text-zinc-300 outline-none focus:border-orange-500" ${!isEnabled ? 'disabled' : ''}>
                                    </div>
                                    <div class="flex items-center gap-1">
                                        <span class="text-[10px] text-zinc-500 font-medium w-4 text-center">W</span>
                                        <input type="number" id="ar-${r.replace(':', '')}-w" value="${ar[r]?.width || ''}" class="w-full bg-zinc-950 border border-zinc-800 text-xs p-1 rounded text-center text-zinc-300 outline-none focus:border-orange-500" ${!isEnabled ? 'disabled' : ''}>
                                    </div>
                                </div>
                            `).join('')}
                        </div>
                    </div>
                    `;
                } else {
                    mapData = mappings[type] || { nodeId: '', field: '' };
                    isEnabled = !!mappings[type];
                    fieldUI = `
                        <div class="flex-1">
                            <label class="text-[10px] uppercase text-zinc-500 font-bold tracking-wider">Field Name</label>
                            <input type="text" id="map-${type}-field" value="${mapData.field || ''}" class="w-full bg-zinc-900 border border-zinc-700 rounded-lg p-2 text-sm focus:border-orange-500 outline-none text-zinc-300 font-mono" placeholder="Input param" ${!isEnabled ? 'disabled' : ''}>
                        </div>
                    `;
                    extraUI = type === 'seed' ? `<label class="flex items-center gap-2 mt-2 text-xs text-zinc-400"><input type="checkbox" id="map-seed-rand" ${mapData.generateRandom ? 'checked' : ''} class="rounded bg-zinc-900 border-zinc-700 text-orange-500 focus:ring-orange-500" ${!isEnabled ? 'disabled' : ''}> Generate Random</label>` : '';
                }

                container.innerHTML += `
                    <div class="bg-zinc-800/40 border border-zinc-700/50 p-4 rounded-xl transition-all ${!isEnabled ? 'opacity-50 grayscale' : ''}" id="map-${type}-container">
                        <div class="font-medium text-sm text-zinc-200 capitalize mb-3 flex justify-between items-center">
                            <span class="flex items-center gap-2"><i data-lucide="link" class="w-3 h-3 text-orange-500"></i> ${type} Input</span>
                            <label class="flex items-center cursor-pointer">
                                <div class="relative">
                                    <input type="checkbox" id="map-${type}-enable" class="sr-only" ${isEnabled ? 'checked' : ''} onchange="toggleMapping('${type}')">
                                    <div class="block bg-zinc-700 w-8 h-5 rounded-full"></div>
                                    <div class="dot absolute left-1 top-1 ${isEnabled ? 'bg-orange-500 translate-x-3' : 'bg-white'} w-3 h-3 rounded-full transition transform"></div>
                                </div>
                            </label>
                        </div>
                        <div class="flex gap-3">
                            <div class="flex-1">
                                <label class="text-[10px] uppercase text-zinc-500 font-bold tracking-wider">Node ID</label>
                                <input type="text" id="map-${type}-node" value="${mapData.nodeId || ''}" list="nodes-list" oninput="autoDetectField('${type}', this.value)" class="w-full bg-zinc-900 border border-zinc-700 rounded-lg p-2 text-sm focus:border-orange-500 outline-none text-zinc-300 font-mono" placeholder="Node ID" ${!isEnabled ? 'disabled' : ''}>
                            </div>
                            ${fieldUI}
                        </div>
                        ${extraUI}
                    </div>
                `;
            });
            
            // Show tool overrides container if prompt input is enabled
            const promptMap = mappings.prompt;
            const overrides = document.getElementById('tool-llm-overrides-container');
            if (promptMap) {
                overrides.classList.remove('hidden');
            } else {
                overrides.classList.add('hidden');
            }

            lucide.createIcons();
        }



        document.getElementById('delete-tool-btn').addEventListener('click', async () => {
            if (editingToolIndex === -1) return;
            if (confirm('Are you sure you want to remove this tool configuration and permanently delete its workflow file?')) {
                const tool = appConfig.tools[editingToolIndex];
                if (tool.workflowFile) {
                    try {
                        await adminFetch(`/api/admin/workflows/${encodeURIComponent(tool.workflowFile)}`, { method: 'DELETE' });
                    } catch (e) { console.error("Error deleting workflow file", e); }
                }
                // Delete prompt override file
                try {
                    await adminFetch(`/api/admin/prompts/${encodeURIComponent(tool.id)}`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ prompt: "" })
                    });
                } catch(e) { console.error("Error deleting prompt override", e); }
                appConfig.tools.splice(editingToolIndex, 1);
                document.getElementById('tool-editor-empty').classList.remove('hidden');
                document.getElementById('tool-editor-form').classList.add('hidden');
                document.getElementById('tool-editor-form').classList.remove('flex');
                editingToolIndex = -1;
                saveConfigToBackend();
            }
        });

        document.getElementById('save-tool-btn').addEventListener('click', async () => {
            if (editingToolIndex === -1) return;
            const tool = appConfig.tools[editingToolIndex];
            tool.id = document.getElementById('edit-tool-id').value.trim();
            tool.name = document.getElementById('edit-tool-name').value.trim();
            const outputType = document.getElementById('edit-tool-output-type').value;
            if (outputType && outputType !== 'image') {
                tool.outputType = outputType;
            } else {
                delete tool.outputType; // default is image, no need to store
            }

            tool.nodeMapping = {};
            delete tool.aspectRatios;

            MAPPING_TYPES.forEach(type => {
                const isEnabled = document.getElementById(`map-${type}-enable`).checked;
                const nodeVal = document.getElementById(`map-${type}-node`).value.trim();

                if (isEnabled && nodeVal) {
                    if (type === 'resolution') {
                        const wField = document.getElementById('map-res-wfield').value.trim() || 'width';
                        const hField = document.getElementById('map-res-hfield').value.trim() || 'height';
                        tool.nodeMapping.width = { nodeId: nodeVal, field: wField };
                        tool.nodeMapping.height = { nodeId: nodeVal, field: hField };

                        if (document.getElementById('map-res-custom-ar').checked) {
                            tool.aspectRatios = {};
                            Object.keys(appConfig.aspectRatios || {}).forEach(r => {
                                const idSuffix = r.replace(':', '');
                                const wEl = document.getElementById(`ar-${idSuffix}-w`);
                                const hEl = document.getElementById(`ar-${idSuffix}-h`);
                                if (wEl && hEl) {
                                    const w = parseInt(wEl.value);
                                    const h = parseInt(hEl.value);
                                    if (!isNaN(w) && !isNaN(h)) {
                                        tool.aspectRatios[r] = { width: w, height: h };
                                    }
                                }
                            });
                        }
                    } else {
                        const fieldVal = document.getElementById(`map-${type}-field`).value.trim();
                        if (fieldVal) {
                            tool.nodeMapping[type] = { nodeId: nodeVal, field: fieldVal };
                            if (type === 'seed') {
                                tool.nodeMapping[type].generateRandom = document.getElementById('map-seed-rand').checked;
                            }
                        }
                    }
                }
            });

            // Save tool LLM overrides (only if prompt is mapped)
            const promptEnabled = document.getElementById('map-prompt-enable').checked;
            let systemPromptOverride = '';
            if (promptEnabled) {
                const modelSelectVal = document.getElementById('edit-tool-llm-model').value;
                const modelOverride = modelSelectVal === '__custom__'
                    ? document.getElementById('edit-tool-llm-model-custom').value.trim()
                    : modelSelectVal;
                systemPromptOverride = document.getElementById('edit-tool-llm-systemprompt').value.trim();
                
                tool.promptEnhance = {
                    enabled: document.getElementById('edit-tool-llm-enabled').checked
                };
                if (modelOverride) {
                    tool.promptEnhance.model = modelOverride;
                } else {
                    delete tool.promptEnhance.model;
                }
            } else {
                delete tool.promptEnhance;
            }

            // Save the prompt text file first
            try {
                await adminFetch(`/api/admin/prompts/${encodeURIComponent(tool.id)}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ prompt: systemPromptOverride })
                });
            } catch(e) {
                console.error("Failed to save tool-specific prompt override", e);
            }

            saveConfigToBackend();
        });

        function renderComfyServers() {
            const container = document.getElementById('comfy-servers-container');
            container.innerHTML = '';
            
            if (!appConfig.comfyServers) appConfig.comfyServers = [];
            
            appConfig.comfyServers.forEach((server, i) => {
                const el = document.createElement('div');
                el.className = "flex items-center gap-2";
                el.innerHTML = `
                    <div class="flex-1">
                        <label class="text-[10px] text-zinc-500 font-bold uppercase block mb-1">URL</label>
                        <input type="text" class="w-full bg-zinc-950 border border-zinc-800 rounded p-2 text-xs focus:border-orange-500 outline-none text-zinc-300 font-mono" value="${server.url}" onchange="appConfig.comfyServers[${i}].url = this.value">
                    </div>
                    <div class="w-20">
                        <label class="text-[10px] text-zinc-500 font-bold uppercase block mb-1">Priority</label>
                        <input type="number" class="w-full bg-zinc-950 border border-zinc-800 rounded p-2 text-xs focus:border-orange-500 outline-none text-zinc-300 font-mono text-center" value="${server.priority || 1}" onchange="appConfig.comfyServers[${i}].priority = parseInt(this.value) || 1">
                    </div>
                    <button class="mt-4 text-zinc-500 hover:text-red-400 p-2 rounded hover:bg-red-950/30 transition" onclick="appConfig.comfyServers.splice(${i}, 1); renderComfyServers();"><i data-lucide="trash-2" class="w-4 h-4"></i></button>
                `;
                container.appendChild(el);
            });
            lucide.createIcons();
        }

        document.getElementById('add-server-btn').addEventListener('click', () => {
            if (!appConfig.comfyServers) appConfig.comfyServers = [];
            // Assign next priority
            let maxP = 0;
            appConfig.comfyServers.forEach(s => { if (s.priority > maxP) maxP = s.priority; });
            appConfig.comfyServers.push({ url: 'http://127.0.0.1:8188', priority: maxP + 1 });
            renderComfyServers();
        });

        document.getElementById('save-settings-btn').addEventListener('click', async () => {
            if (!appConfig) return;

            appConfig.adminKey = document.getElementById('setting-admin-key').value.trim();
            appConfig.targetMegapixels = document.getElementById('setting-target-mp').value;

            // Save global LLM settings
            const modelSelectVal = document.getElementById('setting-llm-model').value;
            const modelVal = modelSelectVal === '__custom__'
                ? document.getElementById('setting-llm-model-custom').value.trim()
                : modelSelectVal;

            const globalSystemPromptVal = document.getElementById('setting-llm-systemprompt').value.trim();
            appConfig.llm = {
                enabled: document.getElementById('setting-llm-enabled').checked,
                provider: document.getElementById('setting-llm-provider').value,
                model: modelVal,
                baseUrl: document.getElementById('setting-llm-baseurl').value.trim(),
                apiKey: document.getElementById('setting-llm-apikey').value.trim()
            };

            appConfig.aspectRatios = {};
            [1, 2, 3].forEach(slot => {
                let name = document.getElementById(`setting-ar-slot-${slot}-name`).value;
                const h = parseInt(document.getElementById(`setting-ar-slot-${slot}-h`).value);
                const w = parseInt(document.getElementById(`setting-ar-slot-${slot}-w`).value);
                
                if (name === 'custom') {
                    name = `${w}:${h}`; // Fallback name for custom
                }
                
                if (!isNaN(w) && !isNaN(h)) {
                    appConfig.aspectRatios[name] = { width: w, height: h };
                }
            });

            // Modify Image Tool setting
            const modifyEnabled = document.getElementById('setting-modify-enabled').checked;
            const modifyToolVal = document.getElementById('setting-modify-tool').value;
            if (modifyEnabled && modifyToolVal) {
                appConfig.modifyTool = modifyToolVal;
            } else {
                delete appConfig.modifyTool;
            }

            const originalText = document.getElementById('save-settings-btn').innerHTML;
            document.getElementById('save-settings-btn').innerHTML = '<i data-lucide="loader-2" class="w-4 h-4 animate-spin"></i> Saving...';

            try {
                // Save global system prompt first
                const promptRes = await adminFetch('/api/admin/prompts/global', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ prompt: globalSystemPromptVal })
                });
                if (!promptRes.ok) {
                    throw new Error('Failed to save global system prompt.');
                }

                const res = await adminFetch('/api/admin/config', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + currentKey },
                    body: JSON.stringify(appConfig)
                });

                if (res.ok) {
                    const st = document.getElementById('settings-save-status');
                    st.classList.remove('hidden');
                    setTimeout(() => st.classList.add('hidden'), 3000);
                    currentKey = appConfig.adminKey; // update key in case it changed
                } else {
                    alert('Error saving config.');
                }
            } catch (e) {
                alert('Save failed: ' + e.message);
            }

            document.getElementById('save-settings-btn').innerHTML = originalText;
            lucide.createIcons();
        });

        async function syncToolsOrder() {
            try {
                const res = await adminFetch('/api/admin/config', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + currentKey },
                    body: JSON.stringify(appConfig)
                });

                if (res.ok) {
                    const st = document.getElementById('order-save-status');
                    if (st) {
                        st.classList.remove('hidden');
                        setTimeout(() => st.classList.add('hidden'), 3000);
                    }
                } else {
                    console.error('Error syncing tool order.');
                }
            } catch (e) {
                console.error('Failed to sync tool order.', e);
            }
        }

        async function saveConfigToBackend() {
            try {
                const originalText = document.getElementById('save-tool-btn').innerHTML;
                document.getElementById('save-tool-btn').innerHTML = '<i data-lucide="loader-2" class="w-4 h-4 animate-spin"></i> Saving...';
                const res = await adminFetch('/api/admin/config', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + currentKey },
                    body: JSON.stringify(appConfig)
                });

                if (res.ok) {
                    renderToolsList();
                    const st = document.getElementById('save-status');
                    st.classList.remove('hidden');
                    setTimeout(() => st.classList.add('hidden'), 3000);
                } else {
                    alert('Error saving config.');
                }
                document.getElementById('save-tool-btn').innerHTML = originalText;
                lucide.createIcons();
            } catch (e) {
                alert('Save failed.');
            }
        }

        // File Upload
        const uploadBtn = document.getElementById('upload-workflow-btn');
        const uploadInput = document.getElementById('workflow-upload-input');

        uploadBtn.addEventListener('click', () => {
            uploadInput.click();
        });

        uploadBtn.addEventListener('dragover', (e) => {
            e.preventDefault();
            uploadBtn.classList.add('border-orange-500');
        });

        uploadBtn.addEventListener('dragleave', (e) => {
            e.preventDefault();
            uploadBtn.classList.remove('border-orange-500');
        });

        uploadBtn.addEventListener('drop', (e) => {
            e.preventDefault();
            uploadBtn.classList.remove('border-orange-500');
            if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
                uploadInput.files = e.dataTransfer.files;
                uploadInput.dispatchEvent(new Event('change'));
            }
        });

        document.getElementById('workflow-upload-input').addEventListener('change', async (e) => {
            const file = e.target.files[0];
            if (!file || !file.name.endsWith('.json')) return;

            const formData = new FormData();
            formData.append('file', file);

            const btn = document.getElementById('upload-workflow-btn');
            const origHTML = btn.innerHTML;
            btn.innerHTML = '<i data-lucide="loader-2" class="w-4 h-4 animate-spin"></i> Uploading...';

            try {
                const res = await adminFetch('/api/admin/workflows/upload', {
                    method: 'POST',
                    body: formData
                });
                const data = await res.json();
                if (res.ok) {
                    if (!availableWorkflowFiles.includes(data.filename)) {
                        availableWorkflowFiles.push(data.filename);
                        updateWorkflowDropdown();
                    }

                    if (!appConfig) appConfig = { tools: [] };
                    if (!appConfig.tools) appConfig.tools = [];

                    let autoMapping = {};
                    try {
                        const text = await file.text();
                        const parsedNodes = JSON.parse(text);
                        if (parsedNodes) {
                            for (const [nodeId, node] of Object.entries(parsedNodes)) {
                                if (node.class_type === 'CLIPTextEncode' && !autoMapping.prompt) {
                                    autoMapping.prompt = { nodeId, field: 'text' };
                                } else if (node.class_type === 'LoadImage' && !autoMapping.image) {
                                    autoMapping.image = { nodeId, field: 'image' };
                                } else if (node.class_type === 'EmptyLatentImage' || node.class_type === 'EmptySD3LatentImage') {
                                    if (!autoMapping.width) autoMapping.width = { nodeId, field: 'width' };
                                    if (!autoMapping.height) autoMapping.height = { nodeId, field: 'height' };
                                } else if (node.class_type === 'KSampler' && !autoMapping.seed) {
                                    autoMapping.seed = { nodeId, field: 'seed', generateRandom: true };
                                } else if (node.class_type === 'KSamplerAdvanced' && !autoMapping.seed) {
                                    autoMapping.seed = { nodeId, field: 'noise_seed', generateRandom: true };
                                }
                            }
                        }
                    } catch (e) {
                        console.error("Failed to parse node mappings automatically", e);
                    }

                    const defaultName = data.filename.replace('.json', '');
                    const defaultId = defaultName.toLowerCase().replace(/[^a-z0-9]/g, '-');
                    appConfig.tools.push({ id: defaultId, name: defaultName, workflowFile: data.filename, nodeMapping: autoMapping });

                    selectTool(appConfig.tools.length - 1);
                    alert("Uploaded successfully! New tool auto-generated.");
                } else {
                    alert("Upload failed: " + data.detail);
                }
            } catch (err) {
                alert("Upload failed.");
            } finally {
                btn.innerHTML = origHTML;
                lucide.createIcons();
                e.target.value = ''; // reset
            }
        });

        // System Management
        document.getElementById('check-update-btn').addEventListener('click', async () => {
            const btn = document.getElementById('check-update-btn');
            const statusText = document.getElementById('update-status-text');
            const applyBtn = document.getElementById('apply-update-btn');
            
            btn.disabled = true;
            statusText.innerText = "Checking...";
            btn.innerHTML = '<i data-lucide="loader-2" class="w-4 h-4 animate-spin"></i> Checking...';
            lucide.createIcons();

            try {
                const res = await adminFetch('/api/admin/system/check-updates');
                const data = await res.json();
                
                if (res.ok) {
                    if (data.update_available) {
                        statusText.innerText = `New version available: ${data.remote_version}`;
                        statusText.classList.replace('text-zinc-500', 'text-emerald-500');
                        applyBtn.classList.remove('hidden');
                    } else {
                        statusText.innerText = `Up to date (${data.current_version})`;
                        statusText.classList.replace('text-emerald-500', 'text-zinc-500');
                        applyBtn.classList.add('hidden');
                    }
                } else {
                    statusText.innerText = "Check failed.";
                }
            } catch (e) {
                statusText.innerText = "Error checking updates.";
            } finally {
                btn.disabled = false;
                btn.innerHTML = '<i data-lucide="refresh-cw" class="w-4 h-4"></i> Check for Updates';
                lucide.createIcons();
            }
        });

        document.getElementById('apply-update-btn').addEventListener('click', async () => {
            if (!confirm("Are you sure you want to install the update? The server will need a restart after.")) return;
            
            const btn = document.getElementById('apply-update-btn');
            const statusText = document.getElementById('update-status-text');
            
            btn.disabled = true;
            btn.innerHTML = '<i data-lucide="loader-2" class="w-4 h-4 animate-spin"></i> Installing...';
            lucide.createIcons();

            try {
                const res = await adminFetch('/api/admin/system/update', { method: 'POST' });
                const data = await res.json();
                if (res.ok) {
                    statusText.innerText = "Update successful! Restart recommended.";
                    btn.classList.add('hidden');
                } else {
                    alert("Update failed: " + data.detail);
                }
            } catch (e) {
                alert("Update failed.");
            } finally {
                btn.disabled = false;
                btn.innerHTML = '<i data-lucide="sparkles" class="w-4 h-4"></i> Install Update';
                lucide.createIcons();
            }
        });

        document.getElementById('restart-server-btn').addEventListener('click', async () => {
            if (!confirm("Restart the server? This will temporarily disconnect you.")) return;
            
            const btn = document.getElementById('restart-server-btn');
            btn.disabled = true;
            btn.innerHTML = '<i data-lucide="loader-2" class="w-4 h-4 animate-spin"></i> Restarting...';
            lucide.createIcons();

            try {
                // We don't await the response fully because the server will die
                fetch('/api/admin/system/restart', { 
                    method: 'POST',
                    headers: { 'Authorization': 'Bearer ' + currentKey }
                });
                
                setTimeout(() => {
                    location.reload();
                }, 5000);
            } catch (e) {
                // Fail silently as server is likely already restarting
            }
        });