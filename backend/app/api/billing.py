from __future__ import annotations

from datetime import date, datetime, time, timedelta
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import require_platform_super_admin
from app.models import Tenant, UsageRecord, User
from app.schemas.billing import (
    ApiResponse,
    BillingBreakdownItem,
    BillingEstimateModuleItem,
    BillingEstimateTenantItem,
    BillingMonthlyEstimateData,
    BillingPriceRuleItem,
    BillingRecordItem,
    BillingRecordListData,
    BillingSummaryCard,
    BillingSummaryData,
    BillingTrendData,
    BillingTrendItem,
)

router = APIRouter()

MODULE_LABELS: dict[str, str] = {
    "mod_training": "对话训练",
    "mod_faq": "FAQ 知识库",
    "mod_ai_scoring": "AI 评分",
    "mod_stats": "统计分析",
    "mod_export": "数据导出",
    "mod_audit": "审计增强",
}

# 简易费用估算规则（按模块单价，单位：元/请求）
MODULE_UNIT_PRICES: dict[str, float] = {
    "mod_training": 0.0010,
    "mod_faq": 0.0030,
    "mod_ai_scoring": 0.0080,
    "mod_stats": 0.0005,
    "mod_export": 0.0020,
    "mod_audit": 0.0008,
}


def _build_time_filters(
    start_date: date | None,
    end_date: date | None,
) -> tuple[datetime | None, datetime | None]:
    start_dt = datetime.combine(start_date, time.min) if start_date else None
    # 用 [start, end) 区间，避免 datetime 精度差异
    end_dt = datetime.combine(end_date + timedelta(days=1), time.min) if end_date else None
    return start_dt, end_dt


def _month_range(month: str) -> tuple[datetime, datetime]:
    # YYYY-MM
    start = datetime.strptime(f"{month}-01", "%Y-%m-%d")
    if start.month == 12:
        end = datetime(start.year + 1, 1, 1)
    else:
        end = datetime(start.year, start.month + 1, 1)
    return start, end


@router.get("/summary", response_model=ApiResponse)
async def billing_summary(
    _: User = Depends(require_platform_super_admin),
    db: AsyncSession = Depends(get_db),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    tenant_id: int | None = Query(default=None),
    module_id: str | None = Query(default=None),
) -> ApiResponse:
    start_dt, end_dt = _build_time_filters(start_date, end_date)
    filters = []
    if start_dt:
        filters.append(UsageRecord.created_at >= start_dt)
    if end_dt:
        filters.append(UsageRecord.created_at < end_dt)
    if tenant_id is not None:
        filters.append(UsageRecord.tenant_id == tenant_id)
    if module_id:
        filters.append(UsageRecord.module_id == module_id.strip())

    row = (
        await db.execute(
            select(
                func.sum(UsageRecord.quantity).label("total_requests"),
                func.count(func.distinct(UsageRecord.tenant_id)).label("total_tenants"),
                func.count(func.distinct(UsageRecord.user_id)).label("total_users"),
                func.avg(UsageRecord.duration_ms).label("avg_duration_ms"),
            ).where(*filters)
        )
    ).one()
    total_requests = int(row.total_requests or 0)
    total_tenants = int(row.total_tenants or 0)
    total_users = int(row.total_users or 0)
    avg_duration_ms = round(float(row.avg_duration_ms or 0.0), 2)

    module_rows = (
        await db.execute(
            select(
                UsageRecord.module_id,
                func.sum(UsageRecord.quantity).label("requests"),
            )
            .where(*filters)
            .group_by(UsageRecord.module_id)
            .order_by(func.sum(UsageRecord.quantity).desc())
        )
    ).all()
    by_module = [
        BillingBreakdownItem(
            key=str(r.module_id),
            label=str(r.module_id),
            requests=int(r.requests or 0),
            ratio=round((int(r.requests or 0) / total_requests * 100.0), 2) if total_requests > 0 else 0.0,
        )
        for r in module_rows
    ]

    tenant_rows = (
        await db.execute(
            select(
                UsageRecord.tenant_id,
                Tenant.name,
                func.sum(UsageRecord.quantity).label("requests"),
            )
            .outerjoin(Tenant, Tenant.id == UsageRecord.tenant_id)
            .where(*filters)
            .group_by(UsageRecord.tenant_id, Tenant.name)
            .order_by(func.sum(UsageRecord.quantity).desc())
        )
    ).all()
    by_tenant = [
        BillingBreakdownItem(
            key=str(r.tenant_id or "0"),
            label=str(r.name or f"租户#{int(r.tenant_id or 0)}"),
            requests=int(r.requests or 0),
            ratio=round((int(r.requests or 0) / total_requests * 100.0), 2) if total_requests > 0 else 0.0,
        )
        for r in tenant_rows
    ]

    return ApiResponse(
        code=200,
        message="success",
        data=BillingSummaryData(
            range_start=start_date.isoformat() if start_date else None,
            range_end=end_date.isoformat() if end_date else None,
            module_id=module_id,
            tenant_id=tenant_id,
            cards=BillingSummaryCard(
                total_requests=total_requests,
                total_tenants=total_tenants,
                total_users=total_users,
                avg_duration_ms=avg_duration_ms,
            ),
            by_module=by_module,
            by_tenant=by_tenant,
        ),
    )


