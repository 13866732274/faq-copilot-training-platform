#!/usr/bin/env bash
set -euo pipefail

# 在目标机器执行：
# 1) 解压迁移包
# 2) 导入 MariaDB
# 3) 部署后端(systemd) + 构建前端 + 写Nginx

VARS_FILE="${1:-/www/wwwroot/migration-vars.env}"
if [[ ! -f "${VARS_FILE}" ]]; then
  echo "未找到变量文件: ${VARS_FILE}" >&2
  exit 1
fi

# shellcheck disable=SC1090
source "${VARS_FILE}"

for cmd in tar rsync mysql nginx systemctl; do
  command -v "${cmd}" >/dev/null 2>&1 || { echo "缺少命令: ${cmd}" >&2; exit 1; }
done

LATEST_PKG="$(ls -t /tmp/chattrainer_migrate_${PROJECT_TAG}_*.tar.gz 2>/dev/null | head -n 1 || true)"
if [[ -z "${LATEST_PKG}" ]]; then
  echo "未找到迁移包: /tmp/chattrainer_migrate_${PROJECT_TAG}_*.tar.gz" >&2
  exit 1
fi

STAMP="$(date +%Y%m%d_%H%M%S)"
RELEASE_DIR="${TARGET_RELEASES_DIR}/${STAMP}"
mkdir -p "${RELEASE_DIR}" "${TARGET_RELEASES_DIR}" "$(dirname "${TARGET_APP_DIR}")"

echo "[1/8] 解压迁移包: ${LATEST_PKG}"
tar -C "${RELEASE_DIR}" -xzf "${LATEST_PKG}"

echo "[2/8] 同步代码到 ${TARGET_APP_DIR}"
mkdir -p "${TARGET_APP_DIR}"
rsync -a "${RELEASE_DIR}/app/chattrainer/" "${TARGET_APP_DIR}/"

if [[ -f "${RELEASE_DIR}/app/咨询话术模拟训练系统-项目开发文档.md" ]]; then
  cp -f "${RELEASE_DIR}/app/咨询话术模拟训练系统-项目开发文档.md" "/www/wwwroot/"
fi

echo "[3/8] 准备数据库 ${TARGET_DB_NAME}（目标: MariaDB ${TARGET_MARIADB_VERSION}）"
mysql -h"${TARGET_DB_HOST}" -P"${TARGET_DB_PORT}" -u"${TARGET_DB_USER}" -p"${TARGET_DB_PASS}" <<SQL
CREATE DATABASE IF NOT EXISTS \
  \`${TARGET_DB_NAME}\` DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE USER IF NOT EXISTS '${SRC_DB_USER}'@'127.0.0.1' IDENTIFIED BY '${SRC_DB_PASS}';
CREATE USER IF NOT EXISTS '${SRC_DB_USER}'@'localhost' IDENTIFIED BY '${SRC_DB_PASS}';
GRANT ALL PRIVILEGES ON \`${TARGET_DB_NAME}\`.* TO '${SRC_DB_USER}'@'127.0.0.1';
GRANT ALL PRIVILEGES ON \`${TARGET_DB_NAME}\`.* TO '${SRC_DB_USER}'@'localhost';
FLUSH PRIVILEGES;
SQL

echo "[4/8] 导入数据库"
mysql -h"${TARGET_DB_HOST}" -P"${TARGET_DB_PORT}" -u"${TARGET_DB_USER}" -p"${TARGET_DB_PASS}" "${TARGET_DB_NAME}" < "${RELEASE_DIR}/db/${SRC_DB_NAME}.sql"

echo "[5/8] 部署后端依赖 + 数据库迁移"
cd "${TARGET_APP_DIR}/backend"
if [[ ! -x "venv/bin/python" ]]; then
  python3 -m venv venv
fi
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r requirements.txt

DB_URL="mysql+asyncmy://${SRC_DB_USER}:${SRC_DB_PASS}@127.0.0.1:${TARGET_DB_PORT}/${TARGET_DB_NAME}"
if [[ -f ".env" ]]; then
  if grep -q "^DATABASE_URL=" .env; then
    sed -i "s|^DATABASE_URL=.*|DATABASE_URL=${DB_URL}|" .env
  else
    printf '\nDATABASE_URL=%s\n' "${DB_URL}" >> .env
  fi
else
  cp .env.example .env
  sed -i "s|^DATABASE_URL=.*|DATABASE_URL=${DB_URL}|" .env
fi

./venv/bin/alembic upgrade head

echo "[6/8] 构建前端"
cd "${TARGET_APP_DIR}/frontend"
npm install
npm run build

echo "[7/8] 写 systemd 服务"
cat > /etc/systemd/system/chattrainer-backend.service <<SERVICE
[Unit]
Description=ChatTrainer Backend (FastAPI)
After=network.target mariadb.service

[Service]
Type=simple
WorkingDirectory=${TARGET_APP_DIR}/backend
Environment=PYTHONPATH=${TARGET_APP_DIR}/backend
ExecStart=${TARGET_APP_DIR}/backend/venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=3
User=root

[Install]
WantedBy=multi-user.target
SERVICE

systemctl daemon-reload
systemctl enable --now chattrainer-backend

echo "[8/8] 写 Nginx 配置并重载"
cat > "${TARGET_NGINX_CONF}" <<NGINX
server {
    listen 80;
    server_name _;

    root ${TARGET_APP_DIR}/frontend/dist;
    index index.html;

    location /api/ {
        proxy_pass http://127.0.0.1:8000/api/;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    location / {
        try_files \$uri \$uri/ /index.html;
    }
}
NGINX

nginx -t
systemctl reload nginx

echo "部署完成。"
echo "后端健康检查: ${APP_HEALTHCHECK_URL}"
echo "本机测试: curl -s ${APP_HEALTHCHECK_URL}"
