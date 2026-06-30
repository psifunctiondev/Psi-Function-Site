/**
 * theme-popup.js
 *
 * Owns theme switching for both desktop (icon-circle + popup) and
 * mobile (icon-strip + caption). Single source of truth: localStorage
 * key + document.documentElement[data-theme]. base.html applies the
 * initial value on <head> parse, this file handles runtime changes.
 *
 * Markup contract:
 *   Desktop (in .site-nav):
 *     <div class="site-nav__theme-wrapper">
 *       <button id="theme-toggle-btn" data-theme-value="...">  <!-- the visible icon-circle -->
 *         <span id="theme-active-icon">...inline svg...</span>
 *       </button>
 *       <div id="theme-popup">
 *         <button class="theme-popup__option" data-theme-value="auto">...icon...</button>
 *         <button class="theme-popup__option" data-theme-value="day">...icon...</button>
 *         <button class="theme-popup__option" data-theme-value="twilight">...icon...</button>
 *         <button class="theme-popup__option" data-theme-value="night">...icon...</button>
 *       </div>
 *     </div>
 *
 *   Mobile (in .mobile-menu):
 *     <div class="mobile-menu__theme-strip">
 *       <button class="mobile-menu__theme-icon" data-theme-value="auto">...icon...</button>
 *       <button class="mobile-menu__theme-icon" data-theme-value="day">...icon...</button>
 *       <button class="mobile-menu__theme-icon" data-theme-value="twilight">...icon...</button>
 *       <button class="mobile-menu__theme-icon" data-theme-value="night">...icon...</button>
 *     </div>
 *     <span id="mobile-theme-caption">Auto</span>
 *
 * Depends on: nothing external. Safe to load as a plain <script>
 * at the end of <body>.
 */

