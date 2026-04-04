/**
 * hero-carousel.js — Gentle crossfade animation for the home page hero.
 *
 * Cycles through Psi logo variants and canvas background variants,
 * alternating which one transitions each cycle (never both at once).
 *
 * Two strategies to avoid layout disruption:
 *   - Psi logo: simple fade-out → swap → fade-in (medallion bg fills gap)
 *   - Canvas: wrapper + back layer for seamless overlap (no flash)
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

  const MIN_DELAY = 30000
  const MAX_DELAY = 45000
  const CROSSFADE_MS = 2400

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

  // --- Strategy 1: Simple fade (for Psi logo) ---
  // Fade out → swap src → fade in. Works because the medallion's
  // solid background fills the gap. Zero layout impact.

  function createFadeCarousel(el, images, currentFilename) {
    if (!el || images.length <= 1) return null

    let currentIndex = images.findIndex((f) => currentFilename.includes(f))
    if (currentIndex === -1) currentIndex = 0

    el.style.transition = `opacity ${CROSSFADE_MS}ms ease`
    let transitioning = false

    async function doTransition() {
      if (transitioning) return
      transitioning = true

      const nextIndex = pickRandom(images, currentIndex)
      const nextSrc = imagePath(images[nextIndex])

      try { await preloadImage(nextSrc) } catch {
        transitioning = false; return
      }

      // Fade out
      el.style.opacity = '0'

      setTimeout(() => {
        // Swap while invisible
        el.src = nextSrc
        void el.offsetWidth
        // Fade in
        el.style.opacity = '1'

        setTimeout(() => {
          currentIndex = nextIndex
          transitioning = false
        }, CROSSFADE_MS + 50)
      }, CROSSFADE_MS + 50)
    }

    return { doTransition }
  }

  // --- Strategy 2: Overlap fade (for canvas) ---
  // Wrapper + back layer so both images are visible simultaneously
  // during the crossfade. No blank flash.

  function createOverlapCarousel(el, images, currentFilename) {
    if (!el || images.length <= 1) return null

    let currentIndex = images.findIndex((f) => currentFilename.includes(f))
    if (currentIndex === -1) currentIndex = 0

    // Wrap the canvas in a container
    const wrapper = document.createElement('div')
    wrapper.className = 'hero-carousel-wrap'
    el.parentNode.insertBefore(wrapper, el)
    wrapper.appendChild(el)

    // Clone for back layer
    const backEl = el.cloneNode(false)
    backEl.classList.add('hero-carousel-back')
    backEl.setAttribute('aria-hidden', 'true')
    backEl.style.opacity = '0'
    wrapper.appendChild(backEl)

    el.style.transition = `opacity ${CROSSFADE_MS}ms ease`
    backEl.style.transition = `opacity ${CROSSFADE_MS}ms ease`

    let transitioning = false

    async function doTransition() {
      if (transitioning) return
      transitioning = true

      const nextIndex = pickRandom(images, currentIndex)
      const nextSrc = imagePath(images[nextIndex])

      try { await preloadImage(nextSrc) } catch {
        transitioning = false; return
      }

      backEl.src = nextSrc
      void backEl.offsetWidth

      // Simultaneous crossfade
      backEl.style.opacity = '1'
      el.style.opacity = '0'

      setTimeout(() => {
        el.src = nextSrc
        el.style.opacity = '1'
        backEl.style.opacity = '0'
        currentIndex = nextIndex
        transitioning = false
      }, CROSSFADE_MS + 100)
    }

    return { doTransition }
  }

  // --- Alternating coordinator ---

  function startAlternating(psiCarousel, canvasCarousel) {
    const carousels = [psiCarousel, canvasCarousel].filter(Boolean)
    if (!carousels.length) return

    let lastIndex = -1

    function cycle() {
      let idx
      if (carousels.length === 1) {
        idx = 0
      } else {
        idx = lastIndex === 0 ? 1 : lastIndex === 1 ? 0 : Math.round(Math.random())
      }

      carousels[idx].doTransition()
      lastIndex = idx
      setTimeout(cycle, randomDelay())
    }

    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
    setTimeout(cycle, randomDelay())
  }

  // --- Init ---

  function init() {
    const psiImg = document.querySelector('.home__hero-psi')
    const canvasImg = document.querySelector('.home__hero-canvas')

    // Psi: simple fade (medallion bg fills gap)
    const psiCarousel = psiImg
      ? createFadeCarousel(psiImg, PSI_LOGOS, psiImg.src)
      : null

    // Canvas: overlap fade (no blank flash)
    const canvasCarousel = canvasImg
      ? createOverlapCarousel(canvasImg, CANVASES, canvasImg.src)
      : null

    startAlternating(psiCarousel, canvasCarousel)
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init)
  } else {
    init()
  }
})()
