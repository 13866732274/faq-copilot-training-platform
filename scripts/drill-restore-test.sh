#!/usr/bin/env bash
set -euo pipefail

# 一键恢复演练（测试库）
# 目标：
# 1) 从备份恢复到测试库
# 2) 进行最小验收检查
# 3) 输出演练报告到 backups/drill-reports/
# 4) 硬拦截：禁止连接生产库

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROD_ENV_FILE="${PROD_ENV_FILE:-${PROJECT_ROOT}/backend/.env}"
TEST_ENV_FILE="${TEST_ENV_FILE:-${PROJECT_ROOT}/backend/.env.test}"
BACKUP_DIR="${BACKUP_DIR:-${PROJECT_ROOT}/backups/mysql}"
REPORT_DIR="${REPORT_DIR:-${PROJECT_ROOT}/backups/drill-reports}"

usage() {
  cat <<'EOF'
用法:
  bash scripts/drill-restore-test.sh [--file /path/to/backup.sql.gz] [--dry-run] [--yes]

参数:
  --file     指定备份文件（.sql 或 .sql.gz）；不传则自动选 backups/mysql 最新文件
  --dry-run  仅检查环境与风险，不执行恢复
  --yes      跳过交互确认

配置来源（优先级）:
  1) 环境变量 DRILL_DATABASE_URL
  2) backend/.env.test 中的 DATABASE_URL

生产库来源:
  backend/.env 的 DATABASE_URL
EOF
}

BACKUP_FILE=""
DRY_RUN="0"
AUTO_YES="0"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --file)
      BACKUP_FILE="${2:-}"
      shift 2
      ;;
    --dry-run)
      DRY_RUN="1"
      shift
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

if ! command -v mysql >/dev/null 2>&1; then
  echo "错误: 未安装 mysql 客户端" >&2
  exit 1
fi

if [[ ! -f "${PROD_ENV_FILE}" ]]; then
  echo "错误: 未找到生产环境文件 ${PROD_ENV_FILE}" >&2
  exit 1
fi

if [[ -z "${BACKUP_FILE}" ]]; then
  if [[ ! -d "${BACKUP_DIR}" ]]; then
    echo "错误: 备份目录不存在 ${BACKUP_DIR}" >&2
    exit 1
  fi
  BACKUP_FILE="$(ls -t "${BACKUP_DIR}"/*.sql.gz "${BACKUP_DIR}"/*.sql 2>/dev/null | head -n 1 || true)"
fi

if [[ -z "${BACKUP_FILE}" || ! -f "${BACKUP_FILE}" ]]; then
  echo "错误: 未找到可用备份文件，请使用 --file 指定" >&2
  exit 1
fi

if [[ "${BACKUP_FILE}" != *.sql && "${BACKUP_FILE}" != *.sql.gz ]]; then
  echo "错误: 仅支持 .sql 或 .sql.gz 文件" >&2
  exit 1
fi

