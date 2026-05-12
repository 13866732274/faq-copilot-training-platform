import request from './request'

interface ApiResponse<T> {
  code: number
  message: string
  data: T
}

export interface TenantItem {
  id: number
  code: string
  name: string
  is_active: boolean
  session_version: number
  created_at: string
  updated_at: string
}

export interface ModuleDefinitionItem {
  module_id: string
  name: string
  description: string | null
  icon: string | null
  menu_keys: string[]
  permission_points: string[]
  dependencies: string[]
  is_default: boolean
  sort_order: number
}

export interface TenantModuleItem {
  tenant_id: number
  module_id: string
  name: string
  description: string | null
  icon: string | null
  menu_keys: string[]
  dependencies: string[]
  depended_by: string[]
  is_default: boolean
  is_enabled: boolean
  source: 'default' | 'tenant_override'
  enabled_at: string | null
  disabled_at: string | null
  sort_order: number
}

export interface TenantModuleListData {
  tenant_id: number
  tenant_name: string
  items: TenantModuleItem[]
  total: number
}

export const getTenants = async () => {
  const res = await request.get<ApiResponse<{ items: TenantItem[]; total: number }>>('/tenants')
  return res.data.data
}

export const createTenant = async (payload: { code: string; name: string }) => {
  const res = await request.post<ApiResponse<TenantItem>>('/tenants', payload)
  return res.data.data
}

export const updateTenant = async (tenantId: number, payload: { name?: string; is_active?: boolean }) => {
  const res = await request.put<ApiResponse<TenantItem>>(`/tenants/${tenantId}`, payload)
  return res.data.data
}

export const getModuleDefinitions = async () => {
  const res = await request.get<ApiResponse<{ items: ModuleDefinitionItem[]; total: number }>>('/tenants/modules')
  return res.data.data
}

export const getTenantModules = async (tenantId: number) => {
  const res = await request.get<ApiResponse<TenantModuleListData>>(`/tenants/${tenantId}/modules`)
  return res.data.data
}

export const updateTenantModule = async (
  tenantId: number,
  payload: { module_id: string; is_enabled: boolean; config_json?: string | null },
) => {
  const res = await request.put<ApiResponse<TenantModuleListData>>(`/tenants/${tenantId}/modules`, payload)
  return res.data.data
}
