#!/usr/bin/env bash
set -euo pipefail

# 全仓中文巡检（只扫描不改）
# 目标：
# 1) 扫描前端 UI 可见文案中可能残留的英文
# 2) 输出中文报告，便于按清单逐项清零

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
TARGET_DIR="${TARGET_DIR:-${PROJECT_ROOT}/frontend/src}"
REPORT_DIR="${REPORT_DIR:-${PROJECT_ROOT}/backups/i18n-reports}"

if [[ ! -d "${TARGET_DIR}" ]]; then
  echo "错误: 未找到扫描目录: ${TARGET_DIR}" >&2
  exit 1
fi

mkdir -p "${REPORT_DIR}"
STAMP="$(date +%Y%m%d_%H%M%S)"
REPORT_FILE="${REPORT_DIR}/zh_ui_scan_${STAMP}.md"
TMP_JSON="/tmp/ct_zh_ui_scan_${STAMP}.json"

echo "开始执行全仓中文巡检（只扫描不改）..."

python3 - <<'PY' "${TARGET_DIR}" "${TMP_JSON}"
import json
import re
import sys
from pathlib import Path

target_dir = Path(sys.argv[1])
out_json = Path(sys.argv[2])

file_patterns = ("*.vue", "*.ts")
exclude_dirs = {"node_modules", "dist", ".git", "coverage"}

# 只关注“可能显示给用户”的位置，降低误报
rules = [
    ("消息提示", re.compile(r"ElMessage\.(?:success|warning|error|info)\(\s*(['\"])(.*?)\1")),
    ("确认弹窗", re.compile(r"ElMessageBox\.(?:confirm|alert|prompt)\(\s*(['\"])(.*?)\1")),
    ("输入占位", re.compile(r'placeholder\s*=\s*"([^"]*[A-Za-z][^"]*)"')),
    ("标签标题", re.compile(r'(?:label|title|description)\s*=\s*"([^"]*[A-Za-z][^"]*)"')),
    ("模板文本", re.compile(r">\s*([^<>\n]*[A-Za-z][^<>\n]*)\s*<")),
]

ignore_terms = {
    "api", "id", "ip", "url", "http", "https", "json", "sql", "jwt", "token", "vite", "vue", "typescript",
    "element", "plus", "pc", "saas", "crud", "md", "html", "css", "js", "ts", "uuid",
    "active", "passive", "common", "hospital", "department", "student", "admin", "super_admin",
    "append", "replace", "all", "dark", "light", "ctrl", "enter",
}

def contains_chinese(text: str) -> bool:
    return re.search(r"[\u4e00-\u9fff]", text) is not None

def should_ignore(text: str) -> bool:
    lower = text.strip().lower()
    if not lower:
        return True
    if len(lower) <= 2:  # 如 "ID"、"IP"
        return True
    if "{{" in lower or "}}" in lower:
        return True
    if re.search(r"[=(){}$]", lower):
        return True
    if lower.startswith(":") or lower.startswith("@"):
        return True
    if re.search(r"\b[a-z_]+\.[a-z_]+\b", lower):
        return True
    if lower in ignore_terms:
        return True
    if re.fullmatch(r"[a-z0-9_./:#\-\s]+", lower) and len(lower.split()) <= 2:
        # 大概率是技术字面量
        return True
    return False

results: list[dict] = []

paths = []
for pattern in file_patterns:
    paths.extend(target_dir.rglob(pattern))

for path in sorted(set(paths)):
    if any(part in exclude_dirs for part in path.parts):
        continue
    try:
        content = path.read_text(encoding="utf-8")
    except Exception:
        continue
    lines = content.splitlines()
    file_hits = []
    for idx, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        for rule_name, pattern in rules:
            for m in pattern.finditer(line):
                text = (m.group(2) if m.lastindex and m.lastindex >= 2 else m.group(1)).strip()
                if not text:
                    continue
                if contains_chinese(text):
                    continue
                if should_ignore(text):
                    continue
                file_hits.append(
                    {
                        "line": idx,
                        "rule": rule_name,
                        "text": text[:200],
                    }
                )
    if file_hits:
        results.append({"file": str(path), "hits": file_hits})

summary = {
    "total_files_scanned": len(set(paths)),
    "files_with_findings": len(results),
    "total_findings": sum(len(i["hits"]) for i in results),
    "items": results,
}
out_json.write_text(json.dumps(summary, ensure_ascii=False), encoding="utf-8")
print(json.dumps(summary, ensure_ascii=False))
PY

python3 - <<'PY' "${TMP_JSON}" "${REPORT_FILE}"
import json
import sys
from datetime import datetime
from pathlib import Path

obj = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
report_file = Path(sys.argv[2])

lines = []
lines.append("# 全仓中文巡检报告（前端 UI 文案）")
lines.append("")
lines.append(f"- 执行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
lines.append("- 模式: 只扫描不改")
lines.append(f"- 扫描文件数: {obj['total_files_scanned']}")
lines.append(f"- 命中文件数: {obj['files_with_findings']}")
lines.append(f"- 疑似英文残留数: {obj['total_findings']}")
lines.append("")

if obj["total_findings"] == 0:
    lines.append("## 结论")
    lines.append("")
    lines.append("当前规则下未发现疑似英文 UI 文案残留 ✅")
else:
    lines.append("## 疑似英文残留清单")
    lines.append("")
    for item in obj["items"]:
        rel = item["file"]
        lines.append(f"### {rel}")
        lines.append("")
        lines.append("| 行号 | 类型 | 文案片段 |")
        lines.append("|---:|---|---|")
        for hit in item["hits"]:
            text = hit["text"].replace("|", "\\|")
            lines.append(f"| {hit['line']} | {hit['rule']} | `{text}` |")
        lines.append("")
    lines.append("## 建议")
    lines.append("")
    lines.append("- 先修复高频页面（登录、管理端列表、弹窗提示）。")
    lines.append("- 修复后重新执行本脚本，直到命中为 0。")

report_file.write_text("\n".join(lines), encoding="utf-8")
PY

echo "巡检完成，报告: ${REPORT_FILE}"

FINDINGS_COUNT="$(python3 - <<'PY' "${TMP_JSON}"
import json, sys
obj = json.loads(open(sys.argv[1], encoding="utf-8").read())
print(obj["total_findings"])
PY
)"

if [[ "${FINDINGS_COUNT}" == "0" ]]; then
  echo "结果: 未发现疑似英文残留 ✅"
  exit 0
fi

echo "结果: 发现疑似英文残留 ${FINDINGS_COUNT} 项（详见报告）" >&2
exit 2
