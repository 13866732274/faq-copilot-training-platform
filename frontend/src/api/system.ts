import request from './request'
import type { AxiosRequestConfig } from 'axios'

interface ApiResponse<T> {
  code: number
  message: string
  data: T
}

export interface PublicSystemSettings {
  site_name: string
  site_subtitle: string
  logo_url?: string | null
  brand_accent: string
  default_tenant_code?: string | null
  show_tenant_input?: boolean
}

export interface SystemSettings extends PublicSystemSettings {
  enable_ai_scoring: boolean
  enable_export_center: boolean
  enable_audit_enhanced: boolean
  admin_menu_template_lock: boolean
  faq_task_timeout_minutes: 5 | 15 | 30
  updated_at: string
}

export interface SystemSettingsUpdatePayload {
  site_name: string
  site_subtitle: string
  logo_url?: string | null
  brand_accent: string
  enable_ai_scoring: boolean
  enable_export_center: boolean
  enable_audit_enhanced: boolean
  admin_menu_template_lock: boolean
  faq_task_timeout_minutes: 5 | 15 | 30
}

export const getPublicSystemSettings = async () => {
  const res = await request.get<ApiResponse<PublicSystemSettings>>('/system/settings/public')
  return res.data.data
}

export const getSystemSettings = async (params?: { tenant_id?: number }) => {
  const res = await request.get<ApiResponse<SystemSettings>>('/system/settings', { params })
  return res.data.data
}

export const updateSystemSettings = async (
  payload: SystemSettingsUpdatePayload,
  params?: { tenant_id?: number },
) => {
  const res = await request.put<ApiResponse<SystemSettings>>('/system/settings', payload, { params })
  return res.data.data
}

const exportBlob = async (url: string, params?: Record<string, string | number | undefined>) => {
  const config: AxiosRequestConfig = {
    params,
    responseType: 'blob',
  }
  const res = await request.get(url, config)
  return res.data as Blob
}

export const exportUsersCsv = async (params?: {
  hospital_id?: number
  department_id?: number
  role?: string
  start_date?: string
  end_date?: string
}) => exportBlob('/system/exports/users', params)

export const exportPracticesCsv = async (params?: {
  hospital_id?: number
  department_id?: number
  status?: string
  start_date?: string
  end_date?: string
}) => exportBlob('/system/exports/practices', params)

export const exportQuizzesCsv = async (params?: {
  hospital_id?: number
  department_id?: number
  scope?: string
  start_date?: string
  end_date?: string
}) => exportBlob('/system/exports/quizzes', params)
