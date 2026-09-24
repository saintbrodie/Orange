(() => {
  function widenGeneralSettings() {
    const settings = document.getElementById('settings-container');
    if (!settings) return;

    settings.classList.remove('max-w-3xl');
    settings.classList.add('max-w-6xl');

    // styles.css applies its legacy glass treatment to every .max-w-6xl.
    // General Settings uses that utility only for width, so keep the outer
    // workspace transparent and let the actual rounded settings card provide
    // the visible surface.
    settings.style.setProperty('background', 'transparent', 'important');
    settings.style.setProperty('border', '0', 'important');
    settings.style.setProperty('box-shadow', 'none', 'important');
    settings.style.setProperty('backdrop-filter', 'none', 'important');
    settings.style.setProperty('-webkit-backdrop-filter', 'none', 'important');
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', widenGeneralSettings, {once: true});
  } else {
    widenGeneralSettings();
  }
})();