@router.get("/trend", response_model=ApiResponse)
async def billing_trend(
    _: User = Depends(require_platform_super_admin),
    db: AsyncSession = Depends(get_db),
    days: int = Query(default=30, ge=1, le=180),
    tenant_id: int | None = Query(default=None),
    module_id: str | None = Query(default=None),
) -> ApiResponse:
    start_dt = datetime.combine((date.today() - timedelta(days=days - 1)), time.min)
    filters = [UsageRecord.created_at >= start_dt]
    if tenant_id is not None:
        filters.append(UsageRecord.tenant_id == tenant_id)
    if module_id:
        filters.append(UsageRecord.module_id == module_id.strip())

    rows = (
        await db.execute(
            select(
                func.date(UsageRecord.created_at).label("day"),
                func.sum(UsageRecord.quantity).label("requests"),
                func.avg(UsageRecord.duration_ms).label("avg_duration_ms"),
            )
            .where(*filters)
            .group_by(func.date(UsageRecord.created_at))
            .order_by(func.date(UsageRecord.created_at).asc())
        )
    ).all()

    row_map = {str(r.day): (int(r.requests or 0), round(float(r.avg_duration_ms or 0.0), 2)) for r in rows}
    items: list[BillingTrendItem] = []
    for i in range(days):
        current_day = (date.today() - timedelta(days=days - 1 - i)).isoformat()
        reqs, avg_ms = row_map.get(current_day, (0, 0.0))
        items.append(BillingTrendItem(day=current_day, requests=reqs, avg_duration_ms=avg_ms))
    return ApiResponse(code=200, message="success", data=BillingTrendData(items=items, total=len(items)))


