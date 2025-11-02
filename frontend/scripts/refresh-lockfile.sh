#!/usr/bin/env bash
set -euo pipefail

# Resolve the frontend directory regardless of where the script is invoked from.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

if ! command -v docker >/dev/null 2>&1; then
  echo "Error: docker is required to regenerate package-lock.json without a local Node installation." >&2
  exit 1
fi

# Allow overriding the Node image tag (e.g., NODE_IMAGE=node:22 ./refresh-lockfile.sh)
NODE_IMAGE="${NODE_IMAGE:-node:20}"

# Use the current user/group when available so generated files are not owned by root.
if command -v id >/dev/null 2>&1; then
  UID_FLAG="$(id -u)"
  GID_FLAG="$(id -g)"
else
  UID_FLAG=0
  GID_FLAG=0
fi

cd "${FRONTEND_DIR}"

printf 'Regenerating package-lock.json with %s...\n' "${NODE_IMAGE}"
docker run --rm \
  -u "${UID_FLAG}:${GID_FLAG}" \
  -v "${FRONTEND_DIR}:/app" \
  -w /app \
  "${NODE_IMAGE}" \
  bash -lc "set -e; echo 'node version: ' \\$(node --version); echo 'npm version: ' \\$(npm --version); npm install --package-lock-only"

echo "Done. Remember to commit the updated package-lock.json."
