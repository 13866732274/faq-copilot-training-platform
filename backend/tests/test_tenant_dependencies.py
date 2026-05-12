from __future__ import annotations

from fastapi import HTTPException

from app.dependencies import ensure_tenant_bound


class _UserStub:
    def __init__(self, tenant_id: int | None) -> None:
        self.tenant_id = tenant_id


def test_ensure_tenant_bound_returns_tenant_id() -> None:
    user = _UserStub(tenant_id=9)
    assert ensure_tenant_bound(user) == 9


def test_ensure_tenant_bound_raises_when_missing() -> None:
    user = _UserStub(tenant_id=None)
    try:
        ensure_tenant_bound(user)
    except HTTPException as exc:
        assert exc.status_code == 400
        assert "未绑定租户" in str(exc.detail)
    else:
        raise AssertionError("expected HTTPException")
