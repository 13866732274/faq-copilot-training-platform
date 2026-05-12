from __future__ import annotations

import time

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import SessionLocal
from app.main import app
from app.models import Tenant, User
from app.utils.security import hash_password


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def _seed_two_tenants(db: AsyncSession, suffix: str) -> dict[str, str]:
    tenant_a = Tenant(code=f"graybox-a-{suffix}", name=f"灰盒租户A-{suffix}", is_active=True)
    tenant_b = Tenant(code=f"graybox-b-{suffix}", name=f"灰盒租户B-{suffix}", is_active=True)
    db.add(tenant_a)
    db.add(tenant_b)
    await db.flush()

    password = "Test@123456"
    user_a = User(
        username=f"graybox_a_{suffix}",
        password_hash=hash_password(password),
        real_name=f"租户A管理员{suffix}",
        role="super_admin",
        tenant_id=tenant_a.id,
        is_all_hospitals=True,
        is_active=True,
    )
    user_b = User(
        username=f"graybox_b_{suffix}",
        password_hash=hash_password(password),
        real_name=f"租户B管理员{suffix}",
        role="super_admin",
        tenant_id=tenant_b.id,
        is_all_hospitals=True,
        is_active=True,
    )
    db.add(user_a)
    db.add(user_b)
    await db.commit()
    return {
        "username_a": user_a.username,
        "username_b": user_b.username,
        "password": password,
    }


async def _login(client: AsyncClient, username: str, password: str) -> dict:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("code") == 200
    return body["data"]


@pytest.mark.anyio
async def test_cross_tenant_graybox_acceptance() -> None:
    suffix = str(int(time.time() * 1000))
    async with SessionLocal() as db:
        seeded = await _seed_two_tenants(db, suffix)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        login_a = await _login(client, seeded["username_a"], seeded["password"])
        token_a = login_a["access_token"]

        login_b = await _login(client, seeded["username_b"], seeded["password"])
        token_b = login_b["access_token"]

        headers_a = {"Authorization": f"Bearer {token_a}"}
        headers_b = {"Authorization": f"Bearer {token_b}"}

        create_hospital = await client.post(
            "/api/v1/hospitals",
            json={"name": f"灰盒医院A-{suffix}", "code": f"hb-a-{suffix}"},
            headers=headers_a,
        )
        assert create_hospital.status_code == 200, create_hospital.text
        hospital_id = int(create_hospital.json()["data"]["id"])

        list_b = await client.get("/api/v1/hospitals", headers=headers_b)
        assert list_b.status_code == 200, list_b.text
        ids_b = [int(item["id"]) for item in (list_b.json().get("data") or [])]
        assert hospital_id not in ids_b

        update_b = await client.put(
            f"/api/v1/hospitals/{hospital_id}",
            json={"name": f"非法修改-{suffix}"},
            headers=headers_b,
        )
        assert update_b.status_code == 404, update_b.text

        create_task = await client.post(
            "/api/v1/import-tasks",
            json={
                "scope": "hospital",
                "hospital_id": hospital_id,
                "department_id": None,
                "total": 1,
                "detail": {"from": "graybox"},
            },
            headers=headers_a,
        )
        assert create_task.status_code == 200, create_task.text
        task_id = int(create_task.json()["data"]["id"])

        task_detail_b = await client.get(f"/api/v1/import-tasks/{task_id}", headers=headers_b)
        assert task_detail_b.status_code == 404, task_detail_b.text

        list_task_b = await client.get("/api/v1/import-tasks", headers=headers_b)
        assert list_task_b.status_code == 200, list_task_b.text
        task_ids_b = [int(item["id"]) for item in list_task_b.json()["data"]["items"]]
        assert task_id not in task_ids_b
        unique_site_name = f"灰盒租户A站点-{suffix}"
        update_a = await client.put(
            "/api/v1/system/settings",
            json={
                "site_name": unique_site_name,
                "site_subtitle": "灰盒测试副标题",
                "logo_url": None,
                "brand_accent": "#07c160",
                "enable_ai_scoring": False,
                "enable_export_center": True,
                "enable_audit_enhanced": True,
            },
            headers=headers_a,
        )
        assert update_a.status_code == 200, update_a.text

        get_a = await client.get("/api/v1/system/settings", headers=headers_a)
        assert get_a.status_code == 200, get_a.text
        assert get_a.json()["data"]["site_name"] == unique_site_name

        get_b = await client.get("/api/v1/system/settings", headers=headers_b)
        assert get_b.status_code == 200, get_b.text
        assert get_b.json()["data"]["site_name"] != unique_site_name

        user_id_a = int(login_a["user"]["id"])
        audit_a = await client.get(
            "/api/v1/audit-logs",
            params={"action": "system_settings_update", "user_id": user_id_a},
            headers=headers_a,
        )
        assert audit_a.status_code == 200, audit_a.text
        assert int(audit_a.json()["data"]["total"]) >= 1

        audit_b = await client.get(
            "/api/v1/audit-logs",
            params={"action": "system_settings_update", "user_id": user_id_a},
            headers=headers_b,
        )
        assert audit_b.status_code == 200, audit_b.text
        assert int(audit_b.json()["data"]["total"]) == 0


