#!/usr/bin/env bash
# Server side of deploy/deploy.ps1. Runs in one interactive ssh session and asks for the
# sudo password once. Touches only: /var/www/ask-washington, the Docker Compose project
# "ask-washington", and the nginx site ask.inmersoft.com.
#
# Usage: bash remote-deploy.sh <staging dir> <app port> <certbot email> [force_nginx 0|1]
set -euo pipefail

STAGE="${1:?staging dir}"
APP_PORT="${2:?app port}"
EMAIL="${3:?certbot email}"
FORCE_NGINX="${4:-0}"

DOMAIN="ask.inmersoft.com"
PROJECT="ask-washington"
APP_DIR="/var/www/${PROJECT}"
SITE_AVAILABLE="/etc/nginx/sites-available/${DOMAIN}"
SITE_ENABLED="/etc/nginx/sites-enabled/${DOMAIN}"
COMPOSE=(docker compose -p "${PROJECT}" -f "${APP_DIR}/docker-compose.prod.yml" --project-directory "${APP_DIR}")

log() { printf '\n==> %s\n' "$*"; }
fail() { printf '\nERROR: %s\n' "$*" >&2; exit 1; }

cleanup_stage() { rm -rf "${STAGE}"; }
trap cleanup_stage EXIT

log "Checking sudo (asked once)"
sudo -v
# Keep the sudo timestamp fresh during the image build.
( while true; do sudo -n true 2>/dev/null; sleep 50; kill -0 "$$" 2>/dev/null || exit; done ) &
SUDO_KEEPALIVE=$!
trap 'kill ${SUDO_KEEPALIVE} 2>/dev/null || true; cleanup_stage' EXIT

for f in app.tar.gz data.dump env.production; do
  [[ -s "${STAGE}/${f}" ]] || fail "missing ${STAGE}/${f}"
done

log "Checking that port ${APP_PORT} is free (or already ours)"
owner="$(sudo docker ps --filter "publish=${APP_PORT}" --format '{{.Names}}' | head -n1)"
if ss -ltnH "( sport = :${APP_PORT} )" | grep -q .; then
  if [[ "${owner}" != "${PROJECT}-app-1" ]]; then
    fail "port ${APP_PORT} is in use by '${owner:-a non-container process}'. Choose another APP_PORT in deploy/.deploy.local. Nothing was changed."
  fi
  echo "port ${APP_PORT} is used by our own container; updating it"
fi

