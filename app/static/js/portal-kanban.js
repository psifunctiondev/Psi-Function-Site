/**
 * portal-kanban.js — SortableJS drag-drop for the project summary Status tab.
 *
 * Wires one Sortable per status column. When a card moves between
 * columns we POST to the API with the target status + the WP's
 * lockVersion, optimistically update the column counts, and revert on
 * failure (with a flash banner).
 *
 * The endpoint:
 *   POST /api/portal/openproject/<op>/work_packages/<wp>/status
 *   body: { targetStatus, lockVersion }
 *
 * The server returns either
 *   { ok: true, workPackage: { id, lockVersion, ... } }   — we update
 *   the card's data-lock-version attribute from the response so the
 *   next move carries the right lockVersion;
 * or
 *   { ok: false, code, message, status }                 — we revert
 *   the DOM and flash the message.
 *
 * SortableJS is a zero-dep library; we import it via Vite (added in
 * commit 5c). If Sortable isn't available the rest of the page still
 * works — drag is a progressive enhancement on top of the read-only
 * kanban render.
 */

import Sortable from 'sortablejs'

;(function () {
  'use strict'

  const board = document.querySelector('.portal-kanban')
  if (!board) return  // not on the Status tab — exit silently.

  const opId = board.dataset.opId
  const slug = board.dataset.slug
  if (!opId || !slug) {
    console.warn('portal-kanban: missing data-op-id / data-slug on board; drag disabled.')
    return
  }

  const cols = Array.from(board.querySelectorAll('.portal-kanban__col'))
  if (!cols.length) return

  const FLASH_CLASS = 'portal-kanban__flash'

  function flash(msg, level) {
    // Remove any prior flash so rapid-fail errors don't stack.
    const prior = board.querySelector('.' + FLASH_CLASS)
    if (prior) prior.remove()

    const banner = document.createElement('div')
    banner.className = FLASH_CLASS + ' ' + FLASH_CLASS + '--' + (level || 'error')
    banner.setAttribute('role', 'alert')
    banner.textContent = msg
    board.prepend(banner)

    // Auto-dismiss after 4s. The success/info flashes still disappear
    // so the kanban doesn't accumulate banners on every drag.
    setTimeout(() => banner.remove(), 4000)
  }

  function recountColumn(col) {
    const cardEls = col.querySelectorAll('.portal-kanban__card')
    const spSum = Array.from(cardEls).reduce((acc, c) => {
      const sp = parseInt(c.dataset.storyPoints || '0', 10)
      return acc + (isNaN(sp) ? 0 : sp)
    }, 0)
    const countEl = col.querySelector('.portal-kanban__col-count')
    if (countEl) {
      const ptsLabel = cardEls.length === 1 ? 'pt' : 'pts'
      countEl.textContent =
        cardEls.length + ' ' + (cardEls.length === 1 ? 'story' : 'stories')
        + ' · ' + spSum + ' ' + ptsLabel
    }
  }

  function recountAll() {
    cols.forEach(recountColumn)
  }

  // Reconcile all column counts on load — the server-rendered counts
  // are correct but it's cheap to verify and catches the case where
  // the JS is the source of truth on a subsequent re-render.
  recountAll()

  cols.forEach((col) => {
    Sortable.create(col, {
      group: 'portal-kanban-cards',
      animation: 150,
      ghostClass: 'portal-kanban__card--ghost',
      chosenClass: 'portal-kanban__card--chosen',
      dragClass: 'portal-kanban__card--dragging',
      // We don't allow dropping a card back into its own column to
      // count as a change — Sortable's onMove returns false in that
      // case so no POST fires.
      onMove(evt) {
        return evt.to !== evt.from
      },
      onEnd(evt) {
        const card = evt.item
        const targetCol = evt.to
        const targetStatus = targetCol.dataset.status
        const wpId = card.dataset.wpId
        const lockVersion = parseInt(card.dataset.lockVersion || '0', 10)
        const fromStatus = (evt.from).dataset.status

        if (!targetStatus || !wpId || !lockVersion) {
          flash('Drag failed: missing target status / work-package id / lock version.', 'error')
          // Revert the DOM since the server never heard about it.
          evt.from.insertBefore(card, evt.from.children[evt.oldIndex] || null)
          return
        }

        // Optimistic UI — the card is already in the new column. We
        // update the counts immediately and recount the source column
        // after the network call returns (whether success or failure).
        recountColumn(targetCol)
        // Optimistically flip the lockVersion to the "next" guess; the
        // server returns the real one and we update on success.
        card.dataset.lockVersion = String(lockVersion + 1)

        const url = (
          '/api/portal/openproject/' + encodeURIComponent(opId)
          + '/work_packages/' + encodeURIComponent(wpId)
          + '/status'
        )

        fetch(url, {
          method: 'POST',
          credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            targetStatus: targetStatus,
            lockVersion: lockVersion,
          }),
        })
        .then((r) => r.json().then((b) => ({ status: r.status, body: b })))
        .then(({ status, body }) => {
          if (body && body.ok) {
            // Server returned the canonical WP — refresh lockVersion
            // from the response so the next drag carries the right
            // token.
            const newLV = body.workPackage && body.workPackage.lockVersion
            if (typeof newLV === 'number') {
              card.dataset.lockVersion = String(newLV)
            } else {
              // Fallback: we already optimistically bumped above.
            }
            // Update the card's status label (if it had one).
            const statusEl = card.querySelector('.portal-kanban__card-status')
            if (statusEl) statusEl.textContent = targetStatus
            flash(
              'Moved to ' + targetStatus + '.',
              'success'
            )
            recountColumn(targetCol)
            return
          }

          // Failure — revert.
          if (status === 409) {
            // Stale lockVersion — server has fresher state. Easiest
            // revert is to send the user back to the page so they see
            // the canonical DOM.
            flash(
              (body && body.message)
              || 'OpenProject rejected the change — someone else edited this story first. Refreshing...',
              'error'
            )
            window.setTimeout(() => window.location.reload(), 1500)
            return
          }
          // Other failures: revert the DOM.
          evt.from.insertBefore(card, evt.from.children[evt.oldIndex] || null)
          flash(
            (body && body.message)
            || 'Could not update status (HTTP ' + status + ').',
            'error'
          )
          recountAll()
        })
        .catch((err) => {
          // Network failure — revert.
          evt.from.insertBefore(card, evt.from.children[evt.oldIndex] || null)
          flash(
            'Network error: ' + (err && err.message ? err.message : 'unreachable'),
            'error'
          )
          recountAll()
        })
      },
    })
  })
})()