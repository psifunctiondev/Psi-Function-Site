/**
 * hero-carousel.js — Gentle crossfade animation for the home page hero.
 *
 * Cycles through Psi logo variants and canvas background variants,
 * alternating which one transitions each cycle (never both at once).
 * Uses a thin wrapper + absolute back layer for seamless overlap.
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

  const MIN_DELAY = 40000
  const MAX_DELAY = 60000
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

  // --- Carousel engine ---

  function createCarousel(el, images, currentFilename) {
    if (!el || images.length <= 1) return null

    let currentIndex = images.findIndex((f) => currentFilename.includes(f))
    if (currentIndex === -1) currentIndex = 0

    // Wrap the <img> in a position:relative container that inherits
    // the img's display footprint exactly. The back layer then sits
    // absolutely within this wrapper, matching the front img bounds.
    const wrapper = document.createElement('div')
    wrapper.className = 'hero-carousel-wrap'
    el.parentNode.insertBefore(wrapper, el)
    wrapper.appendChild(el)

    // Clone the image for the back layer
    const backEl = el.cloneNode(false)
    backEl.classList.add('hero-carousel-back')
    backEl.setAttribute('aria-hidden', 'true')
    wrapper.appendChild(backEl)

    // Transition on both layers
    el.style.transition = `opacity ${CROSSFADE_MS}ms ease`
    backEl.style.transition = `opacity ${CROSSFADE_MS}ms ease`
    backEl.style.opacity = '0'

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
