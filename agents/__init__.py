# agents package — internal agent workers bundled with the Psi-Function-Site
# release. Run from the release root:
#
#     .venv/bin/python -m agents.driftbot.worker
#
# Path-C (2026-07-16) moved the DrifterBot worker here from
# brandsight/agents/drifterbot/. The worker runs as its own systemd unit
# (deploy/systemd/consulting-site-drifterbot@.service) but is installed
# via the same release pipeline as the web app.