(() => {
  const STORAGE_KEY = 'site-theme';
  const VALID_THEMES = new Set(['auto', 'night', 'twilight', 'day']);
  const EXPLICIT_THEMES = new Set(['night', 'twilight', 'day']);

  function getStoredPreference() {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      return VALID_THEMES.has(saved) ? saved : 'auto';
    } catch (err) {
      return 'auto';
    }
  }

  function savePreference(theme) {
    try {
      localStorage.setItem(STORAGE_KEY, theme);
    } catch (err) {
      // Ignore storage failures
    }
  }

  function getAutoTheme() {
    const hour = new Date().getHours();

    if (hour >= 6 && hour < 17) {
      return 'day';
    }

    if (hour >= 17 && hour < 20) {
      return 'twilight';
    }

    return 'night';
  }

  function resolveTheme(themePreference) {
    if (!VALID_THEMES.has(themePreference)) {
      return getAutoTheme();
    }

    if (themePreference === 'auto') {
      return getAutoTheme();
    }

    return themePreference;
  }

  function applyTheme(themePreference) {
    const resolvedTheme = resolveTheme(themePreference);
    document.documentElement.setAttribute('data-theme', resolvedTheme);

    const select = document.getElementById('theme-select');
    if (select && select.value !== themePreference) {
      select.value = themePreference;
    }

    return resolvedTheme;
  }

  function initThemeSwitcher() {
    const initialPreference = getStoredPreference();
    applyTheme(initialPreference);

    const select = document.getElementById('theme-select');
    if (!select) {
      return;
    }

    select.addEventListener('change', (event) => {
      const nextPreference = VALID_THEMES.has(event.target.value)
        ? event.target.value
        : 'auto';

      savePreference(nextPreference);
      applyTheme(nextPreference);
    });

    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState !== 'visible') {
        return;
      }

      const currentPreference = getStoredPreference();
      if (currentPreference === 'auto') {
        applyTheme('auto');
      }
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initThemeSwitcher);
  } else {
    initThemeSwitcher();
  }
})();