get_env_value() {
  local env_file="$1"
  local key="$2"
  while IFS= read -r line || [[ -n "${line}" ]]; do
    [[ -z "${line}" || "${line}" =~ ^[[:space:]]*# ]] && continue
    if [[ "${line}" == "${key}"=* ]]; then
      echo "${line#*=}"
      return 0
    fi
  done <"${env_file}"
  return 1
}

parse_db_url() {
  python3 - <<'PY' "$1"
import sys
from urllib.parse import urlparse, unquote

url = sys.argv[1]
p = urlparse(url)
db = (p.path or "").lstrip("/")
print(unquote(p.scheme or ""))
print(unquote(p.hostname or "127.0.0.1"))
print(str(p.port or 3306))
print(unquote(p.username or "root"))
print(unquote(p.password or ""))
print(unquote(db))
PY
}

PROD_DATABASE_URL="$(get_env_value "${PROD_ENV_FILE}" "DATABASE_URL" || true)"
if [[ -z "${PROD_DATABASE_URL}" ]]; then
  echo "错误: ${PROD_ENV_FILE} 未配置 DATABASE_URL" >&2
  exit 1
fi

if [[ -n "${DRILL_DATABASE_URL:-}" ]]; then
  TEST_DATABASE_URL="${DRILL_DATABASE_URL}"
elif [[ -f "${TEST_ENV_FILE}" ]]; then
  TEST_DATABASE_URL="$(get_env_value "${TEST_ENV_FILE}" "DATABASE_URL" || true)"
else
  TEST_DATABASE_URL=""
fi

if [[ -z "${TEST_DATABASE_URL}" ]]; then
  echo "错误: 未找到测试库连接串。请设置 DRILL_DATABASE_URL 或创建 ${TEST_ENV_FILE}" >&2
  exit 1
fi

readarray -t PROD_PARTS < <(parse_db_url "${PROD_DATABASE_URL}")
readarray -t TEST_PARTS < <(parse_db_url "${TEST_DATABASE_URL}")

PROD_HOST="${PROD_PARTS[1]}"
PROD_PORT="${PROD_PARTS[2]}"
PROD_USER="${PROD_PARTS[3]}"
PROD_DB="${PROD_PARTS[5]}"

TEST_HOST="${TEST_PARTS[1]}"
TEST_PORT="${TEST_PARTS[2]}"
TEST_USER="${TEST_PARTS[3]}"
TEST_PASS="${TEST_PARTS[4]}"
TEST_DB="${TEST_PARTS[5]}"

if [[ -z "${TEST_DB}" ]]; then
  echo "错误: 测试库名为空" >&2
  exit 1
fi

# ===== 生产库硬拦截 =====
# 规则1：测试库名不得与生产库名相同
if [[ "${TEST_DB}" == "${PROD_DB}" ]]; then
  echo "硬拦截: 测试库名与生产库名相同 (${TEST_DB})，禁止执行恢复" >&2
  exit 1
fi

# 规则2：测试库名必须包含非生产标识，避免误填
if [[ ! "${TEST_DB}" =~ (test|drill|staging|sandbox) ]]; then
  echo "硬拦截: 测试库名必须包含 test/drill/staging/sandbox 关键字，当前=${TEST_DB}" >&2
  exit 1
fi

# 规则3：完全相同连接（host/port/user/db）直接拦截
if [[ "${TEST_HOST}" == "${PROD_HOST}" && "${TEST_PORT}" == "${PROD_PORT}" && "${TEST_USER}" == "${PROD_USER}" ]]; then
  if [[ "${TEST_DB}" == "${PROD_DB}" ]]; then
    echo "硬拦截: 测试连接与生产连接一致，禁止执行" >&2
    exit 1
  fi
fi

mkdir -p "${REPORT_DIR}"
START_TS="$(date +%s)"
RUN_STAMP="$(date +%Y%m%d_%H%M%S)"
REPORT_FILE="${REPORT_DIR}/drill_${RUN_STAMP}.md"

echo "====== 恢复演练信息 ======"
echo "备份文件: ${BACKUP_FILE}"
echo "目标测试库: ${TEST_HOST}:${TEST_PORT}/${TEST_DB}"
echo "报告文件: ${REPORT_FILE}"
echo "========================="

if [[ "${DRY_RUN}" == "1" ]]; then
  cat >"${REPORT_FILE}" <<EOF
# 恢复演练报告（仅检查）

- 执行时间: $(date '+%Y-%m-%d %H:%M:%S')
- 模式: dry-run（未执行恢复）
- 备份文件: \`${BACKUP_FILE}\`
- 目标测试库: \`${TEST_HOST}:${TEST_PORT}/${TEST_DB}\`
- 风险拦截: 通过
- 结论: 可执行正式演练
EOF
  echo "dry-run 完成: ${REPORT_FILE}"
  exit 0
fi

if [[ "${AUTO_YES}" != "1" ]]; then
  echo "警告: 即将向测试库执行恢复，不会触碰生产库。"
  read -r -p "请输入 YES 确认执行: " CONFIRM
  if [[ "${CONFIRM}" != "YES" ]]; then
    echo "已取消执行"
    exit 0
  fi
fi

# 确保测试库存在
MYSQL_PWD="${TEST_PASS}" mysql -h "${TEST_HOST}" -P "${TEST_PORT}" -u "${TEST_USER}" \
  -e "CREATE DATABASE IF NOT EXISTS \`${TEST_DB}\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"

# 导入备份
if [[ "${BACKUP_FILE}" == *.sql.gz ]]; then
  gunzip -c "${BACKUP_FILE}" | MYSQL_PWD="${TEST_PASS}" mysql -h "${TEST_HOST}" -P "${TEST_PORT}" -u "${TEST_USER}" "${TEST_DB}"
else
  MYSQL_PWD="${TEST_PASS}" mysql -h "${TEST_HOST}" -P "${TEST_PORT}" -u "${TEST_USER}" "${TEST_DB}" < "${BACKUP_FILE}"
fi

# 最小验收检查
check_count() {
  local table="$1"
  MYSQL_PWD="${TEST_PASS}" mysql -N -s -h "${TEST_HOST}" -P "${TEST_PORT}" -u "${TEST_USER}" "${TEST_DB}" -e "SELECT COUNT(*) FROM \`${table}\`;"
}

USERS_COUNT="$(check_count "users" || echo "ERR")"
HOSPITALS_COUNT="$(check_count "hospitals" || echo "ERR")"
QUIZZES_COUNT="$(check_count "quizzes" || echo "ERR")"
MESSAGES_COUNT="$(check_count "messages" || echo "ERR")"
PRACTICES_COUNT="$(check_count "practices" || echo "ERR")"
AUDIT_LOGS_COUNT="$(check_count "audit_logs" || echo "ERR")"

END_TS="$(date +%s)"
DURATION="$((END_TS - START_TS))"

STATUS="成功"
if [[ "${USERS_COUNT}" == "ERR" || "${HOSPITALS_COUNT}" == "ERR" || "${QUIZZES_COUNT}" == "ERR" || "${MESSAGES_COUNT}" == "ERR" || "${PRACTICES_COUNT}" == "ERR" ]]; then
  STATUS="失败"
fi

cat >"${REPORT_FILE}" <<EOF
# 恢复演练报告

- 执行时间: $(date '+%Y-%m-%d %H:%M:%S')
- 执行状态: ${STATUS}
- 备份文件: \`${BACKUP_FILE}\`
- 目标测试库: \`${TEST_HOST}:${TEST_PORT}/${TEST_DB}\`
- 耗时: ${DURATION} 秒

## 风险拦截

- 生产库名: \`${PROD_DB}\`
- 测试库名: \`${TEST_DB}\`
- 硬拦截校验: 通过

## 最小验收结果

| 检查项 | 结果 |
|---|---:|
| users 行数 | ${USERS_COUNT} |
| hospitals 行数 | ${HOSPITALS_COUNT} |
| quizzes 行数 | ${QUIZZES_COUNT} |
| messages 行数 | ${MESSAGES_COUNT} |
| practices 行数 | ${PRACTICES_COUNT} |
| audit_logs 行数 | ${AUDIT_LOGS_COUNT} |

## 结论

$( [[ "${STATUS}" == "成功" ]] && echo "演练通过，可用于月度恢复验收。" || echo "演练失败，请检查数据库连接、备份文件完整性或 SQL 执行报错。" )
EOF

echo "恢复演练完成，报告已生成: ${REPORT_FILE}"