@pytest.mark.anyio
async def test_rbac_deny_audit_graybox() -> None:
    suffix = str(int(time.time() * 1000))
    async with SessionLocal() as db:
        seeded = await _seed_two_tenants(db, suffix)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        login_a = await _login(client, seeded["username_a"], seeded["password"])
        token_a = login_a["access_token"]
        headers_super = {"Authorization": f"Bearer {token_a}"}

        # Build two hospitals and departments in the same tenant.
        hosp_a = await client.post(
            "/api/v1/hospitals",
            json={"name": f"RBAC医院A-{suffix}", "code": f"rbac-ha-{suffix}"},
            headers=headers_super,
        )
        assert hosp_a.status_code == 200, hosp_a.text
        hosp_a_id = int(hosp_a.json()["data"]["id"])

        hosp_b = await client.post(
            "/api/v1/hospitals",
            json={"name": f"RBAC医院B-{suffix}", "code": f"rbac-hb-{suffix}"},
            headers=headers_super,
        )
        assert hosp_b.status_code == 200, hosp_b.text
        hosp_b_id = int(hosp_b.json()["data"]["id"])

        dep_a = await client.post(
            "/api/v1/departments",
            json={"hospital_id": hosp_a_id, "name": f"RBAC科室A-{suffix}", "code": f"rbac-da-{suffix}"},
            headers=headers_super,
        )
        assert dep_a.status_code == 200, dep_a.text
        dep_a_id = int(dep_a.json()["data"]["id"])

        dep_b = await client.post(
            "/api/v1/departments",
            json={"hospital_id": hosp_b_id, "name": f"RBAC科室B-{suffix}", "code": f"rbac-db-{suffix}"},
            headers=headers_super,
        )
        assert dep_b.status_code == 200, dep_b.text
        _ = int(dep_b.json()["data"]["id"])

        # Create a limited admin who only manages department A.
        admin_username = f"rbac_admin_{suffix}"
        create_admin = await client.post(
            "/api/v1/users",
            json={
                "username": admin_username,
                "password": "Test@123456",
                "real_name": "RBAC灰盒管理员",
                "role": "admin",
                "department_ids": [dep_a_id],
                "is_all_hospitals": False,
            },
            headers=headers_super,
        )
        assert create_admin.status_code == 200, create_admin.text
        admin_id = int(create_admin.json()["data"]["id"])

        login_admin = await _login(client, admin_username, "Test@123456")
        token_admin = login_admin["access_token"]
        headers_admin = {"Authorization": f"Bearer {token_admin}"}

        # Access out-of-scope hospital departments -> should be denied by enforce_rbac.
        deny_resp = await client.get(
            "/api/v1/departments",
            params={"hospital_id": hosp_b_id},
            headers=headers_admin,
        )
        assert deny_resp.status_code == 403, deny_resp.text
        assert "无权执行该操作" in (deny_resp.json().get("detail") or "")

        # Super admin can see the RBAC deny audit entry.
        audit_resp = await client.get(
            "/api/v1/audit-logs",
            params={"action": "rbac_deny", "user_id": admin_id},
            headers=headers_super,
        )
        assert audit_resp.status_code == 200, audit_resp.text
        items = audit_resp.json()["data"]["items"]
        assert len(items) >= 1
        action_names = [((item.get("detail") or {}).get("action")) for item in items]
        assert "department:list" in action_names
