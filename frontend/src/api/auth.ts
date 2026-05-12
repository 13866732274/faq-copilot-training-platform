import request from './request'
import type { LoginUser } from '../utils/auth'

interface ApiResponse<T> {
  code: number
  message: string
  data: T
}

interface LoginData {
  access_token: string
  token_type: string
  user: LoginUser
}

interface ImpersonationStartPayload {
  tenant_id: number
  reason?: string
  duration_minutes?: number
}

export const loginApi = async (payload: { username: string; password: string; tenant_code?: string }) => {
  const res = await request.post<ApiResponse<LoginData>>('/auth/login', payload)
  return res.data.data
}

export const meApi = async () => {
  const res = await request.get<ApiResponse<LoginUser & { is_active: boolean; avatar?: string | null }>>('/auth/me')
  return res.data.data
}

export const changePasswordApi = async (payload: { current_password: string; new_password: string }) => {
  const res = await request.put<ApiResponse<{ updated: boolean }>>('/auth/password', payload)
  return res.data.data
}

export const updateProfileApi = async (payload: { real_name?: string; avatar?: string }) => {
  const res = await request.put<ApiResponse<{ id: number; username: string; real_name: string; avatar?: string | null }>>(
    '/auth/profile',
    payload,
  )
  return res.data.data
}

export const getLoginHistoryApi = async (params?: { limit?: number }) => {
  const res = await request.get<
    ApiResponse<Array<{ id: number; status: 'success' | 'fail'; ip?: string | null; reason?: string | null; created_at: string }>>
  >('/auth/login-history', { params })
  return res.data.data
}

export interface PermissionPointItem {
  point: string
  allowed: boolean
  reason: string
}

export interface MenuAccessItem {
  menu_key: string
  allowed: boolean
  reason: string
}

export const getPermissionPointsApi = async () => {
  const res = await request.get<ApiResponse<{ points: PermissionPointItem[]; menus: MenuAccessItem[] }>>('/auth/permission-points')
  return res.data.data
}

export const startImpersonationApi = async (payload: ImpersonationStartPayload) => {
  const res = await request.post<ApiResponse<LoginData>>('/auth/impersonation/start', payload)
  return res.data.data
}

export const stopImpersonationApi = async () => {
  const res = await request.post<ApiResponse<LoginData>>('/auth/impersonation/stop')
  return res.data.data
}
