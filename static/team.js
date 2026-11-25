(() => {
    const byId = id => document.getElementById(id);
    const sessionNotice = byId('team-error');
    const openJob = window.OrangeTeamHistory.createViewer(byId('team-result'), api,
        () => Promise.all([loadHistory(), loadSpend(), loadDirectory()]));
    const adminWorkspace = byId('admin-team-container');
    const params = new URLSearchParams(location.search);
    const teamUrl = adminWorkspace ? '/admin?view=team' : '/team';
    const profileId = params.get('user');
    const profileUrl = id => `${teamUrl}${adminWorkspace ? '&' : '?'}user=${encodeURIComponent(id)}`;
    const monthFormat = new Intl.DateTimeFormat(undefined, { month: 'long', year: 'numeric', timeZone: 'UTC' });
    const addedFormat = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' });
    const providerNames = { comfyui: 'ComfyUI', openai: 'OpenAI', openrouter: 'OpenRouter', xai: 'xAI', fal: 'fal.ai' };
    const linkDialog = byId('team-link-dialog');
    let inviteToken;
    let account;
    let profile;
    const directory = { accounts: [], total: 0, page: 1, sort: 'user', descending: false, request: 0, pending: false };
    const selected = new Set();
    let directoryTimer;
    let groups = [];
    let groupTools = [];
    let editingGroup = null;
    let signOutAfterLink = false;
    const activity = { view: '', page: 1, query: '', request: 0 };

    byId('team-profile-back').href = `${teamUrl}#team-management`;

    window.addEventListener('orange:personalization-applied', ({ detail }) => {
        if (adminWorkspace) return;
        const appName = detail.config.branding.appName || 'Orange';
        const signIn = detail.config.signIn || {};
        byId('team-brand-name').textContent = `${appName} Team`;
        byId('team-login-title').textContent = signIn.title || `Sign in to ${appName}`;
        byId('team-login-message').textContent = signIn.message || '';
        byId('team-login-message').hidden = !signIn.message;
        byId('team-login-submit').textContent = signIn.buttonText || 'Sign in';
        byId('team-auth-lock').hidden = signIn.mark === 'logo' || signIn.mark === 'none';
        const logo = byId('team-auth-logo');
        logo.hidden = signIn.mark !== 'logo';
        if (!logo.hidden) logo.src = document.querySelector('.team-brand img').src;
        document.title = `${appName} Team`;
    });

    function element(tag, text) {
        const node = document.createElement(tag);
        if (text !== undefined) node.textContent = text;
        return node;
    }

    function notice(message = '', target = sessionNotice) {
        target.textContent = message;
        target.hidden = !message;
    }

    function leaveTeam() {
        location.replace('/team');
    }

    async function api(path, method = 'GET', body) {
        const options = { method };
        if (body !== undefined) {
            options.headers = { 'Content-Type': 'application/json' };
            options.body = JSON.stringify(body);
        }
        const response = await fetch(path, options);
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            if (response.status === 401 && account) leaveTeam();
            throw new Error(typeof data.detail === 'string' ? data.detail : 'Check the form and try again.');
        }
        return data;
    }

    function bindForm(form, handler) {
        const alert = form.closest('dialog, #team-profile-settings')?.querySelector('[role="alert"]') || sessionNotice;
        form.addEventListener('submit', async event => {
            event.preventDefault();
            const button = event.submitter || form.querySelector('button[type="submit"]');
            const values = Object.fromEntries(new FormData(form));
            button.disabled = true;
            notice('', alert);
            try {
                await handler(values);
            } catch (error) {
                notice(error.message, alert);
            } finally {
                button.disabled = false;
            }
        });
    }

    function action(text, handler) {
        const button = element('button', text);
        button.type = 'button';
        bindAction(button, handler);
        return button;
    }

    function bindAction(button, handler) {
        const alert = button.closest('dialog, #team-profile-settings')?.querySelector('[role="alert"]') || sessionNotice;
        button.addEventListener('click', async () => {
            button.disabled = true;
            notice('', alert);
            try {
                await handler();
            } catch (error) {
                notice(error.message, alert);
            } finally {
                button.disabled = false;
            }
        });
    }

    function appendCell(row, ...children) {
        const cell = element('td');
        cell.append(...children);
        row.append(cell);
        return cell;
    }

    function emptyTable(tbody, columns, text) {
        const row = tbody.insertRow();
        const cell = appendCell(row, text);
        cell.colSpan = columns;
    }

    function amountText(micros) {
        return new Intl.NumberFormat(undefined, { style: 'currency', currency: 'USD', maximumFractionDigits: 6 }).format(micros / 1e6);
    }

    function inputAmount(micros) {
        return micros == null ? '' : String(micros / 1e6);
    }

    function dateText(seconds) {
        return new Date(seconds * 1000).toLocaleString();
    }

    function monthText(month) {
        return `${monthFormat.format(new Date(`${month}-01T00:00:00Z`))} · UTC`;
    }

    function addedDate(seconds) {
        if (seconds == null) return element('span', 'Unknown');
        const date = new Date(seconds * 1000);
        const time = element('time', addedFormat.format(date));
        time.dateTime = date.toISOString();
        return time;
    }

    function label(value) {
        const text = (value || 'unknown').replaceAll('_', ' ');
        return text[0].toUpperCase() + text.slice(1);
    }

    function statusMetrics(target, summary) {
        const fields = {
            'Remaining': amountText(summary.remaining_micros),
            'Monthly limit': amountText(summary.limit_micros),
            'Provider-reported': amountText(summary.reported_micros),
            'Estimated charges': amountText(summary.estimated_micros),
            'Pending reservations': amountText(summary.reserved_micros),
            'Blocked submissions': String(summary.blocked),
        };
        target.replaceChildren(...Object.entries(fields).map(([title, value]) => {
            const item = element('div');
            item.append(element('dt', title), element('dd', value));
            return item;
        }));
    }

    function inlineForm() {
        const form = element('form');
        form.className = 'team-inline';
        return form;
    }

    function limitForm(endpoint, accessibleLabel, micros, placeholder) {
        const form = inlineForm();
        const input = element('input');
        input.name = 'usd';
        input.inputMode = 'decimal';
        input.value = inputAmount(micros);
        input.placeholder = placeholder;
        input.maxLength = 32;
        input.setAttribute('aria-label', accessibleLabel);
        const button = element('button', 'Save');
        button.type = 'submit';
        form.append(input, button);
        bindForm(form, async ({ usd }) => {
            await api(endpoint, 'PUT', { usd: usd.trim() || null });
            await loadSpend();
        });
        return form;
    }

    function showInvitation(data, title) {
        const link = new URL('/team', location.origin);
        link.hash = new URLSearchParams({ invite: data.token }).toString();
        const input = byId('team-invitation-link');
        input.value = link.href;
        byId('team-link-title').textContent = title;
        byId('team-invitation-expires').textContent = `Expires ${dateText(data.expires)}.`;
        byId('team-copy').textContent = 'Copy link';
        notice('', linkDialog.querySelector('[role="alert"]'));
        linkDialog.showModal();
        input.focus();
        input.select();
    }

    async function changeMember(payload, message) {
        const member = profile.user;
        byId('team-profile-feedback').textContent = '';
        if (payload.role === member.role) return;
        const result = await api(`/api/team/users/${encodeURIComponent(member.id)}`, 'PATCH', payload);
        const signOut = member.id === account?.id && (payload.reset || payload.enabled === false || payload.role);
        if (result.invitation) {
            signOutAfterLink = Boolean(signOut);
            showInvitation(result.invitation, payload.reset ? 'Password reset link' : 'Set password link');
        }
        if (signOut) {
            if (!signOutAfterLink) leaveTeam();
            return;
        }
        await loadProfile();
        byId('team-profile-feedback').textContent = message;
    }

    async function removeMember() {
        const member = profile.user;
        if (!window.confirm(`Remove ${member.handle}? This signs them out and removes access to their account.`)) return;
        await api(`/api/team/users/${encodeURIComponent(member.id)}`, 'DELETE');
        if (member.id === account.id) leaveTeam();
        else location.replace(directoryUrl);
    }

    function badge(member) {
        const state = !member.enabled ? 'disabled' : member.accepted ? 'active' : 'pending';
        const item = element('span', { disabled: 'Disabled', active: 'Active', pending: 'Pending password' }[state]);
        item.className = `team-status team-status-${state}`;
        return item;
    }

    function directoryFilters() {
        const filters = {
            query: byId('team-account-search').value.trim(), team: byId('team-account-team').value,
            role: byId('team-account-role').value, status: byId('team-account-state').value,
        };
        return new URLSearchParams(Object.entries(filters).filter(([, value]) => value));
    }

    async function loadDirectory() {
        if (!account || account.role === 'member') return;
        const request = ++directory.request;
        const params = directoryFilters();
        params.set('sort', directory.sort);
        params.set('descending', directory.descending);
        params.set('page', directory.page);
        params.set('page_size', byId('team-page-size').value);
        directory.pending = true;
        updateSelection();
        try {
            const result = await api(`/api/team/accounts?${params}`);
            if (request !== directory.request || !account) return;
            directory.accounts = result.accounts;
            directory.total = result.total;
            directory.page = result.page;
            byId('team-management').hidden = false;
            renderMembers();
        } catch (error) {
            if (request === directory.request && account) {
                directory.accounts = [];
                directory.total = 0;
                renderMembers();
                throw error;
            }
        } finally {
            if (request === directory.request) {
                directory.pending = false;
                updateSelection();
            }
        }
    }

    function changeDirectoryFilters(delay = 0) {
        selected.clear();
        directory.page = 1;
        directory.request += 1;
        directory.pending = true;
        updateSelection();
        window.clearTimeout(directoryTimer);
        directoryTimer = window.setTimeout(() => loadDirectory().catch(error => notice(error.message)), delay);
    }

    function selectionBox(member) {
        const box = element('input');
        box.type = 'checkbox';
        box.setAttribute('aria-label', `Select ${member.handle}`);
        box.dataset.userId = member.id;
        box.addEventListener('change', () => {
            if (box.checked) selected.add(member.id);
            else selected.delete(member.id);
            updateSelection();
        });
        return box;
    }

    function updateSelection() {
        const owner = account?.role === 'owner';
        const allOnPage = byId('team-select-page');
        byId('team-select-heading').hidden = !owner;
        byId('team-bulk-bar').hidden = !owner || (!selected.size && directory.total <= directory.accounts.length);
        byId('team-selected-count').textContent = selected.size ? `${selected.size.toLocaleString()} selected` : '';
        const matches = byId('team-select-matches');
        matches.hidden = directory.total <= directory.accounts.length || selected.size >= directory.total;
        matches.disabled = directory.pending;
        matches.textContent = `Select all ${directory.total.toLocaleString()} matches`;
        byId('team-clear-selection').hidden = !selected.size;
        const manage = byId('team-open-memberships');
        manage.hidden = !selected.size;
        manage.disabled = directory.pending || !groups.length;
        manage.title = groups.length ? '' : 'Create a team first';
        const boxes = byId('team-members').querySelectorAll('input[type="checkbox"]');
        let selectedOnPage = 0;
        for (const box of boxes) {
            box.disabled = directory.pending;
            box.checked = selected.has(box.dataset.userId);
            if (box.checked) selectedOnPage++;
        }
        allOnPage.checked = boxes.length > 0 && selectedOnPage === boxes.length;
        allOnPage.indeterminate = selectedOnPage > 0 && selectedOnPage < boxes.length;
        allOnPage.disabled = directory.pending || !boxes.length;
        const start = (directory.page - 1) * Number(byId('team-page-size').value);
        const end = start + directory.accounts.length;
        byId('team-previous-page').disabled = directory.pending || directory.page <= 1;
        byId('team-next-page').disabled = directory.pending || end >= directory.total;
    }

    function teamLabels(teams) {
        const list = element('span');
        list.className = 'team-membership-labels';
        list.title = teams.map(group => group.name).join(', ');
        for (const group of teams.slice(0, 2)) list.append(element('span', group.name));
        if (teams.length > 2) list.append(element('span', `+${teams.length - 2}`));
        return teams.length ? list : element('span', 'No team');
    }

    function renderMembers() {
        const table = byId('team-members');
        const owner = account.role === 'owner';
        table.replaceChildren();
        if (!directory.accounts.length) emptyTable(table, owner ? 7 : 6, 'No accounts match your filters.');
        for (const member of directory.accounts) {
            const row = table.insertRow();
            if (owner) appendCell(row, selectionBox(member)).className = 'team-select-cell';
            const avatar = element('span', member.handle.slice(0, 2).toUpperCase());
            avatar.className = 'team-avatar';
            avatar.setAttribute('aria-hidden', 'true');
            const canView = account?.role === 'owner' || member.role === 'member' || member.id === account?.id;
            const identity = element(canView ? 'a' : 'span');
            identity.className = 'team-user';
            identity.append(avatar, element('span', member.handle));
            if (canView) identity.href = profileUrl(member.id);
            appendCell(row, identity);
            appendCell(row, label(member.role));
            appendCell(row, badge(member));
            appendCell(row, teamLabels(member.teams));
            appendCell(row, addedDate(member.created_at));
            appendCell(row, (member.generation_count ?? 0).toLocaleString());
        }
        const start = (directory.page - 1) * Number(byId('team-page-size').value) + 1;
        const end = start + directory.accounts.length - 1;
        byId('team-page-range').textContent = directory.total
            ? `${start.toLocaleString()}–${end.toLocaleString()} of ${directory.total.toLocaleString()}`
            : '0 accounts';
    }

    async function loadProfile() {
        const data = await api(`/api/team/users/${encodeURIComponent(profileId)}`);
        profile = data;
        const member = data.user;
        byId('team-profile-avatar').textContent = member.handle.slice(0, 2).toUpperCase();
        byId('team-profile-name').textContent = member.handle;
        byId('team-profile-role').textContent = label(member.role);
        byId('team-profile-status').replaceChildren(badge(member));
        byId('team-profile-added').replaceChildren(...(member.created_at == null
            ? ['Date added unknown'] : ['Added ', addedDate(member.created_at)]));
        byId('team-profile-month').textContent = monthText(data.month);
        statusMetrics(byId('team-profile-usage'), data.usage);

        const table = byId('team-profile-history');
        table.replaceChildren();
        for (const job of data.jobs) {
            const row = table.insertRow();
            const tool = appendCell(row, job.tool_id);
            const source = providerNames[job.provider] || label(job.provider);
            const provider = element('span', job.output_type ? `${source} · ${label(job.output_type)}` : source);
            provider.className = 'team-muted team-job-provider';
            tool.append(provider);
            appendCell(row, dateText(job.created));
            appendCell(row, label(job.status));
        }
        if (!data.jobs.length) emptyTable(table, 3, 'No generations for this account.');

        const settings = byId('team-profile-settings');
        for (const control of settings.querySelectorAll('[data-permission]')) {
            control.hidden = !data.permissions[control.dataset.permission];
        }
        byId('team-profile-limit').value = inputAmount(data.configured_limit_micros);
        byId('team-profile-role-select').value = member.role;
        byId('team-profile-enable').textContent = member.enabled ? 'Disable account' : 'Enable account';
        byId('team-profile-actions').hidden = !(data.permissions.enable || data.permissions.reset || data.permissions.remove);
        byId('team-profile-teams').textContent = data.teams.length ? data.teams.map(group => group.name).join(', ') : 'No team memberships';
        byId('team-profile-tools').textContent = data.can_edit_tools ? 'Manage tool access' : 'View tool access';
        byId('team-profile-data').hidden = false;
    }

    function renderPrices(tools) {
        const table = byId('team-prices');
        table.replaceChildren();
        for (const tool of tools) {
            const row = table.insertRow();
            appendCell(row, tool.name || tool.id);
            appendCell(row, [tool.provider, tool.model].filter(Boolean).join(' / '));
            appendCell(row, limitForm(`/api/team/budgets/tools/${encodeURIComponent(tool.id)}`,
                `USD cost estimate for ${tool.name || tool.id}`, tool.estimate_micros, 'Disabled'));
        }
        if (!tools.length) emptyTable(table, 3, 'No cloud tools configured.');
    }

    async function loadSpend() {
        const spend = await api('/api/team/spend?include_members=false');
        byId('team-month').textContent = monthText(spend.month);
        statusMetrics(byId('team-own-totals'), spend.own);
        if (spend.workspace) {
            byId('team-workspace-usage').hidden = false;
            byId('team-workspace-month').textContent = monthText(spend.month);
            statusMetrics(byId('team-workspace-totals'), spend.workspace);
            byId('team-workspace-limit').value = inputAmount(spend.workspace.limit_micros);
        }
        if (spend.tools) {
            byId('team-pricing').hidden = spend.tools.length === 0;
            renderPrices(spend.tools);
        }
    }

    async function loadGroups() {
        if (!account || account.role === 'member') return;
        const result = await api('/api/team/groups');
        groups = result.groups;
        groupTools = result.tools;
        const teamFilter = byId('team-account-team');
        const previous = teamFilter.value;
        setTeamOptions(teamFilter, 'All teams', true);
        if (previous === 'unassigned' || groups.some(group => group.id === previous)) {
            teamFilter.value = previous;
        } else if (previous) {
            selected.clear();
            directory.page = 1;
        }
        const owner = account.role === 'owner';
        byId('team-groups-panel').hidden = !owner && groups.length === 0;
        byId('team-new-group').hidden = !owner;
        const table = byId('team-groups');
        table.replaceChildren();
        for (const group of groups) {
            const row = table.insertRow();
            const name = owner ? action(group.name, () => openGroup(group)) : group.name;
            if (owner) name.className = 'team-text-button';
            appendCell(row, name);
            const count = action(group.member_count.toLocaleString(), () => {
                byId('team-account-search').value = '';
                byId('team-account-role').value = '';
                byId('team-account-state').value = '';
                teamFilter.value = group.id;
                changeDirectoryFilters();
                byId('team-management').scrollIntoView();
            });
            count.className = 'team-text-button';
            count.setAttribute('aria-label', `View ${group.name} members`);
            appendCell(row, count);
            appendCell(row, group.restricted ? 'Selected tools' : 'All available tools');
        }
        if (!groups.length) emptyTable(table, 3, 'No teams yet.');
        updateSelection();
    }

    async function loadDirectoryAndTeams() {
        await loadGroups();
        await loadDirectory();
    }

    function refreshDashboard() {
        return Promise.all([loadHistory(), loadSpend(), loadDirectoryAndTeams()]);
    }

    function setTeamOptions(select, prompt, includeUnassigned = false) {
        const options = [new Option(prompt, '')];
        if (includeUnassigned) options.push(new Option('No team', 'unassigned'));
        select.replaceChildren(...options, ...groups.map(group => new Option(group.name, group.id)));
    }

    function updateMembershipAction() {
        const mode = byId('team-memberships-action').value;
        const moving = mode === 'move';
        const source = byId('team-memberships-source');
        source.hidden = source.disabled = !moving;
        byId('team-memberships-source-label').hidden = !moving;
        byId('team-memberships-target-label').textContent = moving ? 'To team' : 'Team';
        const current = byId('team-account-team').value;
        if (groups.some(group => group.id === current)) {
            if (moving && !source.value) source.value = current;
            const target = byId('team-memberships-target');
            if (mode === 'remove' && !target.value) target.value = current;
        }
    }

    function openMemberships() {
        const action = byId('team-memberships-action');
        action.value = 'add';
        action.querySelector('option[value="move"]').disabled = groups.length < 2;
        setTeamOptions(byId('team-memberships-source'), 'Choose a team');
        setTeamOptions(byId('team-memberships-target'), 'Choose a team');
        updateMembershipAction();
        byId('team-memberships-count').textContent = `${selected.size.toLocaleString()} selected`;
        const panel = byId('team-memberships-dialog');
        notice('', panel.querySelector('[role="alert"]'));
        panel.showModal();
    }

    function checklist(container, items, selected, name) {
        const checked = new Set(selected);
        container.replaceChildren(...items.map(item => {
            const label = element('label');
            const input = element('input');
            input.type = 'checkbox';
            input.name = name;
            input.value = item.id;
            input.checked = checked.has(item.id);
            label.append(input, element('span', item.name));
            return label;
        }));
        if (!items.length) container.append(element('p', 'None available.'));
    }

    function openGroup(group = null) {
        editingGroup = group;
        byId('team-group-title').textContent = group?.name || 'New team';
        byId('team-group-name').value = group?.name || '';
        byId('team-group-policy').value = group?.restricted ? 'selected' : 'all';
        byId('team-group-tool-field').hidden = !group?.restricted;
        byId('team-remove-group').hidden = !group;
        checklist(byId('team-group-tools'), groupTools.map(tool => ({ ...tool, name: tool.enabled ? tool.name : `${tool.name} (off in Admin)` })), group?.tool_ids, 'tools');
        const panel = byId('team-group-dialog');
        notice('', panel.querySelector('[role="alert"]'));
        panel.showModal();
    }

    function openUserTools() {
        const table = byId('team-user-tools');
        table.replaceChildren();
        for (const tool of profile.tools) {
            const row = table.insertRow();
            appendCell(row, tool.name);
            appendCell(row, !tool.enabled ? 'Off in Admin' : tool.available ? 'Available' : 'Unavailable');
            const override = element('select');
            override.name = tool.id;
            override.setAttribute('aria-label', `Override for ${tool.name}`);
            for (const mode of ['inherit', 'allow', 'deny']) {
                const option = element('option', label(mode));
                option.value = mode;
                override.append(option);
            }
            override.value = tool.override;
            override.disabled = !profile.can_edit_tools;
            appendCell(row, override);
        }
        if (!profile.tools.length) emptyTable(table, 3, 'No tools configured.');
        byId('team-save-user-tools').hidden = !profile.can_edit_tools || !profile.tools.length;
        const panel = byId('team-user-tools-dialog');
        notice('', panel.querySelector('[role="alert"]'));
        panel.showModal();
    }

    async function loadHistory() {
        const { jobs } = await api('/api/team/generations');
        const table = byId('team-history');
        table.replaceChildren();
        if (!jobs.length) emptyTable(table, 4, 'Your generations will appear here.');
        for (const job of jobs) {
            const row = table.insertRow();
            appendCell(row, job.tool_id);
            appendCell(row, dateText(job.created));
            appendCell(row, label(job.status));
            appendCell(row, job.trackable ? action(job.status === 'completed' ? 'View result' : 'Check status', () => openJob(job)) : '—');
        }
    }

    function showIncomingInvitation() {
        if (adminWorkspace) return false;
        const token = new URLSearchParams(location.hash.slice(1)).get('invite');
        if (!token) return false;
        inviteToken = token;
        account = null;
        history.replaceState(null, '', '/team');
        notice();
        byId('team-nav').hidden = true;
        byId('team-account').hidden = true;
        byId('team-profile').hidden = true;
        byId('team-activity').hidden = true;
        byId('team-auth').hidden = false;
        byId('team-login').hidden = true;
        const form = byId('team-accept');
        form.reset();
        form.hidden = false;
        const choosesUsername = token.startsWith('team.') || token.startsWith('member.');
        byId('team-accept-handle-label').hidden = !choosesUsername;
        const handle = byId('team-accept-handle');
        handle.hidden = !choosesUsername;
        handle.disabled = !choosesUsername;
        return true;
    }

    function renderGallery(jobs) {
        const grid = byId('team-gallery-grid');
        grid.replaceChildren(...jobs.map(job => {
            const item = element('li');
            const button = action('', () => openJob(job, `${job.handle} · ${job.tool_id}`, '/api/team/gallery'));
            const image = element('img');
            image.alt = '';
            image.loading = 'lazy';
            image.addEventListener('error', () => {
                const unavailable = element('span', 'Preview unavailable');
                unavailable.className = 'team-gallery-unavailable';
                image.replaceWith(unavailable);
            }, { once: true });
            image.src = `/api/team/gallery/output?prompt_id=${encodeURIComponent(job.id)}`;
            const details = element('span', `${job.tool_id} · ${dateText(job.created)}`);
            details.className = 'team-muted';
            button.append(image, element('strong', job.handle), details);
            item.append(button);
            return item;
        }));
    }

    async function loadActivity() {
        const request = ++activity.request;
        const images = activity.view === 'gallery';
        const feedback = byId('team-activity-feedback');
        const table = byId('team-activity-rows');
        const previous = byId('team-activity-previous');
        const next = byId('team-activity-next');
        const query = new URLSearchParams({ images, page: activity.page, query: activity.query });
        feedback.textContent = 'Loading…';
        previous.disabled = next.disabled = true;
        table.replaceChildren();
        byId('team-gallery-grid').replaceChildren();
        try {
            const { jobs, has_more } = await api(`/api/team/activity?${query}`);
            if (request !== activity.request) return;
            if (images) renderGallery(jobs);
            else {
                for (const job of jobs) {
                    const link = element('a', job.handle);
                    link.href = profileUrl(job.user_id);
                    const row = table.insertRow();
                    appendCell(row, link);
                    appendCell(row, job.tool_id);
                    appendCell(row, dateText(job.created));
                    appendCell(row, label(job.status));
                }
            }
            feedback.textContent = jobs.length ? `Page ${activity.page}` : images ? 'No generated images found.' : 'No generation activity found.';
            next.disabled = !has_more;
        } catch (error) {
            if (request === activity.request) feedback.textContent = error.message;
        } finally {
            if (request === activity.request) previous.disabled = activity.page === 1;
        }
    }

    async function showView() {
        if (!account) return;
        const requested = adminWorkspace ? adminWorkspace.dataset.view : params.get('view') || 'team';
        if (!requested) return;
        const staff = account.role !== 'member';
        const report = staff && ['analytics', 'gallery'].includes(requested);
        const showProfile = !report && staff && Boolean(profileId);
        byId('team-account').hidden = report || showProfile;
        byId('team-profile').hidden = !showProfile;
        byId('team-activity').hidden = !report;
        if (!adminWorkspace) {
            for (const name of ['home', 'analytics', 'gallery']) {
                const tab = byId(`team-${name}-tab`);
                if (name === (report ? requested : 'home')) tab.setAttribute('aria-current', 'page');
                else tab.removeAttribute('aria-current');
            }
        }
        if (report) {
            if (activity.view !== requested) activity.page = 1;
            activity.view = requested;
            const gallery = requested === 'gallery';
            byId('team-activity-title').textContent = gallery ? 'Gallery' : 'Generation activity';
            byId('team-activity-table').hidden = gallery;
            byId('team-gallery-grid').hidden = !gallery;
            await loadActivity();
        } else if (showProfile) {
            await loadProfile();
        } else {
            await refreshDashboard();
            if (location.hash === '#team-management' && !byId('team-management').hidden) {
                byId('team-management').scrollIntoView();
            }
        }
    }

    async function init() {
        const session = await api('/api/team/session');
        localStorage.removeItem('orange_admin_key');
        localStorage.removeItem('orange_setup_recovery_key');
        if (inviteToken || showIncomingInvitation()) return;
        account = session.user;
        if (!account) {
            if (adminWorkspace) leaveTeam();
            else byId('team-auth').hidden = false;
            return;
        }
        const owner = account.role === 'owner';
        if (owner && !adminWorkspace) {
            const url = new URL('/admin', location.href);
            const view = params.get('view');
            url.searchParams.set('view', ['analytics', 'gallery'].includes(view) ? view : 'team');
            if (profileId) url.searchParams.set('user', profileId);
            url.hash = location.hash;
            location.replace(url);
            return;
        }
        const member = account.role === 'member';
        if (!adminWorkspace) {
            byId('team-nav').hidden = false;
            byId('team-analytics-tab').hidden = member;
            byId('team-gallery-tab').hidden = member;
        }
        byId('team-own-heading').hidden = !member;
        byId('team-name').textContent = account.handle;
        byId('team-role').textContent = label(account.role);
        if (member) {
            byId('team-spend-title').textContent = 'My API usage';
            const { teams } = await api('/api/team/account');
            byId('team-own-memberships').textContent = teams.map(group => group.name).join(', ') || 'No team assigned';
        }
        for (const id of ['team-invite-role', 'team-add-role']) {
            byId(`${id}-label`).hidden = !owner;
            byId(id).hidden = !owner;
            byId(id).disabled = !owner;
        }
        byId('team-workspace').hidden = !owner;
        await showView();
    }

    adminWorkspace?.addEventListener('orange:team-view', () => showView().catch(error => notice(error.message)));
    byId('team-logout')?.addEventListener('click', async () => {
        try {
            await api('/api/team/logout', 'POST');
            leaveTeam();
        } catch (error) {
            notice(error.message);
        }
    });
    bindForm(byId('team-activity-filter'), async ({ query }) => {
        activity.query = query.trim();
        activity.page = 1;
        await loadActivity();
    });
    bindAction(byId('team-activity-refresh'), loadActivity);
    byId('team-activity-previous').addEventListener('click', () => {
        activity.page -= 1;
        loadActivity();
    });
    byId('team-activity-next').addEventListener('click', () => {
        activity.page += 1;
        loadActivity();
    });
    bindAction(byId('team-refresh'), refreshDashboard);
    byId('team-account-search').addEventListener('input', () => changeDirectoryFilters(180));
    for (const id of ['team-account-team', 'team-account-role', 'team-account-state']) {
        byId(id).addEventListener('change', () => changeDirectoryFilters());
    }
    const sortButtons = byId('team-management').querySelectorAll('[data-sort]');
    for (const button of sortButtons) {
        bindAction(button, async () => {
            const sort = button.dataset.sort;
            directory.descending = directory.sort === sort ? !directory.descending : ['date', 'generations'].includes(sort);
            directory.sort = sort;
            directory.page = 1;
            for (const other of sortButtons) other.closest('th').removeAttribute('aria-sort');
            button.closest('th').setAttribute('aria-sort', directory.descending ? 'descending' : 'ascending');
            await loadDirectory();
        });
    }
    byId('team-page-size').addEventListener('change', () => {
        directory.page = 1;
        loadDirectory().catch(error => notice(error.message));
    });
    byId('team-previous-page').addEventListener('click', () => {
        directory.page -= 1;
        loadDirectory().catch(error => notice(error.message));
    });
    byId('team-next-page').addEventListener('click', () => {
        directory.page += 1;
        loadDirectory().catch(error => notice(error.message));
    });
    byId('team-select-page').addEventListener('change', event => {
        for (const user of directory.accounts) {
            if (event.target.checked) selected.add(user.id);
            else selected.delete(user.id);
        }
        updateSelection();
    });
    bindAction(byId('team-select-matches'), async () => {
        const filterKey = directoryFilters().toString();
        const params = new URLSearchParams(filterKey);
        params.set('selection', 'true');
        const { ids } = await api(`/api/team/accounts?${params}`);
        if (filterKey !== directoryFilters().toString()) return;
        selected.clear();
        for (const id of ids) selected.add(id);
        updateSelection();
    });
    byId('team-clear-selection').addEventListener('click', () => {
        selected.clear();
        updateSelection();
    });
    byId('team-open-memberships').addEventListener('click', openMemberships);
    byId('team-memberships-action').addEventListener('change', updateMembershipAction);
    byId('team-new-group').addEventListener('click', () => openGroup());
    byId('team-group-policy').addEventListener('change', event => {
        byId('team-group-tool-field').hidden = event.target.value !== 'selected';
    });
    bindAction(byId('team-remove-group'), async () => {
        const group = editingGroup;
        if (!window.confirm(`Delete ${group.name}? Members without another team will inherit all tools available in Team Generate.`)) return;
        await api(`/api/team/groups/${encodeURIComponent(group.id)}`, 'DELETE');
        byId('team-group-dialog').close();
        await loadDirectoryAndTeams().catch(error => notice(error.message));
    });
    byId('team-profile-tools').addEventListener('click', openUserTools);
    byId('team-open-add').addEventListener('click', () => {
        const panel = byId('team-add-dialog');
        notice('', panel.querySelector('[role="alert"]'));
        panel.showModal();
    });
    byId('team-add-dialog').addEventListener('close', () => byId('team-add-user').reset());
    byId('team-open-invite').addEventListener('click', () => {
        const panel = byId('team-invite-dialog');
        const expires = new Date(Date.now() + 24 * 60 * 60 * 1000);
        const localExpiry = new Date(expires.getTime() - expires.getTimezoneOffset() * 60 * 1000);
        byId('team-invite-expiry').value = localExpiry.toISOString().slice(0, 16);
        notice('', panel.querySelector('[role="alert"]'));
        panel.showModal();
    });
    bindAction(byId('team-profile-refresh'), loadProfile);
    bindAction(byId('team-profile-reset'), () => changeMember({ reset: true }, 'Password reset link created.'));
    bindAction(byId('team-profile-enable'), () => {
        const enabled = !profile.user.enabled;
        return changeMember({ enabled }, enabled ? 'Account enabled.' : 'Account disabled.');
    });
    bindAction(byId('team-profile-remove'), removeMember);
    byId('team-copy').addEventListener('click', async () => {
        const input = byId('team-invitation-link');
        input.select();
        try {
            await navigator.clipboard.writeText(input.value);
            byId('team-copy').textContent = 'Copied';
        } catch {
            notice('Copy the selected link to share it.', linkDialog.querySelector('[role="alert"]'));
        }
    });
    linkDialog.addEventListener('close', () => {
        byId('team-invitation-link').value = '';
        if (signOutAfterLink) leaveTeam();
    });
    bindForm(byId('team-login'), async values => {
        await api('/api/team/login', 'POST', values);
        location.reload();
    });
    bindForm(byId('team-accept'), async ({ password, handle }) => {
        await api('/api/team/accept-invitation', 'POST', { token: inviteToken, password, handle });
        location.replace('/team');
    });
    bindForm(byId('team-add-user'), async values => {
        const status = byId('team-account-status');
        status.textContent = '';
        const user = await api('/api/team/users', 'POST', values);
        byId('team-add-dialog').close();
        status.textContent = `Added ${user.handle}.`;
        await loadDirectory().catch(error => notice(error.message));
    });
    bindForm(byId('team-invite'), async ({ role, expires }) => {
        const expiryTime = new Date(expires).getTime();
        if (!Number.isFinite(expiryTime) || expiryTime <= Date.now()) {
            throw new Error('Choose an expiration time in the future.');
        }
        const invitation = await api('/api/team/invitations', 'POST', { role, expires: Math.floor(expiryTime / 1000) });
        byId('team-invite-dialog').close();
        showInvitation(invitation, 'Reusable invite link');
    });
    bindForm(byId('team-profile-budget'), async ({ usd }) => {
        await api(`/api/team/budgets/members/${encodeURIComponent(profileId)}`, 'PUT', { usd: usd.trim() || null });
        await loadProfile();
        byId('team-profile-feedback').textContent = 'Monthly API budget saved.';
    });
    bindForm(byId('team-profile-role-form'), ({ role }) => changeMember({ role }, 'Role saved.'));
    bindForm(byId('team-group-form'), async ({ name, policy }) => {
        const selections = new FormData(byId('team-group-form'));
        const restricted = policy === 'selected';
        const endpoint = '/api/team/groups';
        const group = editingGroup;
        await api(group ? `${endpoint}/${encodeURIComponent(group.id)}` : endpoint, group ? 'PUT' : 'POST', {
            name, restricted, tool_ids: restricted ? selections.getAll('tools') : [],
        });
        byId('team-group-dialog').close();
        await loadDirectoryAndTeams().catch(error => notice(error.message));
    });
    bindForm(byId('team-memberships-form'), async values => {
        const user_ids = [...selected];
        const { updated } = await api('/api/team/memberships', 'PUT', { ...values, user_ids });
        byId('team-memberships-dialog').close();
        selected.clear();
        byId('team-account-status').textContent = `Updated ${updated.toLocaleString()} of ${user_ids.length.toLocaleString()} selected accounts.`;
        await loadDirectoryAndTeams().catch(error => notice(error.message));
    });
    bindForm(byId('team-user-tools-form'), async values => {
        const overrides = Object.fromEntries(Object.entries(values).filter(([, mode]) => mode !== 'inherit'));
        await api(`/api/team/users/${encodeURIComponent(profileId)}/tools`, 'PUT', { overrides });
        byId('team-user-tools-dialog').close();
        await loadProfile().catch(error => notice(error.message));
        byId('team-profile-feedback').textContent = 'Tool access saved.';
    });
    bindForm(byId('team-workspace'), async ({ usd }) => {
        await api('/api/team/budgets/workspace', 'PUT', { usd: usd.trim() });
        await loadSpend();
    });
    window.addEventListener('hashchange', showIncomingInvitation);
    init().catch(error => notice(error.message));
})();
