/**
 * theme-popup.js
 *
 * Manages the in-nav theme picker popup.
 * Wires to the same storage key and Auto logic as base.html so
 * the two never diverge.
 *
 * Depends on: nothing external. Safe to load as a plain <script>
 * at the end of <body>, or as type="module".
 */

(function () {
  const STORAGE_KEY = 'site-theme';
  const VALID_THEMES = new Set(['auto', 'night', 'twilight', 'day']);

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

  // Apply a choice: persist it, resolve Auto, set data-theme, sync checkmarks.
  function applyTheme(choice) {
    try {
      localStorage.setItem(STORAGE_KEY, choice);
    } catch { /* storage blocked — still apply visually */ }

    const resolved = choice === 'auto' ? getAutoTheme() : choice;
    document.documentElement.setAttribute('data-theme', resolved);

    syncCheckmarks(choice);
  }

  // Show a ✓ next to the currently active stored choice.
  function syncCheckmarks(activeChoice) {
    document.querySelectorAll('.theme-popup__option').forEach(btn => {
      const isActive = btn.dataset.themeValue === activeChoice;
      btn.classList.toggle('theme-popup__option--active', isActive);
      btn.setAttribute('aria-checked', isActive ? 'true' : 'false');
    });
  }

  // Toggle popup open/closed.
  function openPopup(popup, toggleBtn) {
    popup.hidden = false;
    toggleBtn.setAttribute('aria-expanded', 'true');
    // Sync checkmarks to current stored choice each time it opens.
    syncCheckmarks(getStoredChoice());
  }

  function closePopup(popup, toggleBtn) {
    popup.hidden = true;
    toggleBtn.setAttribute('aria-expanded', 'false');
  }

  // Boot once DOM is ready.
  function init() {
    const toggleBtn = document.getElementById('theme-toggle-btn');
    const popup     = document.getElementById('theme-popup');

    if (!toggleBtn || !popup) return;

    // Sync checkmarks on load to match whatever base.html already applied.
    syncCheckmarks(getStoredChoice());

    // Toggle on button click.
    toggleBtn.addEventListener('click', function (e) {
      e.stopPropagation();
      const isOpen = !popup.hidden;
      isOpen ? closePopup(popup, toggleBtn) : openPopup(popup, toggleBtn);
    });

    // Option clicks.
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
          e.target !== toggleBtn) {
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

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
