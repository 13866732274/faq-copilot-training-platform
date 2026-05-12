const TOKEN_KEY = 'chattrainer_token'
const USER_KEY = 'chattrainer_user'
const LAST_ROUTE_KEY = 'chattrainer_last_route'

export interface LoginUser {
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
  avatar?: string | null
  tenant_id?: number | null
  tenant_name?: string | null
  is_platform_super_admin?: boolean
  is_impersonating?: boolean
  impersonation_tenant_id?: number | null
  impersonation_tenant_name?: string | null
  impersonation_expires_at?: string | null
  impersonation_reason?: string | null
  enabled_modules?: string[]
}

export function setAuth(token: string, user: LoginUser) {
  localStorage.setItem(TOKEN_KEY, token)
  localStorage.setItem(USER_KEY, JSON.stringify(user))
}

export function clearAuth() {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(USER_KEY)
}

export function getToken() {
  return localStorage.getItem(TOKEN_KEY) || ''
}

export function getCurrentUser(): LoginUser | null {
  const raw = localStorage.getItem(USER_KEY)
  if (!raw) return null
  try {
    return JSON.parse(raw) as LoginUser
  } catch {
    return null
  }
}

export function isAdminRole(role?: string) {
  return role === 'admin' || role === 'super_admin'
}

export function setLastRoute(routePath: string) {
  if (!routePath || routePath.startsWith('/login')) return
  localStorage.setItem(LAST_ROUTE_KEY, routePath)
}

export function getLastRoute() {
  return localStorage.getItem(LAST_ROUTE_KEY) || ''
}

export function clearLastRoute() {
  localStorage.removeItem(LAST_ROUTE_KEY)
}
