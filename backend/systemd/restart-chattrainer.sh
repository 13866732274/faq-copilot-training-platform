#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   BOT_WEBHOOK_SECRET=sk-xxxx FAQ_BOT_PASSWORD=xxxx ./restart-chattrainer.sh
# or export envs beforehand.

if [[ -z "${BOT_WEBHOOK_SECRET:-}" ]]; then
  echo "ERROR: BOT_WEBHOOK_SECRET is required"
  exit 1
fi

if [[ -z "${FAQ_BOT_PASSWORD:-}" ]]; then
  echo "WARN: FAQ_BOT_PASSWORD is empty; /api/v1/bot/wechat-faq will return reply=null"
fi

sudo systemctl set-environment \
  BOT_WEBHOOK_SECRET="${BOT_WEBHOOK_SECRET}" \
  FAQ_BOT_PASSWORD="${FAQ_BOT_PASSWORD:-}" \
  FAQ_BOT_USERNAME="${FAQ_BOT_USERNAME:-wechat_bot}" \
  FAQ_API_BASE="${FAQ_API_BASE:-http://127.0.0.1:8000/api/v1}"

if systemctl list-unit-files chattrainer-backend.service >/dev/null 2>&1; then
  sudo systemctl restart chattrainer-backend
  echo "chattrainer-backend restarted with BOT_WEBHOOK_SECRET + FAQ_BOT_* envs"
elif systemctl list-unit-files chattrainer.service >/dev/null 2>&1; then
  sudo systemctl restart chattrainer
  echo "chattrainer restarted with BOT_WEBHOOK_SECRET + FAQ_BOT_* envs"
else
  echo "ERROR: neither chattrainer-backend.service nor chattrainer.service exists"
  exit 1
fi
