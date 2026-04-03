/**
 * hero-carousel.js — Gentle crossfade animation for the home page hero.
 *
 * Cycles through Psi logo variants and canvas background variants,
 * alternating which one transitions each cycle (never both at once).
 * Uses a two-layer stack per slot so the outgoing and incoming images
 * overlap seamlessly — no blank/white flash.
 *
 * Timing: 40–60s hold, ~2.4s crossfade.
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
  const CROSSFADE_MS = 2400 // slower, more gentle

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
  // Creates an invisible "back" <img> behind the original, positioned
  // identically. To transition: load new image into back, fade back in
  // while fading front out simultaneously, then swap.

  function createCarousel(el, images, currentFilename) {
    if (!el || images.length <= 1) return null

    let currentIndex = images.findIndex((f) => currentFilename.includes(f))
    if (currentIndex === -1) currentIndex = 0

    // Create back layer — copy all inline styles and classes from original
    const backEl = el.cloneNode(false)
    backEl.removeAttribute('class')
    // Copy the original's classes except any carousel-specific ones
    el.classList.forEach((c) => backEl.classList.add(c))
    backEl.classList.add('hero-carousel-back')
    backEl.style.position = 'absolute'
    backEl.style.top = '0'
    backEl.style.left = '0'
    backEl.style.width = '100%'
    backEl.style.height = '100%'
    backEl.style.opacity = '0'
    backEl.style.transition = `opacity ${CROSSFADE_MS}ms ease`
    backEl.style.pointerEvents = 'none'
    backEl.setAttribute('aria-hidden', 'true')

    // The front el needs transition too
    el.style.transition = `opacity ${CROSSFADE_MS}ms ease`

    // Insert back behind the front (visually behind due to DOM order,
    // but we'll control with opacity)
    el.parentNode.insertBefore(backEl, el)

    let transitioning = false

    async function doTransition() {
      if (transitioning) return
      transitioning = true

      const nextIndex = pickRandom(images, currentIndex)
      const nextSrc = imagePath(images[nextIndex])

      try {
        await preloadImage(nextSrc)
      } catch {
        transitioning = false
        return
      }

      // Load new image into back layer
      backEl.src = nextSrc
      void backEl.offsetWidth // force reflow

      // Simultaneously: fade back in, fade front out
      backEl.style.opacity = '1'
      el.style.opacity = '0'

      // After crossfade completes, swap the front src and reset
      setTimeout(() => {
        el.src = nextSrc
        el.style.opacity = '1'
        backEl.style.opacity = '0'
        currentIndex = nextIndex
        transitioning = false
      }, CROSSFADE_MS + 100)
    }

    return { doTransition, images, currentIndex }
  }

  // --- Alternating coordinator ---
  // Each cycle, only ONE of the two carousels transitions.

  function startAlternating(psiCarousel, canvasCarousel) {
    const carousels = [psiCarousel, canvasCarousel].filter(Boolean)
    if (!carousels.length) return

    let lastIndex = -1 // which carousel transitioned last

    function cycle() {
      // Pick the other one (alternate), or random if only one exists
      let idx
      if (carousels.length === 1) {
        idx = 0
      } else {
        idx = lastIndex === 0 ? 1 : lastIndex === 1 ? 0 : Math.round(Math.random())
      }

      const carousel = carousels[idx]
      carousel.doTransition()
      lastIndex = idx

      // Schedule next cycle
      setTimeout(cycle, randomDelay())
    }

    // Respect prefers-reduced-motion
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return

    // Start after initial hold
    setTimeout(cycle, randomDelay())
  }

  // --- Init ---

  function init() {
    const psiImg = document.querySelector('.home__hero-psi')
    const canvasImg = document.querySelector('.home__hero-canvas')

    const psiCarousel = psiImg
      ? createCarousel(psiImg, PSI_LOGOS, psiImg.src)
      : null
    const canvasCarousel = canvasImg
      ? createCarousel(canvasImg, CANVASES, canvasImg.src)
      : null

    startAlternating(psiCarousel, canvasCarousel)
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init)
  } else {
    init()
  }
})()
