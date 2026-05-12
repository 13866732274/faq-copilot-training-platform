from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class BillingSummaryCard(BaseModel):
    total_requests: int
    total_tenants: int
    total_users: int
    avg_duration_ms: float


class BillingBreakdownItem(BaseModel):
    key: str
    label: str
    requests: int
    ratio: float


class BillingSummaryData(BaseModel):
    range_start: str | None = None
    range_end: str | None = None
    module_id: str | None = None
    tenant_id: int | None = None
    cards: BillingSummaryCard
    by_module: list[BillingBreakdownItem]
    by_tenant: list[BillingBreakdownItem]


class BillingTrendItem(BaseModel):
    day: str
    requests: int
    avg_duration_ms: float


class BillingTrendData(BaseModel):
    items: list[BillingTrendItem]
    total: int


class BillingRecordItem(BaseModel):
    id: int
    tenant_id: int | None = None
    tenant_name: str | None = None
    user_id: int | None = None
    module_id: str
    action: str
    endpoint: str | None = None
    method: str | None = None
    status_code: int | None = None
    duration_ms: int | None = None
    quantity: int
    unit: str
    created_at: datetime


class BillingRecordListData(BaseModel):
    items: list[BillingRecordItem]
    total: int
    page: int
    page_size: int


class BillingPriceRuleItem(BaseModel):
    module_id: str
    module_label: str
    unit: str = "request"
    unit_price: float


class BillingEstimateModuleItem(BaseModel):
    module_id: str
    module_label: str
    requests: int
    unit_price: float
    estimated_cost: float


class BillingEstimateTenantItem(BaseModel):
    tenant_id: int | None = None
    tenant_name: str
    total_requests: int
    total_estimated_cost: float
    modules: list[BillingEstimateModuleItem]


class BillingMonthlyEstimateData(BaseModel):
    month: str
    tenant_id: int | None = None
    module_id: str | None = None
    price_rules: list[BillingPriceRuleItem]
    tenants: list[BillingEstimateTenantItem]
    total_requests: int
    total_estimated_cost: float


class ApiResponse(BaseModel):
    code: int
    message: str
    data: (
        BillingSummaryData
        | BillingTrendData
        | BillingRecordListData
        | BillingMonthlyEstimateData
        | None
    ) = None

