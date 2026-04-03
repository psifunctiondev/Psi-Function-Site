/**
 * hero-carousel.js — Gentle crossfade animation for the home page hero.
 *
 * Cycles through Psi logo variants and canvas background variants
 * independently, with random intervals (40–60s) and smooth opacity
 * transitions (~2.5s crossfade).
 *
 * Strategy: single <img> per slot. Fade out → swap src → fade in.
 * No cloned elements, so existing layout geometry is untouched.
 */

;(function () {
  'use strict'

  // --- Configuration ---

  const PSI_LOGOS = [
    'psi_logo_1.png',
    'psi_logo_2.png',
    'psi_logo_3.png',
    'psi_logo_4.png',
    'psi_logo_5.png',
    'psi_logo_6.png',
    'psi_logo_7.png',
    'psi_logo_8.png',
  ]

  const CANVASES = [
    'canvas_1.png',
    'canvas_2.png',
    'canvas_3.png',
    'canvas_4.png',
    'canvas_5.png',
    'canvas_6.png',
    'canvas_7.png',
    'canvas_recede.png',
    'canvas_wave.png',
  ]

  const MIN_DELAY = 40000 // ms
  const MAX_DELAY = 60000
  const FADE_OUT_MS = 1200 // fade to transparent
  const FADE_IN_MS = 1200 // fade new image in

  // --- Helpers ---

  function randomDelay() {
    return MIN_DELAY + Math.random() * (MAX_DELAY - MIN_DELAY)
  }

  function pickRandom(arr, excludeIndex) {
    if (arr.length <= 1) return 0
    let idx
    do {
      idx = Math.floor(Math.random() * arr.length)
    } while (idx === excludeIndex)
    return idx
  }

  function imagePath(filename) {
    // Resolve against the static images directory
    const staticBase = document.querySelector('.home__hero-psi')?.src || ''
    const dir = staticBase.substring(0, staticBase.lastIndexOf('/') + 1)
    return dir + filename
  }

  function preloadImage(src) {
    return new Promise((resolve, reject) => {
      const img = new Image()
      img.onload = () => resolve(img)
      img.onerror = reject
      img.src = src
    })
  }

  // --- Carousel engine ---

  function createCarousel(el, images, currentFilename) {
    if (!el || images.length <= 1) return

    // Figure out current index from the initial src
    let currentIndex = images.findIndex((f) => currentFilename.includes(f))
    if (currentIndex === -1) currentIndex = 0

    // Apply transition style
    el.style.transition = `opacity ${FADE_OUT_MS}ms ease`

    let transitioning = false

    async function cycle() {
      if (transitioning) return
      transitioning = true

      const nextIndex = pickRandom(images, currentIndex)
      const nextSrc = imagePath(images[nextIndex])

      // Preload next image before starting the fade
      try {
        await preloadImage(nextSrc)
      } catch {
        transitioning = false
        scheduleNext()
        return
      }

      // Phase 1: fade out
      el.style.opacity = '0'

      setTimeout(() => {
        // Phase 2: swap src while invisible
        el.src = nextSrc
        el.style.transition = `opacity ${FADE_IN_MS}ms ease`

        // Force reflow before fading in
        void el.offsetWidth

        // Phase 3: fade in
        el.style.opacity = '1'

        setTimeout(() => {
          currentIndex = nextIndex
          transitioning = false
          // Reset transition for next cycle's fade-out
          el.style.transition = `opacity ${FADE_OUT_MS}ms ease`
          scheduleNext()
        }, FADE_IN_MS + 50)
      }, FADE_OUT_MS + 50)
    }

    function scheduleNext() {
      setTimeout(cycle, randomDelay())
    }

    // Respect prefers-reduced-motion
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return

    scheduleNext()
  }

  // --- Init on DOM ready ---

  function init() {
    const psiImg = document.querySelector('.home__hero-psi')
    const canvasImg = document.querySelector('.home__hero-canvas')

    if (psiImg) {
      createCarousel(psiImg, PSI_LOGOS, psiImg.src)
    }

    if (canvasImg) {
      createCarousel(canvasImg, CANVASES, canvasImg.src)
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init)
  } else {
    init()
  }
})()
