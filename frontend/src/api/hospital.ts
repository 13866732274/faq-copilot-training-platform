import request from './request'
import { cachedFetch, invalidateCache } from '../utils/apiCache'

interface ApiResponse<T> {
  code: number
  message: string
  data: T
}

export interface HospitalItem {
  id: number
  code: string
  name: string
  short_name?: string | null
  is_active: boolean
  created_at: string
}

export const getHospitals = async (params?: { active_only?: boolean }) => {
  const cacheKey = `hospitals:${params?.active_only ?? 'all'}`
  return cachedFetch(cacheKey, async () => {
    const res = await request.get<ApiResponse<HospitalItem[]>>('/hospitals', { params })
    return res.data.data
  })
}

export const invalidateHospitalCache = () => invalidateCache('hospitals:')

export const createHospital = async (payload: { name: string; short_name?: string; code?: string }) => {
  const res = await request.post<ApiResponse<HospitalItem>>('/hospitals', payload)
  invalidateHospitalCache()
  return res.data.data
}

export const updateHospital = async (
  hospitalId: number,
  payload: { name?: string; short_name?: string; is_active?: boolean; code?: string },
) => {
  const res = await request.put<ApiResponse<HospitalItem>>(`/hospitals/${hospitalId}`, payload)
  invalidateHospitalCache()
  return res.data.data
}

export const toggleHospital = async (hospitalId: number) => {
  const res = await request.delete<ApiResponse<HospitalItem>>(`/hospitals/${hospitalId}`)
  invalidateHospitalCache()
  return res.data.data
}

export const assignUsersToHospital = async (
  hospitalId: number,
  payload: { user_ids: number[]; mode?: 'replace' | 'append' },
) => {
  const res = await request.put<ApiResponse<HospitalItem>>(`/hospitals/${hospitalId}/assign-users`, payload)
  return res.data.data
}
