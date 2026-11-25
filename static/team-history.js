(() => {
    const element = (tag, text = '') => {
        const node = document.createElement(tag);
        node.textContent = text;
        return node;
    };
    const statusLabel = status => {
        const text = (status || 'unknown').replaceAll('_', ' ');
        return text[0].toUpperCase() + text.slice(1);
    };

    function createViewer(dialog, request, onChange) {
        const title = dialog.querySelector('#team-result-title');
        const content = dialog.querySelector('#team-result-content');
        let stream;
        let view = 0;

        function stopStream() {
            stream?.close();
            stream = null;
        }

        async function showOutput(job, currentView, prefix = '/api') {
            const query = new URLSearchParams({ prompt_id: job.id, type: job.output_type });
            const output = await request(`${prefix}/outputs?${query}`);
            if (!dialog.open || view !== currentView) return;
            if (job.output_type === 'text') {
                content.replaceChildren(element('pre', output.text || 'No text result is available.'));
                return;
            }
            content.replaceChildren();
            for (const [index, item] of (output.items || []).entries()) {
                query.set('index', index);
                const source = `${prefix}/output?${query}`;
                const media = element({ image: 'img', video: 'video', audio: 'audio' }[job.output_type] || 'img');
                if (media.tagName === 'IMG') media.alt = `Result ${index + 1}`;
                else media.controls = true;
                media.src = source;
                const download = element('a', 'Download result');
                download.href = source;
                download.download = item.filename || `result-${index + 1}`;
                content.append(media, download);
            }
            if (!content.children.length) content.textContent = 'No media result is available.';
        }

        function track(job, currentView) {
            stopStream();
            content.textContent = 'Checking generation…';
            const query = new URLSearchParams({ prompt_id: job.id, client_id: job.id, tool_id: job.tool_id });
            const source = new EventSource(`/api/status?${query}`);
            stream = source;
            source.onmessage = async event => {
                if (stream !== source) return;
                const update = JSON.parse(event.data);
                if (update.status === 'preview') return;
                content.textContent = update.detail || update.message || statusLabel(update.status);
                if (update.status !== 'completed' && update.status !== 'error') return;
                stopStream();
                if (update.retry_delivery) {
                    const retry = element('button', 'Retry delivery');
                    retry.type = 'button';
                    retry.addEventListener('click', async () => {
                        retry.disabled = true;
                        try {
                            await request(`/api/jobs/${encodeURIComponent(job.id)}/retry-download`, 'POST');
                            if (dialog.open && view === currentView) track(job, currentView);
                        } catch (error) {
                            if (dialog.open && view === currentView) content.prepend(element('p', error.message));
                        } finally {
                            retry.disabled = false;
                        }
                    });
                    content.append(retry);
                }
                try {
                    if (update.status === 'completed') await showOutput(job, currentView);
                    await onChange();
                } catch (error) {
                    if (dialog.open && view === currentView) content.textContent = error.message;
                }
            };
            source.onerror = () => {
                if (stream !== source) return;
                stopStream();
                content.textContent = 'Unable to connect. Refresh your generations and try again.';
            };
        }

        dialog.addEventListener('close', () => {
            view += 1;
            stopStream();
            content.replaceChildren();
        });

        return async (job, heading = job.tool_id, prefix) => {
            const currentView = ++view;
            title.textContent = heading;
            content.textContent = 'Loading result…';
            dialog.showModal();
            try {
                if (job.status === 'completed') await showOutput(job, currentView, prefix);
                else track(job, currentView);
            } catch (error) {
                if (dialog.open && view === currentView) content.textContent = error.message;
            }
        };
    }

    window.OrangeTeamHistory = { createViewer };

    const history = document.getElementById('generate-history');
    if (!history) return;
    const list = document.getElementById('generate-history-list');
    const feedback = document.getElementById('generate-history-feedback');
    let revision = 0;

    async function request(path, method = 'GET') {
        const response = await fetch(path, { method });
        if (response.status === 401) location.replace('/team');
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.detail || 'Could not load generation history.');
        return data;
    }

    const openResult = createViewer(document.getElementById('team-result'), request, load);

    async function load() {
        if (!history.open) return;
        const current = ++revision;
        list.setAttribute('aria-busy', 'true');
        feedback.textContent = list.children.length ? '' : 'Loading history…';
        try {
            const { jobs } = await request('/api/team/generations');
            if (current !== revision) return;
            feedback.textContent = jobs.length ? '' : 'Your generations will appear here.';
            list.replaceChildren(...jobs.map(job => {
                const row = element('li');
                const details = element('div');
                details.append(element('strong', job.tool_id));
                const date = new Date(job.created * 1000);
                const time = element('time', date.toLocaleString());
                time.dateTime = date.toISOString();
                details.append(time);
                row.append(details, element('span', statusLabel(job.status)));
                if (job.trackable) {
                    const button = element('button', job.status === 'completed' ? 'View result' : 'Check status');
                    button.type = 'button';
                    button.addEventListener('click', () => openResult(job));
                    row.append(button);
                }
                return row;
            }));
        } catch (error) {
            if (current === revision) feedback.textContent = error.message;
        } finally {
            if (current === revision) list.setAttribute('aria-busy', 'false');
        }
    }

    history.hidden = false;
    history.addEventListener('toggle', load);
    document.getElementById('generate-history-refresh').addEventListener('click', load);
    document.addEventListener('orange:generation-history-changed', load);
})();
