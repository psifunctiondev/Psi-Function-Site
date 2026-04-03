/**
 * hero-carousel.js — Gentle crossfade animation for the home page hero.
 *
 * Cycles through Psi logo variants and canvas background variants
 * independently, with random intervals (20–40s) and smooth opacity
 * transitions (~2.5s crossfade).
 *
 * Strategy: two stacked <img> elements per slot. The "back" image
 * loads the next variant, then we crossfade by swapping opacity.
 * After the transition completes, the back becomes the front and
 * we're ready for the next cycle.
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

  const MIN_DELAY = 20000 // ms
  const MAX_DELAY = 40000
  const FADE_DURATION = 2500 // ms — must match CSS transition

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

  function createCarousel(frontEl, images, currentFilename) {
    if (!frontEl || images.length <= 1) return

    // Figure out current index from the initial src
    let currentIndex = images.findIndex((f) => currentFilename.includes(f))
    if (currentIndex === -1) currentIndex = 0

    // Create the back layer (hidden initially)
    const backEl = frontEl.cloneNode(false)
    backEl.classList.add('hero-carousel__back')
    backEl.style.opacity = '0'
    frontEl.classList.add('hero-carousel__front')
    frontEl.parentNode.insertBefore(backEl, frontEl.nextSibling)

    let transitioning = false

    async function cycle() {
      if (transitioning) return
      transitioning = true

      const nextIndex = pickRandom(images, currentIndex)
      const nextSrc = imagePath(images[nextIndex])

      try {
        await preloadImage(nextSrc)
      } catch {
        // Image failed to load — skip this cycle
        transitioning = false
        scheduleNext()
        return
      }

      // Load into back layer and crossfade
      backEl.src = nextSrc
      // Force reflow so the transition triggers
      void backEl.offsetWidth

      backEl.style.opacity = '1'
      frontEl.style.opacity = '0'

      // After transition completes, swap roles
      setTimeout(() => {
        frontEl.src = nextSrc
        frontEl.style.opacity = '1'
        backEl.style.opacity = '0'
        currentIndex = nextIndex
        transitioning = false
        scheduleNext()
      }, FADE_DURATION + 100)
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
