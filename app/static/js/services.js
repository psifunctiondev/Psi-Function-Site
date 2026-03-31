/* =============================================================
   js/services.js
   Interaction logic for the Services page detail panel.

   Behaviour:
     - Clicking a .svc-card shows the matching #panel-{service}
       and hides the previously visible panel.
     - Clicking anywhere outside .services-holder resets the
       detail panel back to the placeholder image.

   Depends on: services.html panel markup and services.css
   ============================================================= */

(function () {
  const placeholder = document.getElementById('panel-placeholder');
  if (!placeholder) return; // not on the services page
  let currentPanel = placeholder;

  function showPanel(nextPanel) {
    if (nextPanel === currentPanel) return;

    // Fully hide outgoing panel — remove both classes so the
    // animation's `forwards` fill can't keep it visible
    currentPanel.classList.remove('is-visible', 'is-entering');
    currentPanel.setAttribute('aria-hidden', 'true');

    // Show incoming panel and trigger entrance animation
    nextPanel.classList.remove('is-entering');
    void nextPanel.offsetWidth; // reflow to restart animation
    nextPanel.classList.add('is-visible', 'is-entering');
    nextPanel.setAttribute('aria-hidden', 'false');

    currentPanel = nextPanel;
  }

  function activate(btn) {
    document.querySelectorAll('.svc-card').forEach(b => {
      b.classList.remove('is-active');
      b.setAttribute('aria-pressed', 'false');
    });
    btn.classList.add('is-active');
    btn.setAttribute('aria-pressed', 'true');

    const nextPanel = document.getElementById('panel-' + btn.dataset.service);
    if (nextPanel) showPanel(nextPanel);
  }

  function reset() {
    document.querySelectorAll('.svc-card').forEach(b => {
      b.classList.remove('is-active');
      b.setAttribute('aria-pressed', 'false');
    });
    showPanel(placeholder);
  }

  // Card clicks — stopPropagation prevents the document listener firing
  document.querySelectorAll('.svc-card').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      activate(btn);
    });
  });

  // Click anywhere outside the services holder → reset to placeholder
  document.addEventListener('click', (e) => {
    if (!e.target.closest('.services-holder')) {
      reset();
    }
  });
})();
