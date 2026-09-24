/**
 * portal-progress.js — Chart.js renderer for the Progress tab.
 *
 * The Progress tab's template embeds the snapshot dataset as a JSON
 * <script id="portal-project-progress-data" type="application/json">.
 * This module reads that JSON and renders a stacked bar chart
 * (weekly buckets on x, story points on y, stack segments per status).
 *
 * Chart.js is loaded via the existing CDN reference in the template;
 * if Chart isn't available yet (network slow / blocked) the canvas
 * stays blank with the placeholder caption. Once Chart loads we
 * instantiate and the placeholder is hidden behind the chart.
 *
 * Re-rendering on window resize: Chart.js handles this automatically.
 */

;(function () {
  'use strict'

  const canvas = document.getElementById('portal-project-progress-chart')
  if (!canvas) return  // not on the Progress tab.

  const dataEl = document.getElementById('portal-project-progress-data')
  if (!dataEl) return

  let dataset
  try {
    dataset = JSON.parse(dataEl.textContent)
  } catch (err) {
    console.warn('portal-progress: dataset JSON unparseable', err)
    return
  }
  if (!dataset || !Array.isArray(dataset.labels)) return

  function build() {
    if (typeof window.Chart === 'undefined') {
      // Chart.js hasn't loaded yet (CDN slow). Try again shortly;
      // bail out after ~3s so we don't loop forever.
      if (build._attempts === undefined) build._attempts = 0
      if (build._attempts++ > 30) {
        console.warn('portal-progress: Chart.js never loaded')
        return
      }
      window.setTimeout(build, 100)
      return
    }

    const labels = dataset.labels
    const statuses = dataset.statuses || []
    const series = dataset.series || []
    const palette = [
      '#4F8CC9', '#7DB46C', '#E8B860', '#C97A4F',
      '#9B59B6', '#B6443A', '#3FB6A1', '#9E9E9E',
    ]

    // Build one Chart.js dataset per status (each becomes a stack
    // segment). ``series[i]`` is the SP-per-week array for the i-th
    // status; we transpose it.
    const datasets = statuses.map((statusName, idx) => ({
      label: statusName,
      data: series.map((row) => (row && row[idx] != null) ? row[idx] : 0),
      backgroundColor: palette[idx % palette.length],
      borderColor: palette[idx % palette.length],
      borderWidth: 1,
    }))

    new window.Chart(canvas, {
      type: 'bar',
      data: { labels: labels, datasets: datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          x: {
            stacked: true,
            title: { display: true, text: 'Week' },
          },
          y: {
            stacked: true,
            beginAtZero: true,
            title: { display: true, text: 'Story points' },
            ticks: { precision: 0 },
          },
        },
        plugins: {
          legend: { position: 'bottom' },
          tooltip: { mode: 'index', intersect: false },
        },
      },
    })
  }

  build()
})()