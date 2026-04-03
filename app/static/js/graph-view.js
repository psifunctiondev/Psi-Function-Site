/**
 * graph-view.js — Interactive knowledge graph for the Services page.
 *
 * Renders an Obsidian-style force-directed graph of business functions
 * and technologies with clickable nodes showing descriptions.
 *
 * Uses Canvas 2D for rendering and a simple force simulation.
 * No external dependencies.
 */

const COLORS = {
  function: { node: '#6B8AFF', label: 'Business Function' },
  technology: { node: '#FF7B6B', label: 'Technology' },
}

const PHYSICS = {
  repulsion: 800,
  attraction: 0.008,
  damping: 0.85,
  centerGravity: 0.02,
  edgeLength: 180,
}

export async function mountGraphView(root) {
  if (!root) return

  // Fetch graph data
  const dataUrl = root.dataset.graphUrl || '/static/data/knowledge-graph.json'
  let graphData
  try {
    const resp = await fetch(dataUrl)
    graphData = await resp.json()
  } catch (err) {
    root.innerHTML =
      '<p class="card__text" style="text-align:center;padding:2rem;">Knowledge graph loading…</p>'
    return
  }

  // Setup canvas
  const canvas = document.createElement('canvas')
  canvas.style.width = '100%'
  canvas.style.height = '100%'
  canvas.style.display = 'block'
  canvas.style.cursor = 'grab'
  root.innerHTML = ''
  root.appendChild(canvas)

  // Detail panel (overlay)
  const detail = document.createElement('div')
  detail.className = 'graph-detail-panel'
  detail.hidden = true
  root.appendChild(detail)

  const ctx = canvas.getContext('2d')
  let width, height, dpr

  function resize() {
    dpr = window.devicePixelRatio || 1
    const rect = root.getBoundingClientRect()
    width = rect.width
    height = rect.height
    canvas.width = width * dpr
    canvas.height = height * dpr
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  }
  resize()
  window.addEventListener('resize', resize)

  // Initialize node positions
  const nodes = graphData.nodes.map((n, i) => ({
    ...n,
    x: width / 2 + (Math.random() - 0.5) * width * 0.6,
    y: height / 2 + (Math.random() - 0.5) * height * 0.6,
    vx: 0,
    vy: 0,
    radius: 8,
  }))

  const nodeMap = {}
  nodes.forEach((n) => (nodeMap[n.id] = n))

  const edges = graphData.edges
    .map((e) => ({
      source: nodeMap[e.source],
      target: nodeMap[e.target],
      label: e.label,
    }))
    .filter((e) => e.source && e.target)

  let selectedNode = null
  let hoveredNode = null
  let dragNode = null

  // Force simulation step
  function simulate() {
    // Repulsion between all node pairs
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const a = nodes[i],
          b = nodes[j]
        let dx = b.x - a.x
        let dy = b.y - a.y
        let dist = Math.sqrt(dx * dx + dy * dy) || 1
        let force = PHYSICS.repulsion / (dist * dist)
        let fx = (dx / dist) * force
        let fy = (dy / dist) * force
        a.vx -= fx
        a.vy -= fy
        b.vx += fx
        b.vy += fy
      }
    }

    // Attraction along edges
    edges.forEach((e) => {
      let dx = e.target.x - e.source.x
      let dy = e.target.y - e.source.y
      let dist = Math.sqrt(dx * dx + dy * dy) || 1
      let force = (dist - PHYSICS.edgeLength) * PHYSICS.attraction
      let fx = (dx / dist) * force
      let fy = (dy / dist) * force
      e.source.vx += fx
      e.source.vy += fy
      e.target.vx -= fx
      e.target.vy -= fy
    })

    // Center gravity
    nodes.forEach((n) => {
      n.vx += (width / 2 - n.x) * PHYSICS.centerGravity
      n.vy += (height / 2 - n.y) * PHYSICS.centerGravity
    })

    // Apply velocity with damping
    nodes.forEach((n) => {
      if (n === dragNode) return
      n.vx *= PHYSICS.damping
      n.vy *= PHYSICS.damping
      n.x += n.vx
      n.y += n.vy
      // Keep in bounds
      n.x = Math.max(40, Math.min(width - 40, n.x))
      n.y = Math.max(40, Math.min(height - 40, n.y))
    })
  }

  // Render
  function draw() {
    ctx.clearRect(0, 0, width, height)

    // Draw edges
    edges.forEach((e) => {
      const isHighlighted =
        selectedNode && (e.source === selectedNode || e.target === selectedNode)
      ctx.beginPath()
      ctx.moveTo(e.source.x, e.source.y)
      ctx.lineTo(e.target.x, e.target.y)
      ctx.strokeStyle = isHighlighted
        ? 'rgba(160, 180, 255, 0.6)'
        : 'rgba(128, 128, 128, 0.15)'
      ctx.lineWidth = isHighlighted ? 2 : 1
      ctx.stroke()
    })

    // Draw nodes
    nodes.forEach((n) => {
      const isSelected = n === selectedNode
      const isHovered = n === hoveredNode
      const isConnected =
        selectedNode &&
        edges.some(
          (e) =>
            (e.source === selectedNode && e.target === n) ||
            (e.target === selectedNode && e.source === n)
        )
      const dimmed = selectedNode && !isSelected && !isConnected

      const color = COLORS[n.type]?.node || '#888'
      const r = isSelected ? 12 : isHovered ? 10 : 8

      ctx.beginPath()
      ctx.arc(n.x, n.y, r, 0, Math.PI * 2)
      ctx.fillStyle = dimmed ? 'rgba(128,128,128,0.3)' : color
      ctx.fill()

      if (isSelected) {
        ctx.strokeStyle = color
        ctx.lineWidth = 2
        ctx.stroke()
      }

      // Label
      ctx.fillStyle = dimmed
        ? 'rgba(128,128,128,0.3)'
        : getComputedStyle(root).getPropertyValue('--color-text') || '#ccc'
      ctx.font = `${isSelected ? '600' : '400'} 11px system-ui, sans-serif`
      ctx.textAlign = 'center'
      ctx.fillText(n.label, n.x, n.y + r + 14)
    })
  }

  // Animation loop
  function tick() {
    simulate()
    draw()
    requestAnimationFrame(tick)
  }
  requestAnimationFrame(tick)

  // Hit detection
  function nodeAt(x, y) {
    for (let i = nodes.length - 1; i >= 0; i--) {
      const n = nodes[i]
      const dx = x - n.x
      const dy = y - n.y
      if (dx * dx + dy * dy <= 16 * 16) return n
    }
    return null
  }

  function getPos(e) {
    const rect = canvas.getBoundingClientRect()
    return { x: e.clientX - rect.left, y: e.clientY - rect.top }
  }

  // Show detail panel
  function showDetail(node) {
    if (!node) {
      detail.hidden = true
      return
    }
    const typeLabel = COLORS[node.type]?.label || node.type
    detail.innerHTML = `
      <div class="graph-detail-panel__type">${typeLabel}</div>
      <h3 class="graph-detail-panel__title">${node.label}</h3>
      <p class="graph-detail-panel__desc">${node.description}</p>
    `
    detail.hidden = false
  }

  // Mouse events
  canvas.addEventListener('mousedown', (e) => {
    const pos = getPos(e)
    const node = nodeAt(pos.x, pos.y)
    if (node) {
      dragNode = node
      canvas.style.cursor = 'grabbing'
    }
  })

  canvas.addEventListener('mousemove', (e) => {
    const pos = getPos(e)
    if (dragNode) {
      dragNode.x = pos.x
      dragNode.y = pos.y
      dragNode.vx = 0
      dragNode.vy = 0
    } else {
      const node = nodeAt(pos.x, pos.y)
      hoveredNode = node
      canvas.style.cursor = node ? 'pointer' : 'grab'
    }
  })

  canvas.addEventListener('mouseup', (e) => {
    if (dragNode) {
      const pos = getPos(e)
      const node = nodeAt(pos.x, pos.y)
      if (node === dragNode) {
        selectedNode = selectedNode === node ? null : node
        showDetail(selectedNode)
      }
      dragNode = null
      canvas.style.cursor = 'grab'
    }
  })

  canvas.addEventListener('mouseleave', () => {
    hoveredNode = null
    dragNode = null
    canvas.style.cursor = 'grab'
  })
}
