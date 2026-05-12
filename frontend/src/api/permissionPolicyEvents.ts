import request from './request'

interface ApiResponse<T> {
  code: number
  message: string
  data: T
}

export interface PermissionPolicyEventItem {
  id: number
  at: string
  stage: 'success' | 'retry' | 'failed'
  attempt: number
  duration_ms: number
  error?: string
  created_at?: string | null
}

export async function appendPermissionPolicyEvent(payload: {
  at?: string
  stage: 'success' | 'retry' | 'failed'
  attempt: number
  duration_ms: number
  error?: string
}) {
  await request.post('/system/permission-policy-events', payload)
}

export async function listPermissionPolicyEvents(page = 1, pageSize = 50): Promise<{
  items: PermissionPolicyEventItem[]
  total: number
}> {
  const resp = await request.get<ApiResponse<{ items: PermissionPolicyEventItem[]; total: number }>>(
    '/system/permission-policy-events',
    { params: { page, page_size: pageSize } },
  )
  return resp.data.data
}

export async function deletePermissionPolicyEvent(eventId: number): Promise<void> {
  await request.delete(`/system/permission-policy-events/${eventId}`)
}

export async function batchDeletePermissionPolicyEvents(ids: number[]): Promise<{ deleted: number }> {
  const resp = await request.post<ApiResponse<{ deleted: number }>>('/system/permission-policy-events/batch-delete', { ids })
  return resp.data.data
}

export async function clearPermissionPolicyEvents(): Promise<{ deleted: number }> {
  const resp = await request.post<ApiResponse<{ deleted: number }>>('/system/permission-policy-events/clear')
  return resp.data.data
}
