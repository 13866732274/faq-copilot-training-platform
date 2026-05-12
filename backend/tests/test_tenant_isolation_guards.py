from __future__ import annotations

from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (BACKEND_ROOT / path).read_text(encoding="utf-8")


def test_management_apis_have_tenant_guards() -> None:
    audit_code = _read("app/api/audit.py")
    system_code = _read("app/api/system.py")
    import_tasks_code = _read("app/api/import_tasks.py")

    assert "ensure_tenant_bound" in audit_code
    assert "AuditLog.tenant_id" in audit_code

    assert "ensure_tenant_bound" in system_code
    assert "tenant_id = ensure_tenant_bound(current_user)" in system_code
    assert "Quiz.tenant_id == tenant_id" in system_code
    assert "Practice.tenant_id == tenant_id" in system_code
    assert "User.tenant_id == tenant_id" in system_code

    assert "ensure_tenant_bound" in import_tasks_code
    assert "ImportTask.tenant_id == tenant_id" in import_tasks_code


def test_core_apis_have_tenant_guards() -> None:
    quizzes_code = _read("app/api/quizzes.py")
    practice_code = _read("app/api/practice.py")
    records_code = _read("app/api/records.py")
    stats_code = _read("app/api/stats.py")

    assert "Quiz.tenant_id == tenant_id" in quizzes_code
    assert "Message.tenant_id" in quizzes_code

    assert "Practice.tenant_id == tenant_id" in practice_code
    assert "tenant_id=tenant_id" in practice_code

    assert "Practice.tenant_id == tenant_id" in records_code
    assert "Quiz.tenant_id == tenant_id" in records_code

    assert "tenant_id = ensure_tenant_bound(current_user)" in stats_code
    assert "u.tenant_id=:tenant_id" in stats_code
    assert "q.tenant_id = :tenant_id" in stats_code
