#!/usr/bin/env bash
set -euo pipefail

# 一键一致性巡检（只读，不改数据）
# 目标：
# 1) 检查医院-科室-用户-题库-练习-审计的关键绑定一致性
# 2) 输出中文报告，便于每次升级后快速验收

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
BACKEND_DIR="${PROJECT_ROOT}/backend"
REPORT_DIR="${REPORT_DIR:-${PROJECT_ROOT}/backups/consistency-reports}"

if [[ ! -d "${BACKEND_DIR}" ]]; then
  echo "错误: 未找到 backend 目录: ${BACKEND_DIR}" >&2
  exit 1
fi

if [[ ! -x "${BACKEND_DIR}/venv/bin/python" ]]; then
  echo "错误: 未找到 Python 虚拟环境解释器: ${BACKEND_DIR}/venv/bin/python" >&2
  exit 1
fi

mkdir -p "${REPORT_DIR}"
STAMP="$(date +%Y%m%d_%H%M%S)"
REPORT_FILE="${REPORT_DIR}/consistency_${STAMP}.md"

echo "开始巡检（只读）..."

JSON_OUT="$("${BACKEND_DIR}/venv/bin/python" - <<'PY' "${BACKEND_DIR}"
import asyncio
import json
import os
import sys

backend_dir = sys.argv[1]
sys.path.insert(0, backend_dir)
os.chdir(backend_dir)

from sqlalchemy import text  # noqa: E402
from app.database import SessionLocal  # noqa: E402

CHECKS = [
    ("users_missing_dept_with_hospital", "用户有医院但无科室", """
        SELECT COUNT(*) c
        FROM users
        WHERE hospital_id IS NOT NULL AND department_id IS NULL
    """),
    ("users_admin_student_missing_dept", "启用中的学员/管理员未绑定科室", """
        SELECT COUNT(*) c
        FROM users
        WHERE role IN ('admin','student') AND is_active=1 AND department_id IS NULL
    """),
    ("quizzes_hospital_scope_missing_dept", "题库(医院/科室范围)缺少科室绑定", """
        SELECT COUNT(*) c
        FROM quizzes
        WHERE is_deleted=0 AND scope IN ('hospital','department')
          AND hospital_id IS NOT NULL AND department_id IS NULL
    """),
    ("practices_missing_dept_with_hospital", "练习有医院但无科室", """
        SELECT COUNT(*) c
        FROM practices
        WHERE hospital_id IS NOT NULL AND department_id IS NULL
    """),
    ("audit_logs_missing_dept_with_hospital", "审计日志有医院但无科室", """
        SELECT COUNT(*) c
        FROM audit_logs
        WHERE hospital_id IS NOT NULL AND department_id IS NULL
    """),
    ("user_dept_links_missing_for_primary", "用户主科室缺少 user_departments 关联", """
        SELECT COUNT(*) c
        FROM users u
        WHERE u.department_id IS NOT NULL
          AND NOT EXISTS (
            SELECT 1
            FROM user_departments ud
            WHERE ud.user_id=u.id AND ud.department_id=u.department_id
          )
    """),
    ("departments_per_hospital_zero", "存在未配置任何科室的医院", """
        SELECT COUNT(*) c
        FROM hospitals h
        WHERE NOT EXISTS (
            SELECT 1 FROM departments d WHERE d.hospital_id=h.id
        )
    """),
    ("orphan_user_departments", "user_departments 存在孤儿引用", """
        SELECT COUNT(*) c
        FROM user_departments ud
        LEFT JOIN users u ON u.id = ud.user_id
        LEFT JOIN departments d ON d.id = ud.department_id
        WHERE u.id IS NULL OR d.id IS NULL
    """),
]

SUMMARY_SQL = {
    "医院数": "SELECT COUNT(*) FROM hospitals",
    "科室数": "SELECT COUNT(*) FROM departments",
    "用户数": "SELECT COUNT(*) FROM users",
    "题库数": "SELECT COUNT(*) FROM quizzes WHERE is_deleted=0",
    "练习数": "SELECT COUNT(*) FROM practices",
    "审计日志数": "SELECT COUNT(*) FROM audit_logs",
}

async def main():
    result = {"checks": [], "summary": {}}
    async with SessionLocal() as db:
        for key, title, sql in CHECKS:
            c = int((await db.execute(text(sql))).scalar_one())
            result["checks"].append({
                "key": key,
                "title": title,
                "count": c,
                "ok": c == 0,
            })
        for name, sql in SUMMARY_SQL.items():
            result["summary"][name] = int((await db.execute(text(sql))).scalar_one())
    print(json.dumps(result, ensure_ascii=False))

asyncio.run(main())
PY
)"

echo "${JSON_OUT}" > "/tmp/ct_consistency_${STAMP}.json"

"${BACKEND_DIR}/venv/bin/python" - <<'PY' "/tmp/ct_consistency_${STAMP}.json" "${REPORT_FILE}"
import json
import sys
from datetime import datetime
from pathlib import Path

data = json.loads(Path(sys.argv[1]).read_text())
report_file = Path(sys.argv[2])

checks = data["checks"]
summary = data["summary"]
all_ok = all(i["ok"] for i in checks)

lines = []
lines.append("# 一键一致性巡检报告")
lines.append("")
lines.append(f"- 执行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
lines.append("- 模式: 只读巡检（不改数据）")
lines.append(f"- 总体结论: {'通过 ✅' if all_ok else '未通过 ❌'}")
lines.append("")
lines.append("## 数据规模概览")
lines.append("")
for k, v in summary.items():
    lines.append(f"- {k}: {v}")
lines.append("")
lines.append("## 关键一致性检查")
lines.append("")
lines.append("| 检查项 | 异常数 | 结果 |")
lines.append("|---|---:|---|")
for item in checks:
    lines.append(f"| {item['title']} | {item['count']} | {'通过' if item['ok'] else '异常'} |")
lines.append("")
if all_ok:
    lines.append("## 建议")
    lines.append("")
    lines.append("- 当前无需执行全量重绑，可按现有流程继续迭代。")
    lines.append("- 建议每次升级后执行一次本脚本并归档报告。")
else:
    lines.append("## 建议")
    lines.append("")
    lines.append("- 请先处理异常项，再进行业务验收。")
    lines.append("- 如需批量修复，建议先执行数据库备份。")

report_file.write_text("\n".join(lines), encoding="utf-8")
PY

echo "巡检完成，报告: ${REPORT_FILE}"

# 使用解析结果判断退出码（0=通过，2=存在异常）
ALL_OK="$("${BACKEND_DIR}/venv/bin/python" - <<'PY' "/tmp/ct_consistency_${STAMP}.json"
import json, sys
obj=json.loads(open(sys.argv[1], encoding='utf-8').read())
print("1" if all(i["ok"] for i in obj["checks"]) else "0")
PY
)"

if [[ "${ALL_OK}" == "1" ]]; then
  echo "结果: 全部检查通过 ✅"
  exit 0
fi

echo "结果: 存在异常项 ❌（详见报告）" >&2
exit 2
