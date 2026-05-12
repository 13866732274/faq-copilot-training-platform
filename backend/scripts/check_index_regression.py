from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import create_engine, text


def _load_database_url() -> str:
    env_file = Path(__file__).resolve().parents[1] / ".env"
    if not env_file.exists():
        raise RuntimeError(f"未找到环境文件: {env_file}")
    database_url = ""
    for line in env_file.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#"):
            continue
        if raw.startswith("DATABASE_URL="):
            database_url = raw.split("=", 1)[1].strip()
            break
    if not database_url:
        raise RuntimeError("未在 backend/.env 中找到 DATABASE_URL")
    return database_url


def _sync_url(async_url: str) -> str:
    return async_url.replace("mysql+asyncmy://", "mysql+pymysql://", 1)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _default_report_dir() -> Path:
    return _project_root() / "backups" / "index-check-reports"


def _mask_database_url(database_url: str) -> str:
    parsed = urlparse(database_url)
    username = parsed.username or ""
    password = "***" if parsed.password else ""
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 3306
    db = (parsed.path or "/").lstrip("/")
    auth = username
    if password:
        auth = f"{auth}:{password}"
    if auth:
        auth = f"{auth}@"
    return f"{parsed.scheme}://{auth}{host}:{port}/{db}"


def _pick_one(conn, sql: str, fallback):
    value = conn.execute(text(sql)).scalar()
    return value if value is not None else fallback


def _explain_key(conn, sql: str, params: dict) -> str:
    row = conn.execute(text(f"EXPLAIN {sql}"), params).mappings().first()
    if not row:
        return ""
    return str(row.get("key") or "")


def _render_report(
    *,
    step: str,
    masked_url: str,
    started_at: datetime,
    results: list[dict],
    failures: list[str],
    report_path: Path,
) -> None:
    total = len(results)
    passed = sum(1 for item in results if item["passed"])
    failed = total - passed
    lines: list[str] = []
    lines.append("# 索引灰度校验报告")
    lines.append("")
    lines.append(f"- 执行时间: {started_at.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"- 校验步骤: {step}")
    lines.append(f"- 数据库: `{masked_url}`")
    lines.append(f"- 结果: {'通过 ✅' if not failures else '失败 ❌'}")
    lines.append(f"- 统计: 总计 {total} / 通过 {passed} / 失败 {failed}")
    lines.append("")
    lines.append("## 逐项明细")
    lines.append("")
    lines.append("| 检查项 | 期望索引 | 实际 key | 结果 | SQL |")
    lines.append("|---|---|---|---|---|")
    for item in results:
        expected = ", ".join(sorted(item["expected_keys"]))
        status = "通过" if item["passed"] else "失败"
        sql_text = item["sql"].replace("|", "\\|")
        lines.append(f"| {item['name']} | `{expected}` | `{item['actual_key'] or 'NULL'}` | {status} | `{sql_text}` |")
    if failures:
        lines.append("")
        lines.append("## 失败原因")
        lines.append("")
        for fail in failures:
            lines.append(f"- {fail}")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")


def run_checks(step: str, report_dir: Path | None) -> int:
    db_url = _load_database_url()
    url = _sync_url(db_url)
    engine = create_engine(url, future=True)
    started_at = datetime.now()
    failures: list[str] = []
    results: list[dict] = []
    with engine.connect() as conn:
        user_id = _pick_one(conn, "SELECT user_id FROM practices WHERE user_id IS NOT NULL LIMIT 1", 1)
        hospital_id = _pick_one(
            conn, "SELECT hospital_id FROM practices WHERE hospital_id IS NOT NULL LIMIT 1", 1
        )
        action = _pick_one(conn, "SELECT action FROM audit_logs WHERE action IS NOT NULL LIMIT 1", "login")

        checks = []
        if step in {"practice_user", "all"}:
            checks.append(
                (
                    "practice_user",
                    "SELECT id FROM practices WHERE user_id=:user_id ORDER BY id DESC LIMIT 20",
                    {"user_id": user_id},
                    {"idx_practice_user_id"},
                )
            )
        if step in {"practice_hospital", "all"}:
            checks.append(
                (
                    "practice_hospital",
                    "SELECT COUNT(*) FROM practices WHERE hospital_id=:hospital_id",
                    {"hospital_id": hospital_id},
                    {"idx_practice_hospital_created_at"},
                )
            )
        if step in {"audit_action", "all"}:
            checks.append(
                (
                    "audit_action",
                    "SELECT id FROM audit_logs WHERE action=:action AND created_at>=DATE_SUB(NOW(), INTERVAL 30 DAY) ORDER BY id DESC LIMIT 20",
                    {"action": action},
                    {"idx_audit_logs_action_created_id"},
                )
            )

        print(f"开始校验 step={step} ...")
        for name, sql, params, expected_keys in checks:
            key = _explain_key(conn, sql, params)
            print(f"- {name}: key={key or '(NULL)'}")
            passed = key in expected_keys
            results.append(
                {
                    "name": name,
                    "sql": sql,
                    "params": params,
                    "expected_keys": expected_keys,
                    "actual_key": key,
                    "passed": passed,
                }
            )
            if key not in expected_keys:
                failures.append(f"{name} 期望索引 {sorted(expected_keys)}，实际 key={key or 'NULL'}")

    if report_dir is not None:
        stamp = started_at.strftime("%Y%m%d_%H%M%S")
        report_path = report_dir / f"index_check_{step}_{stamp}.md"
        _render_report(
            step=step,
            masked_url=_mask_database_url(db_url),
            started_at=started_at,
            results=results,
            failures=failures,
            report_path=report_path,
        )
        print(f"报告已写入: {report_path}")

    if failures:
        print("校验失败：")
        for item in failures:
            print(f"  - {item}")
        return 2
    print("校验通过 ✅")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="索引灰度下线回归校验")
    parser.add_argument(
        "--step",
        choices=["practice_user", "practice_hospital", "audit_action", "all"],
        default="all",
        help="指定要校验的步骤",
    )
    parser.add_argument(
        "--report-dir",
        default=str(_default_report_dir()),
        help="报告输出目录，默认写入 backups/index-check-reports/",
    )
    parser.add_argument(
        "--no-report",
        action="store_true",
        help="仅控制台输出，不写报告文件",
    )
    args = parser.parse_args()
    report_dir = None if args.no_report else Path(args.report_dir)
    raise SystemExit(run_checks(args.step, report_dir))


if __name__ == "__main__":
    main()
