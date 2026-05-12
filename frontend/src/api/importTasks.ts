import request from './request'

interface ApiResponse<T> {
  code: number
  message: string
  data: T
}

export interface ImportTaskItem {
  id: number
  operator_id: number
  operator_name?: string | null
  scope: 'common' | 'hospital' | 'department'
  hospital_id?: number | null
  hospital_name?: string | null
  department_id?: number | null
  department_name?: string | null
  total: number
  success: number
  duplicate: number
  failed: number
  updated: number
  status: 'running' | 'completed' | 'partial_fail'
  detail?: Record<string, any> | null
  started_at: string
  finished_at?: string | null
  created_at: string
}

export interface ImportTaskPageData {
  items: ImportTaskItem[]
  total: number
  page: number
  page_size: number
}

export const createImportTask = async (payload: {
  scope: 'common' | 'hospital' | 'department'
  hospital_id?: number
  department_id?: number
  total: number
  detail?: Record<string, any>
}) => {
  const res = await request.post<ApiResponse<ImportTaskItem>>('/import-tasks', payload)
  return res.data.data
}

export const finishImportTask = async (
  taskId: number,
  payload: {
    success: number
    duplicate: number
    failed: number
    updated: number
    detail?: Record<string, any>
  },
) => {
  const res = await request.put<ApiResponse<ImportTaskItem>>(`/import-tasks/${taskId}/finish`, payload)
  return res.data.data
}

export const getImportTaskList = async (params: {
  page: number
  page_size: number
  scope?: 'common' | 'hospital' | 'department'
  status?: 'running' | 'completed' | 'partial_fail'
  operator_id?: number
}) => {
  const res = await request.get<ApiResponse<ImportTaskPageData>>('/import-tasks', { params })
  return res.data.data
}

export const getImportTaskDetail = async (taskId: number) => {
  const res = await request.get<ApiResponse<ImportTaskItem>>(`/import-tasks/${taskId}`)
  return res.data.data
}

export const exportImportTaskFailedCsv = async (taskId: number) => {
  const res = await request.get(`/import-tasks/${taskId}/export`, {
    responseType: 'blob',
  })
  return res.data as Blob
}
