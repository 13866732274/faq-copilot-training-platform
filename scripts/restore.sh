#!/usr/bin/env bash
set -euo pipefail

# 最小化实现：
# - 从 backend/.env 读取 DATABASE_URL
# - 从 .sql 或 .sql.gz 恢复
# - 提供确认提示，避免误操作

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${ENV_FILE:-${PROJECT_ROOT}/backend/.env}"

usage() {
  cat <<'EOF'
用法:
  ./scripts/restore.sh --file /path/to/backup.sql.gz [--yes]

参数:
  --file   必填，备份文件路径（支持 .sql / .sql.gz）
  --yes    可选，跳过二次确认
EOF
}

BACKUP_FILE=""
AUTO_YES="0"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --file)
      BACKUP_FILE="${2:-}"
      shift 2
      ;;
    --yes)
      AUTO_YES="1"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "未知参数: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if [[ -z "${BACKUP_FILE}" ]]; then
  echo "错误: 请通过 --file 指定备份文件" >&2
  usage
  exit 1
fi

if [[ ! -f "${BACKUP_FILE}" ]]; then
  echo "错误: 备份文件不存在: ${BACKUP_FILE}" >&2
  exit 1
fi

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "错误: 未找到环境文件 ${ENV_FILE}" >&2
  exit 1
fi

if ! command -v mysql >/dev/null 2>&1; then
  echo "错误: 未安装 mysql 客户端，请先安装 mysql-client" >&2
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

echo "即将恢复数据库:"
echo "  主机: ${DB_HOST}:${DB_PORT}"
echo "  库名: ${DB_NAME}"
echo "  文件: ${BACKUP_FILE}"
echo "警告: 该操作会覆盖当前数据库中的同名对象。"

if [[ "${AUTO_YES}" != "1" ]]; then
  read -r -p "确认继续? 输入 YES 继续: " CONFIRM
  if [[ "${CONFIRM}" != "YES" ]]; then
    echo "已取消恢复"
    exit 0
  fi
fi

if [[ "${BACKUP_FILE}" == *.sql.gz ]]; then
  gunzip -c "${BACKUP_FILE}" | MYSQL_PWD="${DB_PASSWORD}" mysql -h "${DB_HOST}" -P "${DB_PORT}" -u "${DB_USER}" "${DB_NAME}"
elif [[ "${BACKUP_FILE}" == *.sql ]]; then
  MYSQL_PWD="${DB_PASSWORD}" mysql -h "${DB_HOST}" -P "${DB_PORT}" -u "${DB_USER}" "${DB_NAME}" < "${BACKUP_FILE}"
else
  echo "错误: 仅支持 .sql 或 .sql.gz 文件" >&2
  exit 1
fi

echo "恢复完成: ${DB_NAME}"
