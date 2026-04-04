/**
 * wave-function.js — Animated quantum wave function visualization.
 *
 * Renders an evolving wave packet showing:
 *   - Real component ψ_re (coral)
 *   - Imaginary component ψ_im (steel blue)
 *   - Probability density |ψ|² (glow fill)
 *
 * Mounts into a container with id="wave-function".
 * Canvas 2D, zero dependencies, requestAnimationFrame.
 */

;(function () {
  'use strict'

  // --- Brand colors ---
  const CORAL = '#F0643A'
  const STEEL = '#6C7D94'
  const GLOW = '#FFB48F'

  // --- Wave parameters ---
  const WAVE = {
    // Base wave packet
    k0: 6,              // central wave number
    sigma: 0.18,        // packet width (fraction of canvas)
    speed: 0.4,         // phase velocity
    // Secondary wave (interference)
    k1: 4.2,
    sigma1: 0.22,
    speed1: -0.25,
    amp1: 0.4,          // relative amplitude
    // Breathing
    breathRate: 0.15,   // how fast the amplitude pulses
    breathDepth: 0.12,  // how much it pulses (0–1)
    // Rendering
    lineWidth: 2,
    fillAlpha: 0.12,
    gridAlpha: 0.12,
    gridLines: 5,
  }

  function init() {
    const container = document.getElementById('wave-function')
    if (!container) return

    const canvas = document.createElement('canvas')
    canvas.style.display = 'block'
    canvas.style.width = '100%'
    canvas.style.height = '100%'
    container.appendChild(canvas)

    const ctx = canvas.getContext('2d')
    let width, height, dpr

    function resize() {
      dpr = window.devicePixelRatio || 1
      const rect = container.getBoundingClientRect()
      width = rect.width
      height = rect.height
      canvas.width = width * dpr
      canvas.height = height * dpr
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    }

    // Use ResizeObserver for responsive sizing
    if (typeof ResizeObserver !== 'undefined') {
      new ResizeObserver(resize).observe(container)
    } else {
      window.addEventListener('resize', resize)
    }
    resize()

    // --- Wave math ---

    function gaussian(x, center, sigma) {
      const d = (x - center) / sigma
      return Math.exp(-0.5 * d * d)
    }

    function computeWave(t) {
      const points = Math.ceil(width)
      const re = new Float32Array(points)
      const im = new Float32Array(points)
      const prob = new Float32Array(points)

      // Breathing modulation
      const breath = 1 - WAVE.breathDepth * (0.5 + 0.5 * Math.sin(t * WAVE.breathRate * Math.PI * 2))

      // Gentle drift for the packet center
      const drift = 0.5 + 0.08 * Math.sin(t * 0.1)
      const drift1 = 0.5 - 0.06 * Math.sin(t * 0.07 + 1.5)

      for (let i = 0; i < points; i++) {
        const x = i / points // normalized 0–1

        // Primary wave packet
        const env0 = gaussian(x, drift, WAVE.sigma) * breath
        const phase0 = WAVE.k0 * Math.PI * 2 * x - t * WAVE.speed
        const re0 = env0 * Math.cos(phase0)
        const im0 = env0 * Math.sin(phase0)

        // Secondary wave packet (creates interference)
        const env1 = gaussian(x, drift1, WAVE.sigma1) * WAVE.amp1 * breath
        const phase1 = WAVE.k1 * Math.PI * 2 * x - t * WAVE.speed1
        const re1 = env1 * Math.cos(phase1)
        const im1 = env1 * Math.sin(phase1)

        re[i] = re0 + re1
        im[i] = im0 + im1
        prob[i] = re[i] * re[i] + im[i] * im[i]
      }

      return { re, im, prob, points }
    }

    // --- Drawing ---

    function drawGrid() {
      ctx.strokeStyle = STEEL
      ctx.globalAlpha = WAVE.gridAlpha
      ctx.lineWidth = 0.5

      const cy = height / 2

      // Horizontal center line
      ctx.beginPath()
      ctx.moveTo(0, cy)
      ctx.lineTo(width, cy)
      ctx.stroke()

      // Faint horizontal guides
      for (let i = 1; i <= WAVE.gridLines; i++) {
        const y = (i / (WAVE.gridLines + 1)) * height
        ctx.beginPath()
        ctx.moveTo(0, y)
        ctx.lineTo(width, y)
        ctx.stroke()
      }

      ctx.globalAlpha = 1
    }

    function drawWaveLine(data, color) {
      const cy = height / 2
      const amp = height * 0.38 // max amplitude in pixels

      ctx.strokeStyle = color
      ctx.lineWidth = WAVE.lineWidth
      ctx.lineJoin = 'round'
      ctx.lineCap = 'round'
      ctx.beginPath()

      for (let i = 0; i < data.length; i++) {
        const x = (i / data.length) * width
        const y = cy - data[i] * amp
        if (i === 0) ctx.moveTo(x, y)
        else ctx.lineTo(x, y)
      }

      ctx.stroke()
    }

    function drawProbabilityFill(prob) {
      const cy = height / 2
      const amp = height * 0.38

      ctx.fillStyle = GLOW
      ctx.globalAlpha = WAVE.fillAlpha
      ctx.beginPath()
      ctx.moveTo(0, cy)

      for (let i = 0; i < prob.length; i++) {
        const x = (i / prob.length) * width
        const y = cy - prob[i] * amp
        ctx.lineTo(x, y)
      }

      ctx.lineTo(width, cy)
      ctx.closePath()
      ctx.fill()
      ctx.globalAlpha = 1
    }

    function render(t) {
      // t in seconds
      ctx.clearRect(0, 0, width, height)

      drawGrid()

      const { re, im, prob } = computeWave(t)

      // Draw probability density fill first (behind the lines)
      drawProbabilityFill(prob)

      // Draw imaginary component
      drawWaveLine(im, STEEL)

      // Draw real component on top
      drawWaveLine(re, CORAL)
    }

    // --- Animation loop ---

    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches

    if (reducedMotion) {
      // Render a single static frame
      render(0)
      return
    }

    let startTime = null

    function tick(timestamp) {
      if (!startTime) startTime = timestamp
      const t = (timestamp - startTime) / 1000 // seconds

      render(t)
      requestAnimationFrame(tick)
    }

    requestAnimationFrame(tick)
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init)
  } else {
    init()
  }
})()
