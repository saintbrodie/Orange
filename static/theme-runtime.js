(() => {
  const DEFAULTS = {
    theme: 'classic',
    branding: { appName: 'Orange', tagline: 'AI Media Tools', footerText: '' },
    custom: {
      accent: '#f97316', accentSecondary: '#ea580c', background: '#09090b', panel: '#18181b',
      text: '#f4f4f5', muted: '#71717a', radius: 24, motion: 'normal'
    },
    brandingAssets: { logo: null, icon: null }
  };

  let presets = null;

  function setVar(name, value) {
    document.documentElement.style.setProperty(name, value);
  }

  async function getPresets() {
    if (presets) return presets;
    try {
      const res = await fetch('/static/themes/presets.json', { cache: 'no-store' });
      presets = await res.json();
    } catch (_) {
      presets = {};
    }
    return presets;
  }

  function replaceIcon(buttonId, iconName) {
    const button = document.getElementById(buttonId);
    if (!button) return;
    const existing = button.querySelector('svg, i');
    if (existing) existing.remove();
    const icon = document.createElement('i');
    icon.setAttribute('data-lucide', iconName);
    icon.className = 'w-5 h-5';
    button.insertBefore(icon, button.firstChild);
  }

  function ensureFooter(text) {
    document.querySelectorAll('.orange-brand-footer').forEach(el => el.remove());
    if (!text) return;

    const generatorStatus = document.getElementById('ai-status-text')?.parentElement?.parentElement;
    if (generatorStatus) {
      const footer = document.createElement('div');
      footer.className = 'orange-brand-footer';
      footer.textContent = text;
      generatorStatus.appendChild(footer);
    }

    const adminMain = document.querySelector('body > main');
    if (adminMain) {
      const footer = document.createElement('div');
      footer.className = 'orange-brand-footer';
      footer.textContent = text;
      footer.style.margin = '24px auto 0';
      adminMain.appendChild(footer);
    }
  }

  function applyBranding(config, preset) {
    const branding = config.branding || DEFAULTS.branding;
    const assets = config.brandingAssets || {};
    const appName = branding.appName || 'Orange';
    const logo = assets.logo || preset.mascot || '/static/orange.svg';
    const icon = assets.icon || preset.head || '/static/orange-head.svg';

    document.title = location.pathname.startsWith('/admin') ? `${appName} - Admin Dashboard` : appName;
    let favicon = document.querySelector('link[rel="icon"]');
    if (!favicon) {
      favicon = document.createElement('link');
      favicon.rel = 'icon';
      document.head.appendChild(favicon);
    }
    favicon.href = `${icon}${icon.includes('?') ? '&' : '?'}v=${Date.now()}`;

    document.querySelectorAll('img[src$="/orange.svg"], img.orange-theme-mascot').forEach(img => {
      img.src = logo;
      img.classList.add('orange-theme-mascot');
      img.alt = `${appName} logo`;
    });

    const generatorBrand = document.querySelector('img.orange-theme-mascot')?.parentElement?.querySelector('h1');
    if (generatorBrand && !location.pathname.startsWith('/admin')) generatorBrand.textContent = appName;

    const adminHeading = document.querySelector('nav h1');
    if (adminHeading && location.pathname.startsWith('/admin')) adminHeading.textContent = `${appName} Admin`;

    document.querySelectorAll('#mobile-admin-drawer .mobile-admin-drawer-head > div').forEach(el => {
      el.textContent = `${appName} Admin`;
    });

    ensureFooter(branding.footerText || '');
  }

  async function applyPersonalization(rawConfig) {
    const config = { ...DEFAULTS, ...(rawConfig || {}) };
    config.branding = { ...DEFAULTS.branding, ...(rawConfig?.branding || {}) };
    config.custom = { ...DEFAULTS.custom, ...(rawConfig?.custom || {}) };
    config.brandingAssets = { ...DEFAULTS.brandingAssets, ...(rawConfig?.brandingAssets || {}) };

    const allPresets = await getPresets();
    const selected = allPresets[config.theme] || allPresets.classic || {};
    const palette = config.theme === 'custom' ? config.custom : selected;

    const accent = palette.accent || DEFAULTS.custom.accent;
    const accent2 = palette.accentSecondary || DEFAULTS.custom.accentSecondary;
    const bg = palette.background || DEFAULTS.custom.background;
    const panel = palette.panel || DEFAULTS.custom.panel;
    const text = palette.text || DEFAULTS.custom.text;
    const muted = palette.muted || DEFAULTS.custom.muted;
    const radius = Number.isFinite(Number(palette.radius)) ? Number(palette.radius) : DEFAULTS.custom.radius;
    const effect = selected.effect || config.theme || 'classic';
    const motion = config.theme === 'custom' ? config.custom.motion : (effect === 'princess' || effect === 'arcade' ? 'playful' : 'normal');

    document.documentElement.dataset.orangeTheme = config.theme || 'classic';
    document.documentElement.dataset.orangeEffect = effect;
    document.documentElement.dataset.orangeMotion = motion;
    setVar('--orange-accent', accent);
    setVar('--orange-accent-2', accent2);
    setVar('--orange-bg', bg);
    setVar('--orange-panel', panel);
    setVar('--orange-panel-2', `color-mix(in srgb, ${panel} 80%, white)`);
    setVar('--orange-text', text);
    setVar('--orange-muted', muted);
    setVar('--orange-radius', `${radius}px`);
    setVar('--orange-glow', `color-mix(in srgb, ${accent} 24%, transparent)`);

    applyBranding(config, selected);
    replaceIcon('generate-btn', selected.generateIcon || 'wand-2');

    const loadingCenter = document.querySelector('#loading-spinner .absolute.inset-0.flex i, #loading-spinner .absolute.inset-0.flex svg');
    if (loadingCenter && loadingCenter.tagName.toLowerCase() === 'i') {
      loadingCenter.setAttribute('data-lucide', selected.generateIcon || 'flame');
    }

    if (window.lucide) window.lucide.createIcons();
    window.dispatchEvent(new CustomEvent('orange:personalization-applied', { detail: { config, preset: selected } }));
  }

  async function load() {
    try {
      const res = await fetch('/api/personalization', { cache: 'no-store' });
      if (!res.ok) throw new Error('personalization unavailable');
      await applyPersonalization(await res.json());
    } catch (_) {
      await applyPersonalization(DEFAULTS);
    }
  }

  window.OrangePersonalization = {
    apply: applyPersonalization,
    presets: getPresets,
    reload: load,
  };

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', load, { once: true });
  else load();

  const observer = new MutationObserver(() => {
    const title = document.querySelector('#mobile-admin-drawer .mobile-admin-drawer-head > div');
    if (title && window.__orangeLastPersonalizationName) title.textContent = `${window.__orangeLastPersonalizationName} Admin`;
  });
  observer.observe(document.documentElement, { childList: true, subtree: true });
})();
