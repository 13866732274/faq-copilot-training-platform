#!/usr/bin/env bash
set -euo pipefail

# 增量发布（在开发机执行）
# 默认行为：
# 1) 仅同步 git 变更文件（未纳入 git 时回退为全量同步项目目录）
# 2) 后端有变更时：执行 alembic upgrade + 重启后端服务
# 3) 前端有变更时：执行 npm run build + reload nginx
# 4) 最后执行健康检查
#
# 用法：
#   bash scripts/incremental_deploy.sh [migration-vars.env路径] [选项]
#
# 选项：
#   --with-backend-deps   后端先 pip install -r requirements.txt
#   --with-frontend-deps  前端先 npm install
#   --no-doc              不同步项目总文档

VARS_FILE="${1:-/www/wwwroot/migration-vars.env}"
if [[ ! -f "${VARS_FILE}" ]]; then
  echo "未找到变量文件: ${VARS_FILE}" >&2
  exit 1
fi
shift || true

INSTALL_BACKEND_DEPS=0
INSTALL_FRONTEND_DEPS=0
SYNC_DOC=1

while [[ $# -gt 0 ]]; do
  case "$1" in
    --with-backend-deps)
      INSTALL_BACKEND_DEPS=1
      shift
      ;;
    --with-frontend-deps)
      INSTALL_FRONTEND_DEPS=1
      shift
      ;;
    --no-doc)
      SYNC_DOC=0
      shift
      ;;
    *)
      echo "未知参数: $1" >&2
      exit 1
      ;;
  esac
done

# shellcheck disable=SC1090
source "${VARS_FILE}"

for cmd in python3 tar git; do
  command -v "${cmd}" >/dev/null 2>&1 || { echo "缺少命令: ${cmd}" >&2; exit 1; }
done

if [[ ! -d "${SRC_APP_DIR}" ]]; then
  echo "SRC_APP_DIR 不存在: ${SRC_APP_DIR}" >&2
  exit 1
fi

DOC_PATH="/www/wwwroot/咨询话术模拟训练系统-项目开发文档.md"

WORK_DIR="$(mktemp -d /tmp/chattrainer_inc_XXXXXX)"
LIST_FILE="${WORK_DIR}/changed-files.txt"
PKG_FILE="${WORK_DIR}/incremental.tgz"

cleanup() {
  rm -rf "${WORK_DIR}"
}
trap cleanup EXIT

echo "[1/6] 收集变更文件 ..."
if git -C "${SRC_APP_DIR}" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  git -C "${SRC_APP_DIR}" status --porcelain | python3 - <<'PY' > "${LIST_FILE}"
import sys
for raw in sys.stdin:
    line = raw.rstrip("\n")
    if not line:
        continue
    entry = line[3:]
    if " -> " in entry:
        entry = entry.split(" -> ", 1)[1]
    print(entry)
PY
else
  printf "backend\nfrontend\n" > "${LIST_FILE}"
fi

python3 - <<'PY' "${LIST_FILE}" > "${LIST_FILE}.filtered"
import sys
from pathlib import Path

infile = Path(sys.argv[1])
rows = []
seen = set()
for raw in infile.read_text(encoding="utf-8", errors="ignore").splitlines():
    p = raw.strip().lstrip("./")
    if not p:
        continue
    if p.startswith("frontend/node_modules/"):
        continue
    if p.startswith("frontend/dist/"):
        continue
    if p.startswith("backend/venv/"):
        continue
    if "/__pycache__/" in p:
        continue
    if p not in seen:
        seen.add(p)
        rows.append(p)
for p in rows:
    print(p)
PY
mv "${LIST_FILE}.filtered" "${LIST_FILE}"

if [[ ! -s "${LIST_FILE}" ]]; then
  echo "未检测到代码文件变更。"
  if [[ "${SYNC_DOC}" -eq 1 && -f "${DOC_PATH}" ]]; then
    echo "仅同步文档 ..."
  else
    echo "结束：无需发布。"
    exit 0
  fi