@router.get("/records", response_model=ApiResponse)
async def billing_records(
    _: User = Depends(require_platform_super_admin),
    db: AsyncSession = Depends(get_db),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    tenant_id: int | None = Query(default=None),
    module_id: str | None = Query(default=None),
) -> ApiResponse:
    start_dt, end_dt = _build_time_filters(start_date, end_date)
    filters = []
    if start_dt:
        filters.append(UsageRecord.created_at >= start_dt)
    if end_dt:
        filters.append(UsageRecord.created_at < end_dt)
    if tenant_id is not None:
        filters.append(UsageRecord.tenant_id == tenant_id)
    if module_id:
        filters.append(UsageRecord.module_id == module_id.strip())

    total = int((await db.execute(select(func.count(UsageRecord.id)).where(*filters))).scalar_one() or 0)
    rows = (
        await db.execute(
            select(UsageRecord, Tenant.name)
            .outerjoin(Tenant, Tenant.id == UsageRecord.tenant_id)
            .where(*filters)
            .order_by(UsageRecord.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()

    items = [
        BillingRecordItem(
            id=r.id,
            tenant_id=r.tenant_id,
            tenant_name=tenant_name,
            user_id=r.user_id,
            module_id=r.module_id,
            action=r.action,
            endpoint=r.endpoint,
            method=r.method,
            status_code=r.status_code,
            duration_ms=r.duration_ms,
            quantity=r.quantity,
            unit=r.unit,
            created_at=r.created_at,
        )
        for r, tenant_name in rows
    ]
    return ApiResponse(
        code=200,
        message="success",
        data=BillingRecordListData(items=items, total=total, page=page, page_size=page_size),
    )


@router.get("/monthly-estimate", response_model=ApiResponse)
async def billing_monthly_estimate(
    _: User = Depends(require_platform_super_admin),
    db: AsyncSession = Depends(get_db),
    month: str = Query(default_factory=lambda: date.today().strftime("%Y-%m")),
    tenant_id: int | None = Query(default=None),
    module_id: str | None = Query(default=None),
) -> ApiResponse:
    try:
        month_start, month_end = _month_range(month)
    except ValueError:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail="month 参数格式错误，应为 YYYY-MM")

    filters = [
        UsageRecord.created_at >= month_start,
        UsageRecord.created_at < month_end,
    ]
    if tenant_id is not None:
        filters.append(UsageRecord.tenant_id == tenant_id)
    if module_id:
        filters.append(UsageRecord.module_id == module_id.strip())

    rows = (
        await db.execute(
            select(
                UsageRecord.tenant_id,
                Tenant.name,
                UsageRecord.module_id,
                func.sum(UsageRecord.quantity).label("requests"),
            )
            .outerjoin(Tenant, Tenant.id == UsageRecord.tenant_id)
            .where(*filters)
            .group_by(UsageRecord.tenant_id, Tenant.name, UsageRecord.module_id)
            .order_by(UsageRecord.tenant_id.asc(), UsageRecord.module_id.asc())
        )
    ).all()

    grouped: dict[int | None, dict] = {}
    total_requests = 0
    total_estimated_cost = 0.0

    for tenant_id_row, tenant_name, module_id_row, reqs in rows:
        requests = int(reqs or 0)
        if requests <= 0:
            continue
        tenant_key = int(tenant_id_row) if tenant_id_row is not None else None
        if tenant_key not in grouped:
            grouped[tenant_key] = {
                "tenant_name": str(tenant_name or f"租户#{tenant_key or 0}"),
                "modules": [],
                "total_requests": 0,
                "total_estimated_cost": 0.0,
            }

        unit_price = float(MODULE_UNIT_PRICES.get(str(module_id_row), 0.0))
        estimated_cost = round(requests * unit_price, 6)
        grouped[tenant_key]["modules"].append(
            BillingEstimateModuleItem(
                module_id=str(module_id_row),
                module_label=MODULE_LABELS.get(str(module_id_row), str(module_id_row)),
                requests=requests,
                unit_price=unit_price,
                estimated_cost=estimated_cost,
            )
        )
        grouped[tenant_key]["total_requests"] += requests
        grouped[tenant_key]["total_estimated_cost"] = round(
            grouped[tenant_key]["total_estimated_cost"] + estimated_cost,
            6,
        )
        total_requests += requests
        total_estimated_cost = round(total_estimated_cost + estimated_cost, 6)

    tenants = [
        BillingEstimateTenantItem(
            tenant_id=tenant_key,
            tenant_name=data["tenant_name"],
            total_requests=int(data["total_requests"]),
            total_estimated_cost=float(data["total_estimated_cost"]),
            modules=sorted(data["modules"], key=lambda x: x.estimated_cost, reverse=True),
        )
        for tenant_key, data in grouped.items()
    ]
    tenants.sort(key=lambda x: x.total_estimated_cost, reverse=True)

    price_rules = [
        BillingPriceRuleItem(
            module_id=mid,
            module_label=MODULE_LABELS.get(mid, mid),
            unit="request",
            unit_price=float(price),
        )
        for mid, price in MODULE_UNIT_PRICES.items()
    ]
    price_rules.sort(key=lambda x: x.module_id)

    return ApiResponse(
        code=200,
        message="success",
        data=BillingMonthlyEstimateData(
            month=month,
            tenant_id=tenant_id,
            module_id=module_id,
            price_rules=price_rules,
            tenants=tenants,
            total_requests=total_requests,
            total_estimated_cost=total_estimated_cost,
        ),
    )

