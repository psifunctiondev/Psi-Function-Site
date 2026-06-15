#!/usr/bin/env bash
# db_migrate.sh — apply Alembic migrations and (optionally) seed flows
# against the configured local instance.
#
# Mirrors the deploy-side seed gating from deploy/scripts/deploy_release.sh
# (SEED_ACME_DEMO=1 -> acme-demo + acme-resources) so local and prod use
# the same knobs.
set -Eeuo pipefail

usage() {
  cat <<'EOF'
Usage: bash deploy/scripts/db_migrate.sh [options]

Apply Alembic migrations to the configured instance. Optionally run dev seed flows.

By default, only migrations run. Pass --with-seeds to enable all known seeds,
or set individual env vars for selective seeding.

Options:
  --with-seeds        Enable all known seed flows (acme-demo, acme-resources,
                      taxonomy, work-demo).
  -h, --help          Show this help and exit.

Seeds (each gated on its own env var):
  SEED_ACME_DEMO=1         flask client seed-acme-demo + seed-acme-resources
                           (matches deploy_release.sh semantics)
  SEED_TAXONOMY=1          flask seed-taxonomy
  SEED_WORK_DEMO=1         flask seed-work-demo

--with-seeds sets all three env vars.

Seed failures are warned and skipped so a single bad seed does not block
the others. Migrations run unconditionally and abort the script on failure.

Examples:
  bash deploy/scripts/db_migrate.sh
  bash deploy/scripts/db_migrate.sh --with-seeds
  SEED_ACME_DEMO=1 bash deploy/scripts/db_migrate.sh
  SEED_TAXONOMY=1 SEED_WORK_DEMO=1 bash deploy/scripts/db_migrate.sh
EOF
}

WITH_SEEDS=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --with-seeds) WITH_SEEDS=1; shift ;;
    -h|--help)    usage; exit 0 ;;
    *)            echo "Unknown option: $1" >&2; usage >&2; exit 1 ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

if [ -z "${VIRTUAL_ENV:-}" ]; then
  if [ ! -d ".venv" ]; then
    echo "ERROR: .venv not found at $REPO_ROOT/.venv" >&2
    echo "Run deploy/scripts/bootstrap_local.sh first to set up the local venv." >&2
    exit 1
  fi
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

export FLASK_APP="${FLASK_APP:-wsgi:app}"

if [ "$WITH_SEEDS" -eq 1 ]; then
  export SEED_ACME_DEMO=1
  export SEED_TAXONOMY=1
  export SEED_WORK_DEMO=1
fi

echo "==> Repository root: $REPO_ROOT"
echo "==> Flask app: $FLASK_APP"
echo "==> Venv: ${VIRTUAL_ENV:-inherited}"
echo

echo "==> Running migrations (flask db upgrade)"
flask db upgrade
echo

if [ "${SEED_ACME_DEMO:-0}" = "1" ]; then
  echo "==> Seeding: ACME demo client"
  flask client seed-acme-demo || echo "WARN: seed-acme-demo failed; continuing" >&2
  echo "==> Seeding: ACME showcase resources"
  flask client seed-acme-resources || echo "WARN: seed-acme-resources failed; continuing" >&2
else
  echo "    (ACME seed skipped; set SEED_ACME_DEMO=1 or pass --with-seeds to enable)"
fi

if [ "${SEED_TAXONOMY:-0}" = "1" ]; then
  echo "==> Seeding: taxonomy"
  flask seed-taxonomy || echo "WARN: seed-taxonomy failed; continuing" >&2
fi

if [ "${SEED_WORK_DEMO:-0}" = "1" ]; then
  echo "==> Seeding: work demo"
  flask seed-work-demo || echo "WARN: seed-work-demo failed; continuing" >&2
fi

echo
echo "==> Done"
