/**
 * portal-backlog.js — SortableJS drag-reorder for the Backlog tab.
 *
 * The Backlog tab renders open user stories in their current
 * methodos_sequence order. Dragging a row to a new position
 * optimistically updates the DOM, then PATCHes the new position via
 *   POST /api/portal/openproject/<op>/work_packages/<wp>/reorder
 *   body: { newPosition, lockVersion }
 *
 * On success we refresh lockVersion from the server response so the
 * next move carries the right token. On failure we revert the DOM
 * and flash the error.
 */

import Sortable from 'sortablejs'

;(function () {
  'use strict'

  const tbody = document.querySelector('.portal-backlog__tbody')
  if (!tbody) return  // not on the Backlog tab — exit silently.

  const board = document.querySelector('.portal-backlog')
  if (!board) return
  const opId = board.dataset.opId
  const slug = board.dataset.slug
  if (!opId || !slug) {
    console.warn('portal-backlog: missing data-op-id / data-slug; drag disabled.')
    return
  }

  const FLASH_CLASS = 'portal-backlog__flash'

  function flash(msg, level) {
    const prior = board.querySelector('.' + FLASH_CLASS)
    if (prior) prior.remove()
    const banner = document.createElement('div')
    banner.className = FLASH_CLASS + ' ' + FLASH_CLASS + '--' + (level || 'error')
    banner.setAttribute('role', 'alert')
    banner.textContent = msg
    board.prepend(banner)
    setTimeout(() => banner.remove(), 4000)
  }

  Sortable.create(tbody, {
    animation: 150,
    ghostClass: 'portal-backlog__row--ghost',
    chosenClass: 'portal-backlog__row--chosen',
    dragClass: 'portal-backlog__row--dragging',
    onEnd(evt) {
      const row = evt.item
      const wpId = row.dataset.wpId
      const lockVersion = parseInt(row.dataset.lockVersion || '0', 10)

      if (!wpId || !lockVersion) {
        flash('Drag failed: missing work-package id / lock version.', 'error')
        // Revert to the server's view.
        window.location.reload()
        return
      }

      // The new position is the row's index in the tbody after the
      // drop (1-based to match OP semantics — Sortable is 0-based).
      const newPosition = Array.prototype.indexOf.call(
        tbody.children, row,
      ) + 1

      // Optimistically bump lockVersion; the server returns the real
      // one on success.
      row.dataset.lockVersion = String(lockVersion + 1)

      const url = (
        '/api/portal/openproject/' + encodeURIComponent(opId)
        + '/work_packages/' + encodeURIComponent(wpId)
        + '/reorder'
      )

      fetch(url, {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          newPosition: newPosition,
          lockVersion: lockVersion,
        }),
      })
      .then((r) => r.json().then((b) => ({ status: r.status, body: b })))
      .then(({ status, body }) => {
        if (body && body.ok) {
          const newLV = body.workPackage && body.workPackage.lockVersion
          if (typeof newLV === 'number') {
            row.dataset.lockVersion = String(newLV)
          }
          flash('Backlog reordered.', 'success')
          return
        }

        if (status === 409) {
          flash(
            (body && body.message)
            || 'OpenProject rejected the reorder — story was edited elsewhere. Refreshing...',
            'error'
          )
          window.setTimeout(() => window.location.reload(), 1500)
          return
        }
        // Other failure: revert.
        flash(
          (body && body.message)
          || 'Could not reorder (HTTP ' + status + ').',
          'error'
        )
        window.location.reload()
      })
      .catch((err) => {
        flash(
          'Network error: ' + (err && err.message ? err.message : 'unreachable'),
          'error'
        )
        window.location.reload()
      })
    },
  })
})()