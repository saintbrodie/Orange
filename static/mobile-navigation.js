(() => {
    const MOBILE_BREAKPOINT = 640;
    const ADMIN_BREAKPOINT = 1180;

    function isMobile() {
        return window.innerWidth <= MOBILE_BREAKPOINT;
    }

    function isAdminCompact() {
        return window.innerWidth <= ADMIN_BREAKPOINT;
    }

    function injectAdminCompactStyles() {
        if (document.getElementById('orange-admin-compact-nav-styles')) return;
        const style = document.createElement('style');
        style.id = 'orange-admin-compact-nav-styles';
        style.textContent = `
            @media (min-width: 641px) and (max-width: 1180px) {
                body:has(#admin-menu) > nav {
                    flex-wrap: nowrap !important;
                    gap: .75rem !important;
                    padding: 1rem 1.25rem !important;
                }
                body:has(#admin-menu) > nav > div:first-child {
                    min-width: 0 !important;
                    flex: 1 1 auto !important;
                    flex-wrap: nowrap !important;
                }
                #admin-menu,
                #logout-btn {
                    display: none !important;
                }
                #mobile-admin-menu-btn:not(.hidden) {
                    display: flex !important;
                    align-items: center;
                    justify-content: center;
                    width: 2.75rem;
                    height: 2.75rem;
                    flex: 0 0 2.75rem;
                    margin-left: auto;
                    color: var(--orange-text, rgb(212 212 216));
                    background: color-mix(in srgb, var(--orange-panel, #18181b) 88%, white 4%);
                    border: 1px solid color-mix(in srgb, var(--orange-muted, #71717a) 34%, transparent);
                    border-radius: min(var(--orange-radius, 14px), 14px);
                }
                #mobile-nav-backdrop {
                    display: block;
                    position: fixed;
                    inset: 0;
                    z-index: 1000;
                    border: 0;
                    background: rgba(0, 0, 0, 0.58);
                    backdrop-filter: blur(2px);
                    -webkit-backdrop-filter: blur(2px);
                    opacity: 0;
                    pointer-events: none;
                    transition: opacity 160ms ease;
                }
                body.orange-mobile-menu-open #mobile-nav-backdrop {
                    opacity: 1;
                    pointer-events: auto;
                }
                #mobile-admin-drawer {
                    display: flex !important;
                    position: fixed;
                    top: 0;
                    right: 0;
                    bottom: 0;
                    width: min(88vw, 21rem);
                    z-index: 1010;
                    padding: 1rem;
                    flex-direction: column;
                    gap: .45rem;
                    background: color-mix(in srgb, var(--orange-bg, #09090b) 96%, var(--orange-panel, #18181b));
                    border-left: 1px solid color-mix(in srgb, var(--orange-muted, #71717a) 25%, transparent);
                    box-shadow: -20px 0 50px rgba(0, 0, 0, .45);
                    transform: translateX(105%);
                    transition: transform 180ms ease;
                    pointer-events: none;
                }
                body.orange-mobile-menu-open #mobile-admin-drawer {
                    transform: translateX(0);
                    pointer-events: auto;
                }
                .mobile-admin-drawer-head {
                    display: flex;
                    align-items: center;
                    justify-content: space-between;
                    gap: 1rem;
                    padding-bottom: .8rem;
                    margin-bottom: .45rem;
                    border-bottom: 1px solid color-mix(in srgb, var(--orange-muted, #71717a) 24%, transparent);
                }
                #mobile-admin-menu-close {
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    width: 2.75rem;
                    height: 2.75rem;
                    flex: 0 0 2.75rem;
                    color: var(--orange-text, rgb(212 212 216));
                    background: color-mix(in srgb, var(--orange-panel, #18181b) 88%, white 4%);
                    border: 1px solid color-mix(in srgb, var(--orange-muted, #71717a) 34%, transparent);
                    border-radius: min(var(--orange-radius, 14px), 14px);
                }
                .mobile-admin-drawer-item {
                    display: flex;
                    width: 100%;
                    align-items: center;
                    gap: .75rem;
                    padding: .85rem .9rem;
                    color: color-mix(in srgb, var(--orange-text, #f4f4f5) 68%, var(--orange-muted, #71717a));
                    background: transparent;
                    border: 1px solid transparent;
                    border-radius: .8rem;
                    text-align: left;
                    font-size: .875rem;
                    font-weight: 500;
                }
                .mobile-admin-drawer-item.active {
                    color: var(--orange-accent, #f97316);
                    background: color-mix(in srgb, var(--orange-accent, #f97316) 10%, var(--orange-panel, #18181b));
                    border-color: color-mix(in srgb, var(--orange-accent, #f97316) 38%, transparent);
                }
                .mobile-admin-drawer-separator {
                    height: 1px;
                    margin: auto 0 .35rem;
                    background: color-mix(in srgb, var(--orange-muted, #71717a) 24%, transparent);
                }
                .mobile-admin-logout {
                    color: rgb(248 113 113);
                }
            }
        `;
        document.head.appendChild(style);
    }

    function ensureBackdrop() {
        let backdrop = document.getElementById('mobile-nav-backdrop');
        if (backdrop) return backdrop;
        backdrop = document.createElement('button');
        backdrop.id = 'mobile-nav-backdrop';
        backdrop.type = 'button';
        backdrop.setAttribute('aria-label', 'Close menu');
        backdrop.addEventListener('click', closeMenus);
        document.body.appendChild(backdrop);
        return backdrop;
    }

    function closeMenus() {
        document.body.classList.remove('orange-mobile-menu-open');
        document.getElementById('mobile-tool-menu-btn')?.setAttribute('aria-expanded', 'false');
        document.getElementById('mobile-admin-menu-btn')?.setAttribute('aria-expanded', 'false');
    }

    function openMenu(button) {
        const isAdminButton = button?.id === 'mobile-admin-menu-btn';
        if (isAdminButton ? !isAdminCompact() : !isMobile()) return;
        ensureBackdrop();
        document.body.classList.add('orange-mobile-menu-open');
        button?.setAttribute('aria-expanded', 'true');
    }

    function makeIconButton(id, label, iconName) {
        const button = document.createElement('button');
        button.id = id;
        button.type = 'button';
        button.className = 'mobile-menu-trigger';
        button.setAttribute('aria-label', label);
        button.setAttribute('aria-expanded', 'false');
        const icon = document.createElement('i');
        icon.setAttribute('data-lucide', iconName);
        icon.className = 'w-5 h-5';
        button.appendChild(icon);
        return button;
    }

    function originalToolIsActive(button) {
        return button.classList.contains('bg-orange-500/10') || button.classList.contains('text-orange-400');
    }

    function toolButtonLabel(button) {
        return button.querySelector('span')?.textContent?.trim() || button.textContent.trim();
    }

    function setCurrentTool(name) {
        const value = document.getElementById('mobile-current-tool-name');
        if (value) value.textContent = name || 'Choose a tool';
    }

    function syncGeneratorTools(toolTabs, drawerList) {
        const originals = Array.from(toolTabs.children).filter(element => element.tagName === 'BUTTON');
        drawerList.replaceChildren();

        let activeName = '';
        originals.forEach(original => {
            const name = toolButtonLabel(original);
            const active = originalToolIsActive(original);
            if (active) activeName = name;

            const button = document.createElement('button');
            button.type = 'button';
            button.className = `mobile-tool-drawer-item${active ? ' active' : ''}`;

            const label = document.createElement('span');
            label.textContent = name;
            const mark = document.createElement('span');
            mark.className = 'mobile-tool-drawer-mark';
            mark.setAttribute('aria-hidden', 'true');
            mark.textContent = active ? '✓' : '›';
            button.append(label, mark);

            button.addEventListener('click', () => {
                original.click();
                setCurrentTool(name);
                closeMenus();
            });
            drawerList.appendChild(button);
        });

        if (!activeName && originals.length === 1) activeName = toolButtonLabel(originals[0]);
        if (activeName) setCurrentTool(activeName);
    }

    function setupGeneratorMenu() {
        const toolTabs = document.getElementById('tool-tabs');
        const shell = toolTabs?.closest('.max-w-6xl');
        const sidebar = shell?.firstElementChild;
        const originalToolList = toolTabs?.parentElement;
        if (!toolTabs || !sidebar || !originalToolList) return false;

        // Keep the real tool controls in the desktop sidebar. The mobile drawer is
        // a body-level proxy so the backdrop can never cover or blur it because of
        // an ancestor stacking context.
        originalToolList.classList.add('orange-desktop-tool-list');

        let currentTool = document.getElementById('mobile-current-tool');
        if (!currentTool) {
            currentTool = document.createElement('div');
            currentTool.id = 'mobile-current-tool';
            const eyebrow = document.createElement('span');
            eyebrow.className = 'mobile-current-tool-label';
            eyebrow.textContent = 'Current tool';
            const name = document.createElement('strong');
            name.id = 'mobile-current-tool-name';
            name.textContent = 'Loading…';
            currentTool.append(eyebrow, name);
        }

        let drawer = document.getElementById('mobile-tool-drawer');
        if (!drawer) {
            drawer = document.createElement('aside');
            drawer.id = 'mobile-tool-drawer';
            drawer.setAttribute('aria-label', 'Tool selector');

            const drawerHeader = document.createElement('div');
            drawerHeader.id = 'mobile-tool-drawer-head';
            const drawerTitleWrap = document.createElement('div');
            const drawerEyebrow = document.createElement('span');
            drawerEyebrow.className = 'mobile-drawer-eyebrow';
            drawerEyebrow.textContent = 'Orange';
            const drawerTitle = document.createElement('div');
            drawerTitle.className = 'mobile-drawer-title';
            drawerTitle.textContent = 'Choose Tool';
            drawerTitleWrap.append(drawerEyebrow, drawerTitle);
            const closeButton = makeIconButton('mobile-tool-menu-close', 'Close tool menu', 'x');
            closeButton.addEventListener('click', closeMenus);
            drawerHeader.append(drawerTitleWrap, closeButton);

            const drawerList = document.createElement('div');
            drawerList.id = 'mobile-tool-drawer-list';
            drawer.append(drawerHeader, drawerList);
            document.body.appendChild(drawer);
        }

        const menuButton = makeIconButton('mobile-tool-menu-btn', 'Choose tool', 'menu');
        menuButton.addEventListener('click', () => {
            if (document.body.classList.contains('orange-mobile-menu-open')) closeMenus();
            else openMenu(menuButton);
        });

        const vramWarning = document.getElementById('vram-warning');
        sidebar.insertBefore(currentTool, vramWarning || sidebar.lastElementChild);
        sidebar.insertBefore(menuButton, vramWarning || sidebar.lastElementChild);

        const drawerList = document.getElementById('mobile-tool-drawer-list');
        if (!drawerList) return false;
        syncGeneratorTools(toolTabs, drawerList);

        // app.js replaces #tool-tabs' direct button children whenever a tool is
        // selected. Watching only those direct child replacements is sufficient.
        // Do NOT observe subtree/class mutations here: Lucide and Tailwind both
        // mutate descendants while rendering, which can turn a broad observer into
        // an infinite DOM-rescan loop and freeze Firefox.
        const observer = new MutationObserver(() => syncGeneratorTools(toolTabs, drawerList));
        observer.observe(toolTabs, { childList: true });

        return true;
    }

    function makeAdminDrawerButton(original, iconName) {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'mobile-admin-drawer-item';
        button.dataset.target = original.id;

        const icon = document.createElement('i');
        icon.setAttribute('data-lucide', iconName);
        icon.className = 'w-4 h-4';
        const text = document.createElement('span');
        text.textContent = original.textContent.trim();
        button.append(icon, text);
        button.addEventListener('click', () => {
            original.click();
            closeMenus();
            window.setTimeout(syncAdminActiveState, 0);
        });
        return button;
    }

    let adminOriginals = [];

    function syncAdminActiveState() {
        const drawer = document.getElementById('mobile-admin-drawer');
        if (!drawer) return;
        drawer.querySelectorAll('.mobile-admin-drawer-item[data-target]').forEach(button => {
            const original = document.getElementById(button.dataset.target);
            button.classList.toggle('active', !!original?.classList.contains('active'));
        });
    }

    function syncAdminVisibility() {
        const originalMenu = document.getElementById('admin-menu');
        const trigger = document.getElementById('mobile-admin-menu-btn');
        if (!originalMenu || !trigger) return;
        const authenticated = !originalMenu.classList.contains('hidden');
        trigger.classList.toggle('hidden', !authenticated);
        if (!authenticated) closeMenus();
    }

    function setAdminDrawerTitle(appName) {
        const title = document.querySelector('#mobile-admin-drawer .mobile-admin-drawer-head > div');
        if (!title) return;
        const nextTitle = `${appName || 'Orange'} Admin`;
        if (title.textContent !== nextTitle) title.textContent = nextTitle;
    }

    function setupAdminMenu() {
        const originalMenu = document.getElementById('admin-menu');
        const logoutButton = document.getElementById('logout-btn');
        const nav = originalMenu?.closest('nav');
        if (!originalMenu || !logoutButton || !nav) return false;

        const trigger = makeIconButton('mobile-admin-menu-btn', 'Open admin menu', 'menu');
        trigger.classList.add('hidden');
        trigger.addEventListener('click', () => {
            if (document.body.classList.contains('orange-mobile-menu-open')) closeMenus();
            else openMenu(trigger);
        });
        nav.insertBefore(trigger, logoutButton);

        const drawer = document.createElement('div');
        drawer.id = 'mobile-admin-drawer';

        const header = document.createElement('div');
        header.className = 'mobile-admin-drawer-head';
        const title = document.createElement('div');
        title.className = 'text-sm font-semibold text-zinc-200';
        title.textContent = `${window.__orangeLastPersonalizationName || 'Orange'} Admin`;
        const closeButton = makeIconButton('mobile-admin-menu-close', 'Close admin menu', 'x');
        closeButton.addEventListener('click', closeMenus);
        header.append(title, closeButton);
        drawer.appendChild(header);

        const items = [
            ['tab-general', 'settings'],
            ['tab-tools', 'wrench'],
            ['tab-personalization', 'palette'],
            ['tab-analytics', 'bar-chart-2'],
            ['tab-gallery', 'image'],
        ];
        adminOriginals = items
            .map(([id, icon]) => [document.getElementById(id), icon])
            .filter(([element]) => !!element);
        adminOriginals.forEach(([element, icon]) => drawer.appendChild(makeAdminDrawerButton(element, icon)));

        const separator = document.createElement('div');
        separator.className = 'mobile-admin-drawer-separator';
        drawer.appendChild(separator);

        const logout = document.createElement('button');
        logout.type = 'button';
        logout.className = 'mobile-admin-drawer-item mobile-admin-logout';
        const logoutIcon = document.createElement('i');
        logoutIcon.setAttribute('data-lucide', 'log-out');
        logoutIcon.className = 'w-4 h-4';
        logout.append(logoutIcon, document.createTextNode('Logout'));
        logout.addEventListener('click', () => {
            logoutButton.click();
            closeMenus();
        });
        drawer.appendChild(logout);
        document.body.appendChild(drawer);

        const observer = new MutationObserver(() => {
            syncAdminVisibility();
            syncAdminActiveState();
        });
        observer.observe(originalMenu, { attributes: true, attributeFilter: ['class'] });
        adminOriginals.forEach(([element]) => observer.observe(element, { attributes: true, attributeFilter: ['class'] }));

        window.addEventListener('orange:personalization-applied', event => {
            setAdminDrawerTitle(event.detail?.config?.branding?.appName || window.__orangeLastPersonalizationName || 'Orange');
        });

        syncAdminVisibility();
        syncAdminActiveState();
        return true;
    }

    injectAdminCompactStyles();
    ensureBackdrop();
    setupGeneratorMenu();
    setupAdminMenu();

    window.addEventListener('resize', closeMenus);
    document.addEventListener('keydown', event => {
        if (event.key === 'Escape') closeMenus();
    });

    if (window.lucide) lucide.createIcons();
})();
