(() => {
    const MOBILE_BREAKPOINT = 640;

    function isMobile() {
        return window.innerWidth <= MOBILE_BREAKPOINT;
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
        if (!isMobile()) return;
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

    function setupGeneratorMenu() {
        const toolTabs = document.getElementById('tool-tabs');
        const shell = toolTabs?.closest('.max-w-6xl');
        const sidebar = shell?.firstElementChild;
        const drawer = toolTabs?.parentElement;
        if (!toolTabs || !sidebar || !drawer) return false;

        drawer.id = 'mobile-tool-drawer';

        const drawerHeader = document.createElement('div');
        drawerHeader.id = 'mobile-tool-drawer-head';
        const drawerTitle = document.createElement('div');
        drawerTitle.className = 'text-sm font-semibold text-zinc-200';
        drawerTitle.textContent = 'Choose Tool';
        const closeButton = makeIconButton('mobile-tool-menu-close', 'Close tool menu', 'x');
        closeButton.addEventListener('click', closeMenus);
        drawerHeader.append(drawerTitle, closeButton);
        drawer.insertBefore(drawerHeader, drawer.firstChild);

        const menuButton = makeIconButton('mobile-tool-menu-btn', 'Choose tool', 'menu');
        menuButton.addEventListener('click', () => {
            if (document.body.classList.contains('orange-mobile-menu-open')) closeMenus();
            else openMenu(menuButton);
        });
        const vramWarning = document.getElementById('vram-warning');
        sidebar.insertBefore(menuButton, vramWarning || sidebar.lastElementChild);

        toolTabs.addEventListener('click', event => {
            if (event.target.closest('button')) closeMenus();
        });

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

    ensureBackdrop();
    setupGeneratorMenu();
    setupAdminMenu();

    window.addEventListener('resize', () => {
        if (!isMobile()) closeMenus();
    });
    document.addEventListener('keydown', event => {
        if (event.key === 'Escape') closeMenus();
    });

    if (window.lucide) lucide.createIcons();
})();
