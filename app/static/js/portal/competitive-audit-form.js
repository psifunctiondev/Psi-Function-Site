/*
 * competitive-audit-form.js
 *
 * Drives the "Add competitor" cloning behavior on the Drift & Anchor
 * competitive-audit intake form. Extracted from an inline <script>
 * block on the template in 2026-07 so the page no longer violates the
 * site's strict CSP (script-src 'self').
 *
 * Behavior contract (UX model B, Quinn 2026-07-22):
 *   - The Add button lives OUTSIDE the default card, in its own row
 *     at the bottom of .competitive-audit-extra-cards. It's always
 *     the LAST child of that container.
 *   - On each "Add" click, clone the default competitor sub-card
 *     (data-competitive-audit-card + data-card-index="1") and insert
 *     it into .competitive-audit-extra-cards, BEFORE the Add button.
 *   - Re-index every occurrence of `competitor_1_`, `id="competitor_1_`,
 *     `for="competitor_1_`, and the card-index attribute to a fresh
 *     `competitor_N_` so the form posts competitor_2, competitor_3, ...
 *   - Rewrite the cloned card's title text "Competitor 1" → "Competitor N".
 *   - Reset all cloned input values to empty (text) or checked (checkbox).
 *   - Append a "Remove" row to each clone; the default card stays put.
 *
 * UX model B replaces the prior model where the Add button lived
 * inline on the socials row of the default card. Quinn asked for
 * model B after a live portal test on 2026-07-22: the Add button
 * should always sit next to the last competitor, not at the top of
 * the form on Competitor 1.
 *
 * No upper bound on clones — Quinn flagged that a cap may be added later.
 */
(function () {
  var form = document.querySelector('.competitive-audit-form-card');
  if (!form) return;

  var defaultCard = form.querySelector(
    '[data-competitive-audit-card][data-card-index="1"]'
  );
  var addBtn = form.querySelector('[data-competitive-audit-add]');
  var extraContainer = form.querySelector(
    '[data-competitive-audit-extra-cards]'
  );
  if (!defaultCard || !addBtn || !extraContainer) return;

  // Anchor for new clones: insertBefore() each new card before the
  // Add button so the button stays as the LAST child of
  // .competitive-audit-extra-cards (UX model B).
  var addRow = addBtn.closest('[data-competitive-audit-add-row]') || addBtn;

  function nextIndex() {
    var cards = form.querySelectorAll('[data-competitive-audit-card]');
    var max = 0;
    cards.forEach(function (c) {
      var n = parseInt(c.getAttribute('data-card-index'), 10);
      if (!isNaN(n) && n > max) max = n;
    });
    return max + 1;
  }

  function reindex(srcHtml, newIndex) {
    // Replace every occurrence of competitor_1_, id="competitor_1_,
    // and for="competitor_1_ with the new index. Also rename the
    // card-index attribute itself.
    var html = srcHtml
      .replace(/competitor_1_/g, 'competitor_' + newIndex + '_')
      .replace(/id="competitor_1_/g, 'id="competitor_' + newIndex + '_')
      .replace(/for="competitor_1_/g, 'for="competitor_' + newIndex + '_')
      .replace(/data-card-index="1"/, 'data-card-index="' + newIndex + '"')
      .replace(
        'class="competitive-audit-col__title">Competitor 1<',
        'class="competitive-audit-col__title">Competitor ' + newIndex + '<'
      );
    // Reset all input values inside the clone — the cloned card
    // starts blank, pre-fill only lives on the default card.
    html = html.replace(
      /(<input\b[^>]*?)(?:\s+value="[^"]*")?(\s*\/?>)/g,
      function (_match, head, tail) {
        if (/type="checkbox"/.test(head)) {
          // Default-checked on clones matches the empty-form UX.
          return head + ' checked' + tail;
        }
        return head + ' value=""' + tail;
      }
    );
    return html;
  }

  function makeRemoveButton(newIndex) {
    var row = document.createElement('div');
    row.className = 'competitive-audit-col__remove-row';
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'btn';
    btn.setAttribute('data-competitive-audit-remove', '');
    btn.setAttribute('aria-label', 'Remove competitor ' + newIndex);
    btn.textContent = 'Remove';
    btn.addEventListener('click', function () {
      var card = btn.closest('[data-competitive-audit-card]');
      if (card && card !== defaultCard) card.remove();
    });
    row.appendChild(btn);
    return row;
  }

  addBtn.addEventListener('click', function () {
    var newIndex = nextIndex();
    var wrapper = document.createElement('div');
    wrapper.innerHTML = reindex(defaultCard.outerHTML, newIndex);
    var newCard = wrapper.firstElementChild;
    if (!newCard) return;
    // Append a Remove row (the default card's Remove row is omitted
    // — Quinn didn't ask for it on the primary card; it stays
    // until the form is submitted or the user backs out).
    newCard.appendChild(makeRemoveButton(newIndex));
    // UX model B: insert the clone BEFORE the Add button so the
    // button stays as the LAST child of extra-cards. The button
    // stays visible at the bottom of the list no matter how many
    // competitors have been added.
    extraContainer.insertBefore(newCard, addRow);
  });
})();
