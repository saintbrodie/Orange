(() => {
  function widenGeneralSettings() {
    const settings = document.getElementById('settings-container');
    if (!settings) return;
    settings.classList.remove('max-w-3xl');
    settings.classList.add('max-w-6xl');
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', widenGeneralSettings, {once: true});
  } else {
    widenGeneralSettings();
  }
})();