(function () {
  const STORAGE_KEY = '***';
  const VALID_THEMES = new Set(['auto', 'night', 'twilight', 'day']);

  // Maps a stored choice to a human-readable label (used in the mobile caption).
  const THEME_LABELS = {
    auto: 'Auto',
    day: 'Day',
    twilight: 'Twilight',
    night: 'Night',
  };

  // The 4 lucide SVGs, keyed by theme name. We rebuild the visible
  // desktop icon to match the active theme (so the icon-circle always
  // shows what's currently selected).
  // The SVGs are inlined as strings so we can swap them without DOM fetching.
  // Source: app/__init__.py THEME_ICONS dict (kept in sync deliberately).
  const THEME_SVG = {
    auto: '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="theme-icon theme-icon--auto"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg>',
    day: '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="theme-icon theme-icon--day"><circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/><path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/></svg>',
    twilight: '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="theme-icon theme-icon--twilight"><path d="M12 10V2"/><path d="m4.93 10.93 1.41 1.41"/><path d="M2 18h2"/><path d="M20 18h2"/><path d="m19.07 10.93-1.41 1.41"/><path d="M22 22H2"/><path d="m16 6-4 4-4-4"/><path d="M16 18a4 4 0 0 0-8 0"/></svg>',
    night: '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="theme-icon theme-icon--night"><path d="M20.985 12.486a9 9 0 1 1-9.473-9.472c.405-.022.617.46.402.803a6 6 0 0 0 8.268 8.268c.344-.215.825-.004.803.401"/></svg>',
  };

  // Mirrors the function in base.html exactly so Auto resolves identically.
  function getAutoTheme() {
    const hour = new Date().getHours();
    if (hour >= 6 && hour < 17) return 'day';
    if (hour >= 17 && hour < 20) return 'twilight';
    return 'night';
  }

  // Read what the user has stored (or 'auto' as the default).
  function getStoredChoice() {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      return VALID_THEMES.has(saved) ? saved : 'auto';
    } catch {
      return 'auto';
    }
  }

  // Apply a choice: persist it, resolve Auto, set data-theme, sync UI.
  function applyTheme(choice) {
    try {
      localStorage.setItem(STORAGE_KEY, choice);
    } catch { /* storage blocked — still apply visually */ }

    const resolved = choice === 'auto' ? getAutoTheme() : choice;
    document.documentElement.setAttribute('data-theme', resolved);

    syncUI(choice);
  }

  // Swap the visible desktop icon to match the active theme.
  function updateDesktopIcon(activeChoice) {
    const iconSlot = document.getElementById('theme-active-icon');
    if (iconSlot) {
      iconSlot.innerHTML = THEME_SVG[activeChoice] || THEME_SVG.auto;
    }
    const toggleBtn = document.getElementById('theme-toggle-btn');
    if (toggleBtn) {
      toggleBtn.setAttribute('data-theme-value', activeChoice);
      toggleBtn.setAttribute('title', THEME_LABELS[activeChoice] || 'Theme');
    }
  }

  // Mark the active row in the desktop popup.
  function syncPopupRows(activeChoice) {
    document.querySelectorAll('.theme-popup__option').forEach(btn => {
      const isActive = btn.dataset.themeValue === activeChoice;
      btn.classList.toggle('theme-popup__option--active', isActive);
      btn.setAttribute('aria-checked', isActive ? 'true' : 'false');
    });
  }

  // Mark the active icon in the mobile strip + update caption.
  function syncMobileStrip(activeChoice) {
    document.querySelectorAll('.mobile-menu__theme-icon').forEach(btn => {
      const isActive = btn.dataset.themeValue === activeChoice;
      btn.classList.toggle('mobile-menu__theme-icon--active', isActive);
      btn.setAttribute('aria-checked', isActive ? 'true' : 'false');
    });
    const caption = document.getElementById('mobile-theme-caption');
    if (caption) {
      caption.textContent = THEME_LABELS[activeChoice] || '';
    }
  }

  // Single source of UI sync — called whenever the active theme changes.
  function syncUI(activeChoice) {
    updateDesktopIcon(activeChoice);
    syncPopupRows(activeChoice);
    syncMobileStrip(activeChoice);
  }

  // Open / close the desktop popup.
  function openPopup(popup, toggleBtn) {
    popup.hidden = false;
    toggleBtn.setAttribute('aria-expanded', 'true');
    // Re-sync popup rows each time it opens, so the active marker
    // is current even if the underlying choice changed elsewhere.
    syncPopupRows(getStoredChoice());
  }

  function closePopup(popup, toggleBtn) {
    popup.hidden = true;
    toggleBtn.setAttribute('aria-expanded', 'false');
  }

  // Boot once DOM is ready.
  function init() {
    const toggleBtn = document.getElementById('theme-toggle-btn');
    const popup     = document.getElementById('theme-popup');

    // Sync everything on load to match whatever base.html already applied.
    syncUI(getStoredChoice());

    // --- Desktop popup wiring ---
    if (toggleBtn && popup) {
      toggleBtn.addEventListener('click', function (e) {
        e.stopPropagation();
        const isOpen = !popup.hidden;
        isOpen ? closePopup(popup, toggleBtn) : openPopup(popup, toggleBtn);
      });

      popup.querySelectorAll('.theme-popup__option').forEach(btn => {
        btn.addEventListener('click', function () {
          applyTheme(btn.dataset.themeValue);
          closePopup(popup, toggleBtn);
        });
      });

      // Close when clicking anywhere outside the popup or toggle.
      document.addEventListener('click', function (e) {
        if (!popup.hidden &&
            !popup.contains(e.target) &&
            e.target !== toggleBtn &&
            !toggleBtn.contains(e.target)) {
          closePopup(popup, toggleBtn);
        }
      });

      // Close on Escape.
      document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && !popup.hidden) {
          closePopup(popup, toggleBtn);
          toggleBtn.focus();
        }
      });
    }

    // --- Mobile strip wiring ---
    // Each icon button is its own click target; no popup state to manage.
    document.querySelectorAll('.mobile-menu__theme-icon').forEach(btn => {
      btn.addEventListener('click', function () {
        applyTheme(btn.dataset.themeValue);
      });
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
