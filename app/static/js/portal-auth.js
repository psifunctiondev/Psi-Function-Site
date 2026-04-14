/**
 * portal-auth.js — Tab switching for the login/register/reset forms
 * and image carousel for the portal login page.
 */

;(function () {
  'use strict'

  // --- Tab switching ---

  const tabs = document.querySelectorAll('.portal-auth-tabs__tab')
  const forms = document.querySelectorAll('.portal-auth-form')

  if (tabs.length && forms.length) {
    tabs.forEach((tab) => {
      tab.addEventListener('click', () => {
        const target = tab.dataset.tab

        // Update tabs
        tabs.forEach((t) => t.classList.toggle('is-active', t.dataset.tab === target))

        // Update forms
        forms.forEach((f) => f.classList.toggle('is-active', f.dataset.tab === target))
      })
    })
  }

  // --- Image carousel (reuses home page pattern) ---

  const IMAGES = [
    'door_1.webp',
    'door_2.webp',
    'door_3.webp',
    'door_4.webp',
    'door_5.webp',
    'door_6.webp',
    'door_7.webp',
    'door_8.webp',
    'door_9.webp',
    'door_10.webp',
    'door_11.webp',
  ]

  const FIRST_DELAY = 8000
  const MIN_DELAY = 25000
  const MAX_DELAY = 40000
  const CROSSFADE_MS = 2400

  function randomDelay() {
    return MIN_DELAY + Math.random() * (MAX_DELAY - MIN_DELAY)
  }

  function pickRandom(arr, exclude) {
    if (arr.length <= 1) return 0
    let idx
    do { idx = Math.floor(Math.random() * arr.length) } while (idx === exclude)
    return idx
  }

  const carouselImg = document.querySelector('.portal-login-grid__img')
  if (carouselImg && IMAGES.length > 1) {
    const dir = carouselImg.src.substring(0, carouselImg.src.lastIndexOf('/') + 1)
    let currentIdx = IMAGES.findIndex((f) => carouselImg.src.includes(f))
    if (currentIdx === -1) currentIdx = 0
    let busy = false

    carouselImg.style.transition = `opacity ${CROSSFADE_MS}ms ease`

    function cycle() {
      if (busy) return
      busy = true
      const next = pickRandom(IMAGES, currentIdx)
      const img = new Image()
      img.onload = () => {
        carouselImg.style.opacity = '0'
        setTimeout(() => {
          carouselImg.src = dir + IMAGES[next]
          void carouselImg.offsetWidth
          carouselImg.style.opacity = '1'
          setTimeout(() => {
            currentIdx = next
            busy = false
            setTimeout(cycle, randomDelay())
          }, CROSSFADE_MS + 50)
        }, CROSSFADE_MS + 50)
      }
      img.onerror = () => { busy = false; setTimeout(cycle, randomDelay()) }
      img.src = dir + IMAGES[next]
    }

    if (!window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      setTimeout(cycle, FIRST_DELAY)
    }
  }
})()
