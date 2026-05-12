from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import select

from app.database import SessionLocal
from app.models import AuditLog, SystemSetting, Tenant, User
from app.utils.security import hash_password


def _prompt_if_empty(value: str | None, label: str, *, secret: bool = False) -> str:
    if value and str(value).strip():
        return str(value).strip()
    if secret:
        import getpass

        return getpass.getpass(f"{label}: ").strip()
    return input(f"{label}: ").strip()


async def bootstrap(
    *,
    tenant_code: str,
    tenant_name: str,
    username: str,
    password: str,
    real_name: str,
    operator: str,
    allow_existing: bool,
    reset_password: bool,
) -> None:
    async with SessionLocal() as db:
        code = tenant_code.strip().lower()
        name = tenant_name.strip()
        uname = username.strip()
        rname = real_name.strip()
        if not code or not name or not uname or not password or not rname:
            raise ValueError("租户编码/租户名称/用户名/密码/姓名都不能为空")
        if len(password) < 6:
            raise ValueError("密码长度不能少于6位")

        tenant = (await db.execute(select(Tenant).where(Tenant.code == code))).scalars().first()
        tenant_created = False
        if not tenant:
            tenant = Tenant(code=code, name=name, is_active=True, session_version=1)
            db.add(tenant)
            await db.flush()
            tenant_created = True
        else:
            if not allow_existing:
                raise ValueError("租户编码已存在，若要复用请加 --allow-existing")
            if not tenant.is_active:
                tenant.is_active = True
            if name and tenant.name != name:
                tenant.name = name

        # 每个租户一个“租户超级管理员”账号（role=super_admin, tenant_id=目标租户）
        user = (
            await db.execute(
                select(User).where(User.tenant_id == tenant.id, User.username == uname).limit(1)
            )
        ).scalars().first()

        user_created = False
        if not user:
            user = User(
                username=uname,
                password_hash=hash_password(password),
                real_name=rname,
                role="super_admin",
                tenant_id=tenant.id,
                is_all_hospitals=True,
                is_active=True,
                menu_permissions=None,
            )
            db.add(user)
            await db.flush()
            user_created = True
        else:
            if not allow_existing:
                raise ValueError("该租户下用户名已存在，若要复用请加 --allow-existing")
            user.real_name = rname
            user.role = "super_admin"
            user.tenant_id = tenant.id
            user.is_all_hospitals = True
            user.is_active = True
            user.menu_permissions = None
            if reset_password:
                user.password_hash = hash_password(password)

        # 初始化该租户系统设置
        settings = (
            await db.execute(select(SystemSetting).where(SystemSetting.tenant_id == tenant.id).limit(1))
        ).scalars().first()
        if not settings:
            db.add(
                SystemSetting(
                    tenant_id=tenant.id,
                    site_name="咨询话术模拟训练系统",
                    site_subtitle="运营管理中台",
                    brand_accent="#07c160",
                    enable_ai_scoring=False,
                    enable_export_center=True,
                    enable_audit_enhanced=True,
                    updated_by=None,
                )
            )

        db.add(
            AuditLog(
                tenant_id=tenant.id,
                user_id=None,
                action="tenant_bootstrap",
                target_type="tenant",
                target_id=tenant.id,
                detail={
                    "operator": operator,
                    "tenant_code": code,
                    "tenant_name": tenant.name,
                    "tenant_created": tenant_created,
                    "user_created": user_created,
                    "username": uname,
                    "reset_password": bool(reset_password),
                },
                ip="127.0.0.1",
            )
        )

        await db.commit()
        print("bootstrap_done")
        print(f"tenant_id={tenant.id} tenant_code={tenant.code} tenant_name={tenant.name}")
        print(f"user_id={user.id} username={user.username} role={user.role} tenant_id={user.tenant_id}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="一键初始化租户 + 租户超级管理员")
    parser.add_argument("--tenant-code", help="租户编码（英文/数字/短横线），如 hz-nanke")
    parser.add_argument("--tenant-name", help="租户名称，如 杭州男科")
    parser.add_argument("--username", help="租户超级管理员用户名")
    parser.add_argument("--password", help="租户超级管理员密码")
    parser.add_argument("--real-name", help="租户超级管理员姓名")
    parser.add_argument("--operator", default="bootstrap_script", help="操作人标识（写入审计）")
    parser.add_argument("--allow-existing", action="store_true", help="允许复用已存在租户/账号")
    parser.add_argument("--reset-password", action="store_true", help="复用已有账号时重置密码")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    tenant_code = _prompt_if_empty(args.tenant_code, "租户编码")
    tenant_name = _prompt_if_empty(args.tenant_name, "租户名称")
    username = _prompt_if_empty(args.username, "租户超级管理员用户名")
    password = _prompt_if_empty(args.password, "租户超级管理员密码", secret=True)
    real_name = _prompt_if_empty(args.real_name, "租户超级管理员姓名")

    asyncio.run(
        bootstrap(
            tenant_code=tenant_code,
            tenant_name=tenant_name,
            username=username,
            password=password,
            real_name=real_name,
            operator=args.operator.strip() or "bootstrap_script",
            allow_existing=bool(args.allow_existing),
            reset_password=bool(args.reset_password),
        )
    )


if __name__ == "__main__":
    main()

