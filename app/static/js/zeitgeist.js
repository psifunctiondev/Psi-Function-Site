/**
 * zeitgeist.js — Client-side faceted filtering for the Zeitgeist news feed.
 * Updates the URL query string and reloads filtered results without a full
 * page refresh (progressive enhancement — works without JS via form submit).
 */

;(function () {
  'use strict'

  const checkboxes = document.querySelectorAll('.zeitgeist-filters__checkbox')
  if (!checkboxes.length) return

  function getSelectedSlugs() {
    return Array.from(checkboxes)
      .filter((cb) => cb.checked)
      .map((cb) => cb.value)
  }

  function updateFeed() {
    const slugs = getSelectedSlugs()
    const url = new URL(window.location)

    if (slugs.length) {
      url.searchParams.set('tags', slugs.join(','))
    } else {
      url.searchParams.delete('tags')
    }

    // Update URL without full reload, then fetch new content
    window.history.replaceState(null, '', url)
    window.location.reload()
  }

  checkboxes.forEach((cb) => {
    cb.addEventListener('change', updateFeed)
  })
})()
