import request from './request'

interface ApiResponse<T> {
  code: number
  message: string
  data: T
}

export interface ConfigurableMenuAuditEntry {
  menu_key: string
  runtime_allowed: boolean
  in_db: boolean | null
  via_compat: boolean
}

export interface PermissionAuditUserItem {
  user_id: number
  username: string
  real_name: string
  role: string
  is_active: boolean
  permission_mode: 'default_all' | 'custom' | 'invalid_json'
  raw_menu_permissions: string | null
  parsed_menu_permissions: string[] | null
  configurable_menu_audit: ConfigurableMenuAuditEntry[]
  issues: string[]
  issue_count: number
}

export interface PermissionAuditSummary {
  total: number
  active: number
  inactive: number
  default_all: number
  custom: number
  invalid_json: number
  has_issues: number
  missing_quiz_taxonomy_explicit: number
}

export interface PermissionAuditData {
  summary: PermissionAuditSummary
  items: PermissionAuditUserItem[]
  all_configurable_menu_keys: string[]
  all_menu_keys: string[]
}

export interface PermissionFixResult {
  fixed_count: number
  fixed_users: Array<{
    user_id: number
    username: string
    real_name: string
    added: string
  }>
}

export async function getPermissionAudit(): Promise<PermissionAuditData> {
  const resp = await request.get<ApiResponse<PermissionAuditData>>('/admin/permission-audit')
  return resp.data.data
}

export async function fixPermissionAudit(): Promise<PermissionFixResult> {
  const resp = await request.post<ApiResponse<PermissionFixResult>>('/admin/permission-audit/fix')
  return resp.data.data
}
