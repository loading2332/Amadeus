#!/usr/bin/env bash
# Installed as /usr/local/sbin/deploy-amadeus on the production host.
# It deliberately has no input: the GitHub Actions SSH key is restricted to
# this command in authorized_keys.
set -Eeuo pipefail

readonly APP_DIR="/root/develop/amadeus"
readonly COMPOSE=(docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file .env)

exec 9>/var/lock/amadeus-deploy.lock
if ! flock -n 9; then
  echo "another Amadeus deployment is already running" >&2
  exit 1
fi

cd "$APP_DIR"

if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "refusing deployment: production worktree contains local changes" >&2
  exit 1
fi

git switch main
git pull --ff-only origin main

"${COMPOSE[@]}" build api worker migrate
"${COMPOSE[@]}" run --rm --no-deps migrate
"${COMPOSE[@]}" up -d --force-recreate --no-deps api worker

for _ in {1..20}; do
  if curl --fail --silent --show-error --max-time 5 http://127.0.0.1:8000/ >/dev/null; then
    echo "Amadeus deployment succeeded at $(git rev-parse --short HEAD)"
    exit 0
  fi
  sleep 3
done

echo "Amadeus API did not become healthy" >&2
"${COMPOSE[@]}" logs --tail=100 api >&2
exit 1
