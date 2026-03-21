#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${1:?usage: smoke_test.sh <base_url>}"

echo "Smoke testing ${BASE_URL}"

curl --fail --silent --show-error "${BASE_URL}/health" | grep -q '"status"[[:space:]]*:[[:space:]]*"ok"'
curl --fail --silent --show-error -I "${BASE_URL}/" | head -n 1 | grep -q "200"

echo "Smoke tests passed for ${BASE_URL}"
