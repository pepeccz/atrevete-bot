#!/usr/bin/env bash
# deploy-admin-prod.sh — deploy the admin-panel production image on the server.
#
# ALWAYS use this script (or the explicit -f flag) instead of plain `docker compose up`.
# Running `docker compose up` without -f auto-merges docker-compose.override.yml,
# which activates the dev build (React StrictMode, HMR) and re-introduces the P0
# infinite spinner bug in the conversations inbox.
#
# Usage (on pepe@server):
#   cd /home/pepe/Proyectos/atrevete-bot
#   bash scripts/deploy-admin-prod.sh

set -euo pipefail

REPO_DIR="/home/pepe/Proyectos/atrevete-bot"

echo "==> Deploying admin-panel (production build)..."
cd "${REPO_DIR}"

docker compose -f docker-compose.yml up -d --build admin-panel

echo ""
echo "==> Verifying NEXT_PUBLIC_API_URL baked into image..."
BAKED_URL=$(docker compose -f docker-compose.yml exec admin-panel printenv NEXT_PUBLIC_API_URL 2>/dev/null || true)

if [ -z "${BAKED_URL}" ]; then
  echo "WARNING: Could not read NEXT_PUBLIC_API_URL from container. Verify manually."
else
  echo "NEXT_PUBLIC_API_URL = ${BAKED_URL}"
  if [ "${BAKED_URL}" != "https://api.zonavix.com" ]; then
    echo "WARNING: Expected https://api.zonavix.com but got ${BAKED_URL}"
    echo "         The build arg may not have been set correctly."
  else
    echo "OK: API URL is correct."
  fi
fi

echo ""
echo "==> Deploy complete. Run UAT smoke checks:"
echo "    1. /conversations — list renders, no permanent Cargando…"
echo "    2. /escalations  — 308 redirect to /conversations?filter=escalated (no localhost in Location)"
echo "    3. Dashboard 'Necesitan atención' — click item navigates to /conversations?conversation_id=...&filter=escalated"
echo "    4. No unexpected console errors."
