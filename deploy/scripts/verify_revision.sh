#!/usr/bin/env bash
set -euo pipefail

ENV_NAME="${1:?usage: verify_revision.sh <env> <expected_sha>}"
EXPECTED_SHA="${2:?usage: verify_revision.sh <env> <expected_sha>}"

LIVE_SHA="$(cat /opt/consulting-site/${ENV_NAME}/current/REVISION)"

if [[ "${LIVE_SHA}" != "${EXPECTED_SHA}" ]]; then
  echo "ERROR: ${ENV_NAME} revision mismatch"
  echo "expected: ${EXPECTED_SHA}"
  echo "actual:   ${LIVE_SHA}"
  exit 1
fi

echo "OK: ${ENV_NAME} revision is ${LIVE_SHA}"
