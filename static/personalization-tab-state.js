(() => {
  const tab = document.getElementById('tab-personalization');
  const container = document.getElementById('personalization-container');
  const adminMenu = document.getElementById('admin-menu');
  if (!tab || !container || !adminMenu) return;

  const DEFAULT_CLASS = 'admin-tab flex items-center gap-2 text-zinc-400 hover:text-zinc-200 px-4 py-2 rounded-lg text-sm font-medium transition';
  const restoreRequested = localStorage.getItem('orange_admin_tab') === 'personalization';
  let restored = false;

  function deactivate() {
    tab.className = DEFAULT_CLASS;
    container.classList.add('hidden');
  }

  document.querySelectorAll('#tab-general,#tab-tools,#tab-analytics,#tab-gallery').forEach(other => {
    other.addEventListener('click', deactivate);
  });
  document.getElementById('logout-btn')?.addEventListener('click', deactivate);

  function maybeRestore() {
    if (!restoreRequested || restored || adminMenu.classList.contains('hidden')) return;
    restored = true;
    // Legacy admin.js only knows the original tabs. Re-select Personalization
    // after authentication so a saved Personalization tab survives a reload.
    window.setTimeout(() => tab.click(), 0);
  }

  const observer = new MutationObserver(maybeRestore);
  observer.observe(adminMenu, { attributes: true, attributeFilter: ['class'] });
  maybeRestore();
})();
