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
  // Real and imaginary are now fully independent wave systems
  // with different wavelengths, speeds, and envelopes.
  const WAVE = {
    // Real component (coral) — longer wavelength, slower
    real: {
      k: 4.5,             // wave number (fewer oscillations)
      sigma: 0.22,         // wider packet
      speed: 0.3,          // slower phase velocity
      breathRate: 0.12,
      breathDepth: 0.10,
      drift: { center: 0.48, range: 0.10, rate: 0.08 },
    },
    // Imaginary component (steel) — shorter wavelength, faster
    imag: {
      k: 7.5,             // more oscillations
      sigma: 0.16,         // tighter packet
      speed: 0.55,         // faster phase velocity
      breathRate: 0.19,
      breathDepth: 0.14,
      drift: { center: 0.52, range: 0.07, rate: 0.11 },
    },
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

    function computeComponent(cfg, t, points) {
      const data = new Float32Array(points)
      const breath = 1 - cfg.breathDepth * (0.5 + 0.5 * Math.sin(t * cfg.breathRate * Math.PI * 2))
      const center = cfg.drift.center + cfg.drift.range * Math.sin(t * cfg.drift.rate)

      for (let i = 0; i < points; i++) {
        const x = i / points
        const env = gaussian(x, center, cfg.sigma) * breath
        const phase = cfg.k * Math.PI * 2 * x - t * cfg.speed
        data[i] = env * Math.sin(phase)
      }

      return data
    }

    function computeWave(t) {
      const points = Math.ceil(width)
      const re = computeComponent(WAVE.real, t, points)
      const im = computeComponent(WAVE.imag, t, points)

      // Probability density from both independent components
      const prob = new Float32Array(points)
      for (let i = 0; i < points; i++) {
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
