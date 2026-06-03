/**
 * work-chyron.js — Auto-advancing "selected work" showcase.
 *
 * Cycles through WorkItem cards one at a time with a gentle crossfade.
 * - Auto-advances every ADVANCE_MS, pauses on hover/focus.
 * - Dot indicators allow manual navigation.
 * - Respects prefers-reduced-motion: no auto-advance, no fade transition,
 *   but dots still work for manual navigation.
 *
 * Server renders all cards; this script toggles the `is-active` class.
 * Matches the vanilla-IIFE style of hero-carousel.js.
 */

;(function () {
  'use strict'

  const ADVANCE_MS = 9000   // hold per card
  const FADE_MS = 600       // crossfade duration (mirrors CSS var)

  function init() {
    const root = document.querySelector('.work-chyron')
    if (!root) return

    const viewport = root.querySelector('.work-chyron__viewport')
    const cards = Array.from(root.querySelectorAll('.work-chyron__card'))
    const dots = Array.from(root.querySelectorAll('.work-chyron__dot'))
    if (cards.length === 0) return

    const reduceMotion = window.matchMedia(
      '(prefers-reduced-motion: reduce)'
    ).matches

    // Expose the fade duration to CSS so the two stay in sync.
    root.style.setProperty('--work-chyron-fade', `${reduceMotion ? 0 : FADE_MS}ms`)

    // Mark as JS-enhanced so CSS hands control of visibility to us.
    if (viewport) viewport.classList.add('is-enhanced')

    let current = 0
    let timer = null
    let transitioning = false

    function show(nextIndex) {
      if (nextIndex === current || transitioning) return
      const total = cards.length
      const idx = ((nextIndex % total) + total) % total

      transitioning = true
      const outgoing = cards[current]
      const incoming = cards[idx]

      // Update dots immediately for responsive feel.
      dots.forEach((d, i) => {
        const active = i === idx
        d.classList.toggle('is-active', active)
        d.setAttribute('aria-selected', active ? 'true' : 'false')
      })

      incoming.classList.add('is-active')
      incoming.removeAttribute('aria-hidden')
      outgoing.classList.remove('is-active')
      outgoing.setAttribute('aria-hidden', 'true')

      current = idx
      // Release the transition lock after the fade completes.
      window.setTimeout(() => { transitioning = false }, FADE_MS + 50)
    }

    function next() {
      show(current + 1)
    }

    function start() {
      if (reduceMotion || cards.length <= 1) return
      stop()
      timer = window.setInterval(next, ADVANCE_MS)
    }

    function stop() {
      if (timer !== null) {
        window.clearInterval(timer)
        timer = null
      }
    }

    // Manual navigation via dots.
    dots.forEach((dot) => {
      dot.addEventListener('click', () => {
        const idx = parseInt(dot.getAttribute('data-index'), 10)
        if (!Number.isNaN(idx)) {
          show(idx)
          start() // restart the timer so the chosen card gets full dwell
        }
      })
    })

    // Pause on hover / keyboard focus within the showcase.
    root.addEventListener('mouseenter', stop)
    root.addEventListener('mouseleave', start)
    root.addEventListener('focusin', stop)
    root.addEventListener('focusout', start)

    // Pause when the tab is hidden to avoid silent advances.
    document.addEventListener('visibilitychange', () => {
      if (document.hidden) stop()
      else start()
    })

    start()
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init)
  } else {
    init()
  }
})()
