import request from './request'
import { cachedFetch, invalidateCache } from '../utils/apiCache'

interface ApiResponse<T> {
  code: number
  message: string
  data: T
}

export interface DepartmentItem {
  id: number
  hospital_id: number
  hospital_name?: string | null
  code: string
  name: string
  is_active: boolean
  created_at: string
}

export const getDepartments = async (params?: {
  active_only?: boolean
  hospital_id?: number
}) => {
  const cacheKey = `departments:${params?.active_only ?? 'all'}:${params?.hospital_id ?? 'all'}`
  return cachedFetch(cacheKey, async () => {
    const res = await request.get<ApiResponse<DepartmentItem[]>>('/departments', { params })
    return res.data.data
  })
}

export const invalidateDepartmentCache = () => invalidateCache('departments:')

export const createDepartment = async (payload: {
  hospital_id: number
  name: string
  code?: string
}) => {
  const res = await request.post<ApiResponse<DepartmentItem>>('/departments', payload)
  invalidateDepartmentCache()
  return res.data.data
}

export const updateDepartment = async (
  departmentId: number,
  payload: { name?: string; is_active?: boolean; code?: string },
) => {
  const res = await request.put<ApiResponse<DepartmentItem>>(`/departments/${departmentId}`, payload)
  invalidateDepartmentCache()
  return res.data.data
}

export const toggleDepartment = async (departmentId: number) => {
  const res = await request.delete<ApiResponse<DepartmentItem>>(`/departments/${departmentId}`)
  invalidateDepartmentCache()
  return res.data.data
}

export const assignUsersToDepartment = async (
  departmentId: number,
  payload: { user_ids: number[]; mode?: 'replace' | 'append' },
) => {
  const res = await request.put<ApiResponse<DepartmentItem>>(
    `/departments/${departmentId}/assign-users`,
    payload,
  )
  return res.data.data
}
