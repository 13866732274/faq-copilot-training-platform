from __future__ import annotations

from types import SimpleNamespace

from app.services.rbac import evaluate_rbac_decision


def _actor(role: str, tenant_id: int | None, is_all_hospitals: bool = False):
    return SimpleNamespace(role=role, tenant_id=tenant_id, is_all_hospitals=is_all_hospitals)


def test_super_admin_can_cross_tenant_scope() -> None:
    decision = evaluate_rbac_decision(
        actor=_actor("super_admin", 1),
        action="user:update",
        required_roles={"admin", "super_admin"},
        target_tenant_id=2,
        target_hospital_id=99,
        target_department_id=77,
        accessible_hospital_ids=[],
        accessible_department_ids=[],
    )
    assert decision.allowed is True
    assert decision.role_ok is True
    assert decision.tenant_ok is True
    assert decision.scope_ok is True


def test_admin_denied_when_cross_tenant() -> None:
    decision = evaluate_rbac_decision(
        actor=_actor("admin", 1),
        action="user:update",
        required_roles={"admin", "super_admin"},
        target_tenant_id=2,
        target_hospital_id=1,
        target_department_id=1,
        accessible_hospital_ids=[1, 2],
        accessible_department_ids=[1, 3],
    )
    assert decision.allowed is False
    assert decision.tenant_ok is False
    assert decision.reason == "超出租户范围"


def test_admin_denied_when_out_of_scope() -> None:
    decision = evaluate_rbac_decision(
        actor=_actor("admin", 1, is_all_hospitals=False),
        action="department:list",
        required_roles={"admin", "super_admin"},
        target_tenant_id=1,
        target_hospital_id=8,
        target_department_id=18,
        accessible_hospital_ids=[2, 3],
        accessible_department_ids=[11, 12],
    )
    assert decision.allowed is False
    assert decision.tenant_ok is True
    assert decision.scope_ok is False
    assert decision.reason == "超出医院/科室数据范围"
