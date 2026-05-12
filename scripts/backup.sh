#!/usr/bin/env bash
set -euo pipefail

# 最小化实现：
# - 从 backend/.env 读取 DATABASE_URL
# - 执行 mysqldump 并 gzip 压缩
# - 保留最近 N 天备份（默认 30 天）

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${ENV_FILE:-${PROJECT_ROOT}/backend/.env}"
BACKUP_DIR="${BACKUP_DIR:-${PROJECT_ROOT}/backups/mysql}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "错误: 未找到环境文件 ${ENV_FILE}" >&2
  exit 1
fi

if ! command -v mysqldump >/dev/null 2>&1; then
  echo "错误: 未安装 mysqldump，请先安装 mysql-client" >&2
  exit 1
fi

get_env_value() {
  local key="$1"
  while IFS= read -r line || [[ -n "${line}" ]]; do
    [[ -z "${line}" || "${line}" =~ ^[[:space:]]*# ]] && continue
    if [[ "${line}" == "${key}"=* ]]; then
      echo "${line#*=}"
      return 0
    fi
  done <"${ENV_FILE}"
  return 1
}

DATABASE_URL="$(get_env_value "DATABASE_URL" || true)"
if [[ -z "${DATABASE_URL}" ]]; then
  echo "错误: ${ENV_FILE} 中未找到 DATABASE_URL" >&2
  exit 1
fi

readarray -t DB_PARTS < <(python3 - <<'PY' "${DATABASE_URL}"
import sys
from urllib.parse import urlparse, unquote

url = sys.argv[1]
if "://" not in url:
    raise SystemExit("invalid database url")
parsed = urlparse(url)
db = (parsed.path or "").lstrip("/")
print(unquote(parsed.hostname or "127.0.0.1"))
print(str(parsed.port or 3306))
print(unquote(parsed.username or "root"))
print(unquote(parsed.password or ""))
print(unquote(db))
PY
)

DB_HOST="${DB_PARTS[0]}"
DB_PORT="${DB_PARTS[1]}"
DB_USER="${DB_PARTS[2]}"
DB_PASSWORD="${DB_PARTS[3]}"
DB_NAME="${DB_PARTS[4]}"

if [[ -z "${DB_NAME}" ]]; then
  echo "错误: 无法从 DATABASE_URL 解析数据库名" >&2
  exit 1
fi

mkdir -p "${BACKUP_DIR}"

STAMP="$(date +%Y%m%d_%H%M%S)"
OUT_FILE="${BACKUP_DIR}/${DB_NAME}_${STAMP}.sql.gz"
TMP_FILE="${OUT_FILE}.tmp"

echo "开始备份: ${DB_NAME} -> ${OUT_FILE}"
MYSQL_PWD="${DB_PASSWORD}" mysqldump \
  --default-character-set=utf8mb4 \
  --single-transaction \
  --no-tablespaces \
  --routines \
  --triggers \
  -h "${DB_HOST}" \
  -P "${DB_PORT}" \
  -u "${DB_USER}" \
  "${DB_NAME}" | gzip -9 > "${TMP_FILE}"

mv "${TMP_FILE}" "${OUT_FILE}"

python3 - <<'PY' "${BACKUP_DIR}" "${RETENTION_DAYS}"
import os
import sys
import time

backup_dir = sys.argv[1]
retention_days = int(sys.argv[2])
expire_ts = time.time() - retention_days * 24 * 3600
removed = 0
for name in os.listdir(backup_dir):
    if not name.endswith(".sql.gz"):
        continue
    path = os.path.join(backup_dir, name)
    if os.path.isfile(path) and os.path.getmtime(path) < expire_ts:
        os.remove(path)
        removed += 1
print(f"清理完成: 删除 {removed} 个过期备份")
PY

echo "备份完成: ${OUT_FILE}"
