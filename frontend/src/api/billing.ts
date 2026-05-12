import request from './request'

interface ApiResponse<T> {
  code: number
  message: string
  data: T
}

export interface BillingSummaryCard {
  total_requests: number
  total_tenants: number
  total_users: number
  avg_duration_ms: number
}

export interface BillingBreakdownItem {
  key: string
  label: string
  requests: number
  ratio: number
}

export interface BillingSummaryData {
  range_start: string | null
  range_end: string | null
  module_id: string | null
  tenant_id: number | null
  cards: BillingSummaryCard
  by_module: BillingBreakdownItem[]
  by_tenant: BillingBreakdownItem[]
}

export interface BillingTrendItem {
  day: string
  requests: number
  avg_duration_ms: number
}

export interface BillingTrendData {
  items: BillingTrendItem[]
  total: number
}

export interface BillingRecordItem {
  id: number
  tenant_id: number | null
  tenant_name: string | null
  user_id: number | null
  module_id: string
  action: string
  endpoint: string | null
  method: string | null
  status_code: number | null
  duration_ms: number | null
  quantity: number
  unit: string
  created_at: string
}

export interface BillingRecordListData {
  items: BillingRecordItem[]
  total: number
  page: number
  page_size: number
}

export interface BillingPriceRuleItem {
  module_id: string
  module_label: string
  unit: string
  unit_price: number
}

export interface BillingEstimateModuleItem {
  module_id: string
  module_label: string
  requests: number
  unit_price: number
  estimated_cost: number
}

export interface BillingEstimateTenantItem {
  tenant_id: number | null
  tenant_name: string
  total_requests: number
  total_estimated_cost: number
  modules: BillingEstimateModuleItem[]
}

export interface BillingMonthlyEstimateData {
  month: string
  tenant_id: number | null
  module_id: string | null
  price_rules: BillingPriceRuleItem[]
  tenants: BillingEstimateTenantItem[]
  total_requests: number
  total_estimated_cost: number
}

export const getBillingSummary = async (params?: {
  start_date?: string
  end_date?: string
  tenant_id?: number
  module_id?: string
}) => {
  const res = await request.get<ApiResponse<BillingSummaryData>>('/billing/summary', { params })
  return res.data.data
}

export const getBillingTrend = async (params?: {
  days?: number
  tenant_id?: number
  module_id?: string
}) => {
  const res = await request.get<ApiResponse<BillingTrendData>>('/billing/trend', { params })
  return res.data.data
}

export const getBillingRecords = async (params?: {
  page?: number
  page_size?: number
  start_date?: string
  end_date?: string
  tenant_id?: number
  module_id?: string
}) => {
  const res = await request.get<ApiResponse<BillingRecordListData>>('/billing/records', { params })
  return res.data.data
}

export const getBillingMonthlyEstimate = async (params?: {
  month?: string
  tenant_id?: number
  module_id?: string
}) => {
  const res = await request.get<ApiResponse<BillingMonthlyEstimateData>>('/billing/monthly-estimate', { params })
  return res.data.data
}