fi

BACKEND_CHANGED=0
FRONTEND_CHANGED=0
if rg -q "^backend/" "${LIST_FILE}"; then
  BACKEND_CHANGED=1
fi
if rg -q "^frontend/" "${LIST_FILE}"; then
  FRONTEND_CHANGED=1
fi

echo "[2/6] 打包增量文件 ..."
if [[ -s "${LIST_FILE}" ]]; then
  tar -czf "${PKG_FILE}" -C "${SRC_APP_DIR}" -T "${LIST_FILE}"
else
  tar -czf "${PKG_FILE}" -C "${SRC_APP_DIR}" --files-from /dev/null
fi

REMOTE_PKG="/tmp/chattrainer_incremental_$(date +%Y%m%d_%H%M%S).tgz"

echo "[3/6] 上传增量包并远端执行 ..."
python3 - <<'PY' "${TARGET_SSH_HOST}" "${TARGET_SSH_PORT}" "${TARGET_SSH_USER}" "${TARGET_SSH_PASS:-}" "${PKG_FILE}" "${REMOTE_PKG}" "${TARGET_APP_DIR}" "${APP_HEALTHCHECK_URL}" "${BACKEND_CHANGED}" "${FRONTEND_CHANGED}" "${INSTALL_BACKEND_DEPS}" "${INSTALL_FRONTEND_DEPS}" "${SYNC_DOC}" "${DOC_PATH}"
import os
import sys
import paramiko

(
    host,
    port,
    user,
    password,
    local_pkg,
    remote_pkg,
    target_app_dir,
    health_url,
    backend_changed,
    frontend_changed,
    install_backend_deps,
    install_frontend_deps,
    sync_doc,
    doc_path,
) = sys.argv[1:]

port = int(port)
backend_changed = int(backend_changed)
frontend_changed = int(frontend_changed)
install_backend_deps = int(install_backend_deps)
install_frontend_deps = int(install_frontend_deps)
sync_doc = int(sync_doc)

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
kwargs = dict(hostname=host, port=port, username=user, timeout=30)
if password:
    kwargs["password"] = password
client.connect(**kwargs)

sftp = client.open_sftp()
sftp.put(local_pkg, remote_pkg)
if sync_doc and os.path.exists(doc_path):
    remote_doc = "/www/wwwroot/咨询话术模拟训练系统-项目开发文档.md"
    sftp.put(doc_path, remote_doc)
sftp.close()

cmd = f"""set -e
mkdir -p "{target_app_dir}"
tar -xzf "{remote_pkg}" -C "{target_app_dir}"
rm -f "{remote_pkg}"
if [[ "{backend_changed}" == "1" ]]; then
  cd "{target_app_dir}/backend"
  if [[ "{install_backend_deps}" == "1" ]]; then
    ./venv/bin/pip install -r requirements.txt
  fi
  ./venv/bin/alembic upgrade head
  systemctl restart chattrainer-backend
fi
if [[ "{frontend_changed}" == "1" ]]; then
  cd "{target_app_dir}/frontend"
  if [[ "{install_frontend_deps}" == "1" ]]; then
    npm install
  fi
  npm run build
  systemctl reload nginx
fi
curl -fsS "{health_url}"
"""

stdin, stdout, stderr = client.exec_command(cmd)
out = stdout.read().decode("utf-8", "ignore")
err = stderr.read().decode("utf-8", "ignore")
print(out, end="")
if err:
    print(err, end="", file=sys.stderr)

code = stdout.channel.recv_exit_status()
client.close()
if code != 0:
    raise SystemExit(code)
PY

echo "[4/6] 已同步文件列表："
if [[ -s "${LIST_FILE}" ]]; then
  sed 's/^/ - /' "${LIST_FILE}"
else
  echo " - (无代码文件，可能仅同步了文档)"
fi

echo "[5/6] 后端变更: ${BACKEND_CHANGED}，前端变更: ${FRONTEND_CHANGED}"
echo "[6/6] 完成。"

