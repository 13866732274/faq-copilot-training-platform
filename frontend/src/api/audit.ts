import request from './request'

interface ApiResponse<T> {
  code: number
  message: string
  data: T
}

export interface AuditLogItem {
  id: number
  user_id?: number | null
  username?: string | null
  real_name?: string | null
  action: string
  target_type: string
  target_id?: number | null
  hospital_id?: number | null
  hospital_name?: string | null
  department_id?: number | null
  department_name?: string | null
  detail?: Record<string, any> | null
  ip?: string | null
  created_at: string
}

export interface AuditLogListData {
  items: AuditLogItem[]
  total: number
  page: number
  page_size: number
}

export interface AuditLogQuery {
  page: number
  page_size: number
  action?: string
  user_id?: number
  hospital_id?: number
  department_id?: number
  keyword?: string
  start_at?: string
  end_at?: string
}

export const getAuditLogs = async (params: AuditLogQuery) => {
  const res = await request.get<ApiResponse<AuditLogListData>>('/audit-logs', { params })
  return res.data.data
}

export const deleteAuditLog = async (logId: number) => {
  await request.delete(`/audit-logs/${logId}`)
}

export const batchDeleteAuditLogs = async (ids: number[]) => {
  await request.post('/audit-logs/batch-delete', { ids })
}

export const clearAuditLogs = async () => {
  await request.post('/audit-logs/clear')
}
