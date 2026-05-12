#!/usr/bin/env bash
set -euo pipefail

# 在源机器执行：
# 1) 导出数据库
# 2) 打包代码 + uploads + 文档
# 3) scp 到目标机 /tmp

VARS_FILE="${1:-/www/wwwroot/migration-vars.env}"
if [[ ! -f "${VARS_FILE}" ]]; then
  echo "未找到变量文件: ${VARS_FILE}" >&2
  exit 1
fi

# shellcheck disable=SC1090
source "${VARS_FILE}"

for cmd in mysqldump rsync tar scp; do
  command -v "${cmd}" >/dev/null 2>&1 || { echo "缺少命令: ${cmd}" >&2; exit 1; }
done

STAMP="$(date +%Y%m%d_%H%M%S)"
WORK_DIR="/tmp/chattrainer_migrate_${PROJECT_TAG}_${STAMP}"
PKG_NAME="chattrainer_migrate_${PROJECT_TAG}_${STAMP}.tar.gz"
PKG_PATH="/tmp/${PKG_NAME}"

mkdir -p "${WORK_DIR}/app" "${WORK_DIR}/db" "${WORK_DIR}/meta"

echo "[1/5] 导出数据库 ${SRC_DB_NAME} ..."
DUMP_OPTS=(
  --default-character-set=utf8mb4
  --single-transaction
  --no-tablespaces
  --routines
  --triggers
  --events
  --skip-lock-tables
)
if mysqldump --help 2>/dev/null | rg -q "column-statistics"; then
  DUMP_OPTS+=(--column-statistics=0)
fi
if mysqldump --help 2>/dev/null | rg -q "set-gtid-purged"; then
  DUMP_OPTS+=(--set-gtid-purged=OFF)
fi
MYSQL_PWD="${SRC_DB_PASS}" mysqldump \
  -h "${SRC_DB_HOST}" -P "${SRC_DB_PORT}" -u "${SRC_DB_USER}" \
  "${DUMP_OPTS[@]}" "${SRC_DB_NAME}" > "${WORK_DIR}/db/${SRC_DB_NAME}.sql"

# 兜底处理：若导出中混入 MySQL8 专属 collation，则统一替换
sed -i 's/utf8mb4_0900_ai_ci/utf8mb4_unicode_ci/g' "${WORK_DIR}/db/${SRC_DB_NAME}.sql"

echo "[2/5] 打包项目代码 ..."
rsync -a "${SRC_APP_DIR}/" "${WORK_DIR}/app/chattrainer/" \
  --exclude ".git" \
  --exclude "**/__pycache__" \
  --exclude "frontend/node_modules" \
  --exclude "frontend/dist" \
  --exclude "backend/venv" \
  --exclude "backups"

if [[ -f "/www/wwwroot/咨询话术模拟训练系统-项目开发文档.md" ]]; then
  cp "/www/wwwroot/咨询话术模拟训练系统-项目开发文档.md" "${WORK_DIR}/app/"
fi

cp "${VARS_FILE}" "${WORK_DIR}/meta/migration-vars.env"

cat > "${WORK_DIR}/meta/manifest.txt" <<MANIFEST
PROJECT_TAG=${PROJECT_TAG}
CREATED_AT=$(date '+%F %T')
SRC_APP_DIR=${SRC_APP_DIR}
SRC_DB=${SRC_DB_HOST}:${SRC_DB_PORT}/${SRC_DB_NAME}
TARGET_SSH=${TARGET_SSH_USER}@${TARGET_SSH_HOST}:${TARGET_SSH_PORT}
MANIFEST

echo "[3/5] 生成压缩包 ..."
tar -C "${WORK_DIR}" -czf "${PKG_PATH}" .

echo "[4/5] 上传到目标机 /tmp（会提示输入目标机SSH密码）..."
scp -P "${TARGET_SSH_PORT}" "${PKG_PATH}" "${TARGET_SSH_USER}@${TARGET_SSH_HOST}:/tmp/"

echo "[5/5] 完成"
echo "包路径: ${PKG_PATH}"
echo "目标机路径: /tmp/${PKG_NAME}"
echo "下一步：登录目标机执行 migrate_deploy_on_target.sh"
