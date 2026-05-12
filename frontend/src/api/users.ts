import request from './request'

interface ApiResponse<T> {
  code: number
  message: string
  data: T
}

export interface UserItem {
  id: number
  username: string
  real_name: string
  role: 'super_admin' | 'admin' | 'student'
  hospital_id?: number | null
  hospital_name?: string | null
  hospital_ids?: number[]
  department_id?: number | null
  department_name?: string | null
  department_ids?: number[]
  menu_permissions?: string[] | null
  is_all_hospitals?: boolean
  tenant_id?: number | null
  tenant_name?: string | null
  is_active: boolean
  created_at: string
}

export const getUsers = async (params: {
  page: number
  page_size: number
  keyword?: string
  role?: string
  hospital_id?: number
  department_id?: number
}) => {
  const res = await request.get<ApiResponse<{ items: UserItem[]; total: number; page: number; page_size: number }>>(
    '/users',
    { params },
  )
  return res.data.data
}

export const createUser = async (payload: {
  username: string
  password: string
  real_name: string
  role: string
  hospital_id?: number
  hospital_ids?: number[]
  department_id?: number
  department_ids?: number[]
  menu_permissions?: string[] | null
  is_all_hospitals?: boolean
  tenant_id?: number
}) => {
  const res = await request.post<ApiResponse<UserItem>>('/users', payload)
  return res.data.data
}

export const updateUser = async (
  userId: number,
  payload: {
    real_name?: string
    role?: string
    password?: string
    hospital_id?: number
    hospital_ids?: number[]
    department_id?: number
    department_ids?: number[]
    menu_permissions?: string[] | null
    is_all_hospitals?: boolean
    tenant_id?: number
  },
) => {
  const res = await request.put<ApiResponse<UserItem>>(`/users/${userId}`, payload)
  return res.data.data
}

export const toggleUser = async (userId: number) => {
  const res = await request.delete<ApiResponse<UserItem>>(`/users/${userId}`)
  return res.data.data
}

export const bulkImportStudents = async (payload: {
  role?: 'student' | 'admin'
  hospital_id?: number
  department_id?: number
  default_password?: string
  items: Array<{
    username: string
    real_name: string
    password?: string
    hospital_id?: number
    department_id?: number
  }>
}) => {
  const res = await request.post<
    ApiResponse<{
      total: number
      created: number
      skipped: number
      errors: string[]
      failed_items?: Array<{
        line_no: number
        username: string
        real_name: string
        reason: string
      }>
    }>
  >('/users/bulk-import-students', payload)
  return res.data.data
}

export const bulkSetUserStatus = async (payload: { user_ids: number[]; is_active: boolean }) => {
  const res = await request.post<
    ApiResponse<{ total: number; updated: number; skipped: number; skipped_user_ids: number[] }>
  >('/users/bulk-status', payload)
  return res.data.data
}

export const bulkSetUserMenuPermissions = async (payload: {
  user_ids: number[]
  menu_permissions: string[] | null
}) => {
  const res = await request.post<
    ApiResponse<{
      total: number
      updated: number
      skipped: number
      skipped_user_ids: number[]
      skipped_reason_ids?: Record<string, number[]>
    }>
  >('/users/bulk-menu-permissions', payload)
  return res.data.data
}
