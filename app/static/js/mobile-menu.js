/**
 * mobile-menu.js — Hamburger menu toggle + mobile theme switching.
 */

;(function () {
  'use strict'

  const btn = document.getElementById('hamburger-btn')
  const menu = document.getElementById('mobile-menu')
  if (!btn || !menu) return

  const STORAGE_KEY = 'site-theme'
  const VALID_THEMES = new Set(['auto', 'night', 'twilight', 'day'])

  function getAutoTheme() {
    const hour = new Date().getHours()
    if (hour >= 6 && hour < 17) return 'day'
    if (hour >= 17 && hour < 20) return 'twilight'
    return 'night'
  }

  function isOpen() {
    return btn.getAttribute('aria-expanded') === 'true'
  }

  function openMenu() {
    menu.hidden = false
    menu.classList.add('is-open')
    btn.setAttribute('aria-expanded', 'true')
    btn.setAttribute('aria-label', 'Close menu')
    updateActiveTheme()
  }

  function closeMenu() {
    menu.classList.remove('is-open')
    btn.setAttribute('aria-expanded', 'false')
    btn.setAttribute('aria-label', 'Open menu')
    // Wait for animation to finish before hiding
    setTimeout(() => {
      if (!isOpen()) menu.hidden = true
    }, 300)
  }

  function toggle() {
    if (isOpen()) closeMenu()
    else openMenu()
  }

  btn.addEventListener('click', toggle)

  // Close when clicking outside
  document.addEventListener('click', (e) => {
    if (isOpen() && !btn.contains(e.target) && !menu.contains(e.target)) {
      closeMenu()
    }
  })

  // Close on Escape
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && isOpen()) closeMenu()
  })

  // Close when a nav link is clicked
  menu.querySelectorAll('.mobile-menu__link').forEach((link) => {
    link.addEventListener('click', closeMenu)
  })

  // --- Theme switching (mirrors theme-popup.js logic) ---

  function updateActiveTheme() {
    const saved = localStorage.getItem(STORAGE_KEY) || 'auto'
    menu.querySelectorAll('.mobile-menu__theme-option').forEach((opt) => {
      const isActive = opt.dataset.themeValue === saved
      opt.classList.toggle('mobile-menu__theme-option--active', isActive)
    })
  }

  menu.querySelectorAll('.mobile-menu__theme-option').forEach((opt) => {
    opt.addEventListener('click', () => {
      const value = opt.dataset.themeValue
      if (!VALID_THEMES.has(value)) return

      localStorage.setItem(STORAGE_KEY, value)
      const applied = value === 'auto' ? getAutoTheme() : value
      document.documentElement.setAttribute('data-theme', applied)

      updateActiveTheme()

      // Also sync the desktop theme popup if it exists
      const desktopPopup = document.getElementById('theme-popup')
      if (desktopPopup) {
        desktopPopup.querySelectorAll('.theme-popup__option').forEach((o) => {
          o.classList.toggle(
            'theme-popup__option--active',
            o.dataset.themeValue === value
          )
        })
      }
    })
  })
})()
