/**
 * hero-carousel.js — Gentle animated transitions for the home page hero.
 *
 * Cycles through Psi logo variants and canvas background variants
 * independently, with random intervals (20–40s) and a WebGL swirl
 * transition (~3s vortex dissolve). Falls back to CSS crossfade if
 * WebGL is unavailable.
 *
 * Zero external dependencies.
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

  const MIN_DELAY = 20000
  const MAX_DELAY = 40000
  const SWIRL_DURATION = 3000 // ms

  // --- GLSL Shaders ---

  const VERTEX_SRC = `
    attribute vec2 a_position;
    varying vec2 v_uv;
    void main() {
      v_uv = a_position * 0.5 + 0.5;
      gl_Position = vec4(a_position, 0.0, 1.0);
    }
  `

  // Swirl/vortex transition shader
  // progress: 0.0 = fully imageA, 1.0 = fully imageB
  // The swirl intensifies in the first half, then calms as imageB emerges
  const FRAGMENT_SRC = `
    precision mediump float;
    varying vec2 v_uv;
    uniform sampler2D u_imageA;
    uniform sampler2D u_imageB;
    uniform float u_progress;

    void main() {
      vec2 center = vec2(0.5, 0.5);
      vec2 uv = v_uv;

      // Swirl strength: peaks at progress=0.5, zero at 0 and 1
      float swirlAmount = sin(u_progress * 3.14159) * 2.5;

      // Distance from center
      vec2 delta = uv - center;
      float dist = length(delta);

      // Swirl angle — stronger near center, fades at edges
      float angle = swirlAmount * (1.0 - smoothstep(0.0, 0.7, dist));

      // Rotate UV around center
      float cosA = cos(angle);
      float sinA = sin(angle);
      vec2 rotated = vec2(
        cosA * delta.x - sinA * delta.y,
        sinA * delta.x + cosA * delta.y
      ) + center;

      // Clamp to valid UV range
      rotated = clamp(rotated, 0.0, 1.0);

      // Sample both images with swirled UVs
      vec4 colorA = texture2D(u_imageA, rotated);
      vec4 colorB = texture2D(u_imageB, rotated);

      // Smooth crossfade weighted by progress
      // Use a slightly accelerated curve for a more dramatic reveal
      float blend = smoothstep(0.3, 0.7, u_progress);

      gl_FragColor = mix(colorA, colorB, blend);
    }
  `

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

  function loadImage(src) {
    return new Promise((resolve, reject) => {
      const img = new Image()
      img.crossOrigin = 'anonymous'
      img.onload = () => resolve(img)
      img.onerror = reject
      img.src = src
    })
  }

  // --- WebGL helpers ---

  function createShader(gl, type, source) {
    const shader = gl.createShader(type)
    gl.shaderSource(shader, source)
    gl.compileShader(shader)
    if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
      console.warn('Shader compile error:', gl.getShaderInfoLog(shader))
      gl.deleteShader(shader)
      return null
    }
    return shader
  }

  function createProgram(gl, vertSrc, fragSrc) {
    const vert = createShader(gl, gl.VERTEX_SHADER, vertSrc)
    const frag = createShader(gl, gl.FRAGMENT_SHADER, fragSrc)
    if (!vert || !frag) return null

    const program = gl.createProgram()
    gl.attachShader(program, vert)
    gl.attachShader(program, frag)
    gl.linkProgram(program)
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
      console.warn('Program link error:', gl.getProgramInfoLog(program))
      return null
    }
    return program
  }

  function createTexture(gl, image) {
    const tex = gl.createTexture()
    gl.bindTexture(gl.TEXTURE_2D, tex)
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE)
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE)
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR)
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR)
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, image)
    return tex
  }

  // --- WebGL Swirl Carousel ---

  function createSwirlCarousel(targetEl, images, currentFilename) {
    if (!targetEl || images.length <= 1) return

    let currentIndex = images.findIndex((f) => currentFilename.includes(f.replace('.png', '')))
    if (currentIndex === -1) currentIndex = 0

    // Create canvas overlay
    const canvas = document.createElement('canvas')
    canvas.className = 'hero-carousel__gl'
    canvas.style.cssText = `
      position: absolute; top: 0; left: 0; width: 100%; height: 100%;
      pointer-events: none; opacity: 0; z-index: 1;
    `

    // Insert canvas as sibling overlay
    targetEl.parentNode.style.position = 'relative'
    targetEl.parentNode.insertBefore(canvas, targetEl.nextSibling)

    const gl = canvas.getContext('webgl', { alpha: true, premultipliedAlpha: false })
    if (!gl) {
      // Fallback: remove canvas, use CSS crossfade instead
      canvas.remove()
      createFallbackCarousel(targetEl, images, currentIndex)
      return
    }

    const program = createProgram(gl, VERTEX_SRC, FRAGMENT_SRC)
    if (!program) {
      canvas.remove()
      createFallbackCarousel(targetEl, images, currentIndex)
      return
    }

    gl.useProgram(program)

    // Fullscreen quad
    const posLoc = gl.getAttribLocation(program, 'a_position')
    const buf = gl.createBuffer()
    gl.bindBuffer(gl.ARRAY_BUFFER, buf)
    gl.bufferData(
      gl.ARRAY_BUFFER,
      new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]),
      gl.STATIC_DRAW
    )
    gl.enableVertexAttribArray(posLoc)
    gl.vertexAttribPointer(posLoc, 2, gl.FLOAT, false, 0, 0)

    // Uniform locations
    const uImageA = gl.getUniformLocation(program, 'u_imageA')
    const uImageB = gl.getUniformLocation(program, 'u_imageB')
    const uProgress = gl.getUniformLocation(program, 'u_progress')

    let transitioning = false

    function resize() {
      const rect = canvas.parentNode.getBoundingClientRect()
      const dpr = window.devicePixelRatio || 1
      canvas.width = rect.width * dpr
      canvas.height = rect.height * dpr
      gl.viewport(0, 0, canvas.width, canvas.height)
    }
    resize()
    window.addEventListener('resize', resize)

    function renderFrame(texA, texB, progress) {
      gl.activeTexture(gl.TEXTURE0)
      gl.bindTexture(gl.TEXTURE_2D, texA)
      gl.uniform1i(uImageA, 0)

      gl.activeTexture(gl.TEXTURE1)
      gl.bindTexture(gl.TEXTURE_2D, texB)
      gl.uniform1i(uImageB, 1)

      gl.uniform1f(uProgress, progress)
      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4)
    }

    async function cycle() {
      if (transitioning) return
      transitioning = true

      const nextIndex = pickRandom(images, currentIndex)
      const nextSrc = imagePath(images[nextIndex])

      let currentImg, nextImg
      try {
        ;[currentImg, nextImg] = await Promise.all([
          loadImage(targetEl.src),
          loadImage(nextSrc),
        ])
      } catch {
        transitioning = false
        scheduleNext()
        return
      }

      resize()
      const texA = createTexture(gl, currentImg)
      const texB = createTexture(gl, nextImg)

      // Show the GL canvas on top
      canvas.style.opacity = '1'

      const start = performance.now()

      function animate(now) {
        const elapsed = now - start
        const progress = Math.min(elapsed / SWIRL_DURATION, 1.0)

        // Ease in-out for smoother feel
        const eased = progress < 0.5
          ? 2 * progress * progress
          : 1 - Math.pow(-2 * progress + 2, 2) / 2

        renderFrame(texA, texB, eased)

        if (progress < 1.0) {
          requestAnimationFrame(animate)
        } else {
          // Transition complete — update the real image and hide GL canvas
          targetEl.src = nextSrc
          canvas.style.opacity = '0'

          // Clean up textures
          gl.deleteTexture(texA)
          gl.deleteTexture(texB)

          currentIndex = nextIndex
          transitioning = false
          scheduleNext()
        }
      }

      requestAnimationFrame(animate)
    }

    function scheduleNext() {
      setTimeout(cycle, randomDelay())
    }

    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
    scheduleNext()
  }

  // --- CSS Crossfade Fallback ---

  function createFallbackCarousel(targetEl, images, currentIndex) {
    const backEl = targetEl.cloneNode(false)
    backEl.className += ' hero-carousel__back'
    backEl.style.opacity = '0'
    targetEl.parentNode.insertBefore(backEl, targetEl.nextSibling)

    let transitioning = false

    async function cycle() {
      if (transitioning) return
      transitioning = true

      const nextIndex = pickRandom(images, currentIndex)
      const nextSrc = imagePath(images[nextIndex])

      try {
        await loadImage(nextSrc)
      } catch {
        transitioning = false
        setTimeout(cycle, randomDelay())
        return
      }

      backEl.src = nextSrc
      void backEl.offsetWidth
      backEl.style.opacity = '1'
      targetEl.style.opacity = '0'

      setTimeout(() => {
        targetEl.src = nextSrc
        targetEl.style.opacity = '1'
        backEl.style.opacity = '0'
        currentIndex = nextIndex
        transitioning = false
        setTimeout(cycle, randomDelay())
      }, 2600)
    }

    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
    setTimeout(cycle, randomDelay())
  }

  // --- Init ---

  function init() {
    const psiImg = document.querySelector('.home__hero-psi')
    const canvasImg = document.querySelector('.home__hero-canvas')

    if (psiImg) {
      createSwirlCarousel(psiImg, PSI_LOGOS, psiImg.src)
    }

    if (canvasImg) {
      createSwirlCarousel(canvasImg, CANVASES, canvasImg.src)
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init)
  } else {
    init()
  }
})()