log "Checking that no other nginx site serves ${DOMAIN}"
others="$(sudo grep -rlE "server_name[^;]*\b${DOMAIN//./\\.}\b" /etc/nginx/sites-enabled/ 2>/dev/null | grep -v "/${DOMAIN}$" || true)"
[[ -z "${others}" ]] || fail "another enabled site already uses ${DOMAIN}: ${others}. Nothing was changed."

log "Installing the code in ${APP_DIR}"
sudo mkdir -p "${APP_DIR}"
sudo tar -xzf "${STAGE}/app.tar.gz" -C "${APP_DIR}"
sudo install -m 600 -o root -g root "${STAGE}/env.production" "${APP_DIR}/.env"

log "Building and starting the containers (project ${PROJECT})"
sudo "${COMPOSE[@]}" up -d --build --remove-orphans

log "Waiting for /health on 127.0.0.1:${APP_PORT}"
for i in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:${APP_PORT}/health" >/dev/null 2>&1; then
    echo "healthy after $((i * 5)) s"
    break
  fi
  [[ $i -eq 60 ]] && { sudo "${COMPOSE[@]}" logs --tail 50 app; fail "the app did not become healthy"; }
  sleep 5
done

log "Restoring the vector store dump"
db_user="$(sudo grep -E '^POSTGRES_USER=' "${APP_DIR}/.env" | cut -d= -f2-)"
db_name="$(sudo grep -E '^POSTGRES_DB=' "${APP_DIR}/.env" | cut -d= -f2-)"
# The dump is read by this (non-root) user, who owns the staging dir; only docker needs sudo.
# shellcheck disable=SC2024
sudo "${COMPOSE[@]}" exec -T db pg_restore --clean --if-exists --no-owner --no-privileges \
  -U "${db_user}" -d "${db_name}" < "${STAGE}/data.dump"
sudo "${COMPOSE[@]}" exec -T db psql -U "${db_user}" -d "${db_name}" -tAc \
  "SELECT 'chunks: ' || count(*) FROM data_chunks"
# Drop cached database handles from before the restore.
sudo "${COMPOSE[@]}" restart app
for i in $(seq 1 36); do
  curl -fsS "http://127.0.0.1:${APP_PORT}/health" >/dev/null 2>&1 && break
  [[ $i -eq 36 ]] && fail "the app did not come back after the restore"
  sleep 5
done

log "Configuring nginx for ${DOMAIN}"
created_site=0
linked_site=0
backup=""
if [[ ! -f "${SITE_AVAILABLE}" || "${FORCE_NGINX}" == "1" ]]; then
  if [[ -f "${SITE_AVAILABLE}" ]]; then
    backup="${SITE_AVAILABLE}.bak.$(date +%Y%m%d%H%M%S)"
    sudo cp -p "${SITE_AVAILABLE}" "${backup}"
  fi
  sed "s#127\.0\.0\.1:8710#127.0.0.1:${APP_PORT}#" "${APP_DIR}/deploy/nginx/${DOMAIN}.conf" \
    | sudo tee "${SITE_AVAILABLE}" >/dev/null
  created_site=1
else
  echo "keeping the existing ${SITE_AVAILABLE} (managed by certbot); use -ForceNginx to replace it"
fi
if [[ ! -L "${SITE_ENABLED}" ]]; then
  sudo ln -s "${SITE_AVAILABLE}" "${SITE_ENABLED}"
  linked_site=1
fi

if sudo nginx -t; then
  sudo systemctl reload nginx
else
  echo "nginx -t failed: undoing the site change, nginx was NOT reloaded" >&2
  [[ ${linked_site} -eq 1 ]] && sudo rm -f "${SITE_ENABLED}"
  if [[ ${created_site} -eq 1 ]]; then
    if [[ -n "${backup}" ]]; then sudo mv -f "${backup}" "${SITE_AVAILABLE}"; else sudo rm -f "${SITE_AVAILABLE}"; fi
  fi
  fail "nginx configuration test failed"
fi

log "Requesting or renewing the certificate with certbot"
sudo certbot --nginx -d "${DOMAIN}" --non-interactive --agree-tos --redirect \
  --keep-until-expiring -m "${EMAIL}"

log "Smoke test: POST /ask on 127.0.0.1:${APP_PORT}"
# A real question through retrieval and the LLM (costs a fraction of a cent). On failure the
# service is left running so it can be inspected; only the deploy is marked as failed.
smoke_body="$(mktemp)"
smoke_code="$(curl -s -o "${smoke_body}" -w '%{http_code}' --max-time 90 \
  -H 'Content-Type: application/json' -d '{"question": "What is plan-vivo-kit?"}' \
  "http://127.0.0.1:${APP_PORT}/ask" || true)"
if [[ "${smoke_code}" != "200" ]] || ! grep -q '"sources":\[{' "${smoke_body}"; then
  echo "POST /ask returned HTTP ${smoke_code:-no response}:" >&2
  head -c 600 "${smoke_body}" >&2; echo >&2
  echo "--- last 30 lines of the app logs ---" >&2
  sudo "${COMPOSE[@]}" logs --no-color --tail 30 app >&2
  rm -f "${smoke_body}"
  fail "smoke test failed: the service is still up, but /ask does not answer with sources"
fi
echo "POST /ask: HTTP 200 with sources"
rm -f "${smoke_body}"

log "Done"
sudo "${COMPOSE[@]}" ps
