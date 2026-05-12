from __future__ import annotations

import asyncio

from sqlalchemy import delete, select

from app.database import SessionLocal
from app.models import (
    AuditLog,
    Department,
    Hospital,
    ImportTask,
    Message,
    Practice,
    PracticeComment,
    PracticeReply,
    PreviewCache,
    Quiz,
    QuizVersion,
    SystemSetting,
    Tenant,
    User,
    UserDepartment,
    UserHospital,
)
from app.utils.security import hash_password


KEEP_USERNAMES = {"admin", "super_admin"}
DEFAULT_TENANT_CODE = "default"


async def main() -> None:
    async with SessionLocal() as db:
        default_tenant = (
            await db.execute(select(Tenant).where(Tenant.code == DEFAULT_TENANT_CODE))
        ).scalars().first()
        if not default_tenant:
            default_tenant = Tenant(code=DEFAULT_TENANT_CODE, name="默认租户", is_active=True, session_version=1)
            db.add(default_tenant)
            await db.flush()

        keep_users = (
            await db.execute(select(User).where(User.username.in_(sorted(KEEP_USERNAMES))))
        ).scalars().all()
        keep_user_ids = {int(u.id) for u in keep_users}

        # 清理业务数据（先清子表，后清主表）
        for model in (
            PracticeComment,
            PracticeReply,
            Practice,
            ImportTask,
            PreviewCache,
            QuizVersion,
            Quiz,
            Message,
            AuditLog,
        ):
            await db.execute(delete(model))

        # 清理组织与关联
        if keep_user_ids:
            await db.execute(delete(UserDepartment).where(UserDepartment.user_id.notin_(keep_user_ids)))
            await db.execute(delete(UserHospital).where(UserHospital.user_id.notin_(keep_user_ids)))
        else:
            await db.execute(delete(UserDepartment))
            await db.execute(delete(UserHospital))
        await db.execute(delete(Department))
        await db.execute(delete(Hospital))

        # 清理用户（仅保留 admin/super_admin）
        await db.execute(delete(User).where(User.username.notin_(sorted(KEEP_USERNAMES))))

        # 统一保留用户归属到默认租户
        remain_users = (await db.execute(select(User).where(User.username.in_(sorted(KEEP_USERNAMES))))).scalars().all()
        for u in remain_users:
            u.tenant_id = int(default_tenant.id)
            u.hospital_id = None
            u.department_id = None
            if u.username == "super_admin":
                u.role = "super_admin"
                u.is_all_hospitals = True
                u.is_active = True
                u.password_hash = hash_password("123456")
            elif u.username == "admin":
                u.is_active = True

        # 若不存在 super_admin，则创建
        super_admin = next((u for u in remain_users if u.username == "super_admin"), None)
        if not super_admin:
            db.add(
                User(
                    username="super_admin",
                    password_hash=hash_password("123456"),
                    real_name="平台超级管理员",
                    role="super_admin",
                    tenant_id=int(default_tenant.id),
                    is_all_hospitals=True,
                    is_active=True,
                    menu_permissions=None,
                )
            )

        # 清理非默认租户与其设置
        await db.execute(delete(SystemSetting).where(SystemSetting.tenant_id != int(default_tenant.id)))
        await db.execute(delete(Tenant).where(Tenant.id != int(default_tenant.id)))
        default_tenant.name = "默认租户"
        default_tenant.is_active = True
        default_tenant.session_version = 1

        # 兜底：清理保留用户的残余范围绑定
        await db.execute(delete(UserDepartment))
        await db.execute(delete(UserHospital))

        await db.commit()
        print("reset_done")


if __name__ == "__main__":
    asyncio.run(main())

