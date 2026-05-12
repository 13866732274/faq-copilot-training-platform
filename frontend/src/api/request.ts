import axios from 'axios'
import { clearAuth, getCurrentUser, getToken, setLastRoute } from '../utils/auth'
import { toChineseErrorMessage } from '../utils/errorMessage'
import { pushGlobalNotice } from '../utils/globalNotice'

const PERMISSION_POINTS_CACHE_KEY = 'permission-points-cache'
const MENU_ACCESS_CACHE_KEY = 'menu-access-cache'

let hasShownAuthExpiredMessage = false

const parseBody = (data: unknown): Record<string, any> => {
  if (!data) return {}
  if (typeof data === 'object') return data as Record<string, any>
  if (typeof data === 'string') {
    try {
      return JSON.parse(data) as Record<string, any>
    } catch {
      return {}
    }
  }
  return {}
}

const isHighRiskImpersonationWrite = (config: any): boolean => {
  const method = String(config?.method || 'get').toLowerCase()
  const url = String(config?.url || '')
  const params = (config?.params || {}) as Record<string, any>
  const body = parseBody(config?.data)

  // 1) 租户停用
  if (method === 'put' && /^\/tenants\/\d+$/.test(url)) {
    if (Object.prototype.hasOwnProperty.call(body, 'is_active') && body.is_active === false) return true
  }

  // 2) 批量禁用用户
  if (method === 'post' && url === '/users/bulk-status') {
    if (Object.prototype.hasOwnProperty.call(body, 'is_active') && body.is_active === false) return true
  }

  // 3) 单用户状态切换（delete 接口）
  if (method === 'delete' && /^\/users\/\d+$/.test(url)) {
    return true
  }

  // 4) 案例库硬删除
  if (method === 'delete' && /^\/quizzes\/\d+$/.test(url)) {
    const hardParam = params.hard
    const hard = hardParam === true || hardParam === 'true' || hardParam === 1 || hardParam === '1'
    if (hard) return true
  }

  return false
}

const request = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api/v1',
  timeout: 15000,
})

request.interceptors.request.use((config) => {
  const url = String(config.url || '')
  const bypassConfirm = url.includes('/auth/login') || url.includes('/auth/impersonation/')
  if (!bypassConfirm) {
    const currentUser = getCurrentUser()
    if (currentUser?.is_impersonating && isHighRiskImpersonationWrite(config)) {
      const method = String(config.method || 'get').toLowerCase().toUpperCase()
      const targetTenant = currentUser.impersonation_tenant_name || currentUser.tenant_name || '目标租户'
      const ok = window.confirm(
        `你当前处于“租户代入”模式。\n将执行高风险操作：${method} ${url || '-'}\n作用租户：${targetTenant}\n\n请确认该操作仅用于排障且已获授权。`,
      )
      if (!ok) {
        return Promise.reject(new axios.Cancel('impersonation_write_confirm_cancelled'))
      }
    }
  }
  const token = getToken()
  if (token) {
    config.headers = config.headers || {}
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

request.interceptors.response.use(
  (response) => response,
  (error) => {
    if (axios.isCancel(error)) {
      return Promise.reject(error)
    }
    const status = error?.response?.status
    const url = String(error?.config?.url || '')
    const isLoginApi = url.includes('/auth/login')
    const onLoginPage = window.location.pathname === '/login'
    if (status === 401 && !isLoginApi) {
      const current = window.location.pathname + window.location.search
      setLastRoute(current)
      if (!hasShownAuthExpiredMessage && !onLoginPage) {
        hasShownAuthExpiredMessage = true
        pushGlobalNotice(
          {
            title: '登录已过期，请重新登录',
            type: 'warning',
            duration: 3000,
            detail: `接口返回 401，当前会话已失效，请重新登录后继续操作。请求地址：${url || '-'}`,
            errorCode: 'AUTH-401',
          },
          { persistForNextLoad: true },
        )
        setTimeout(() => {
          hasShownAuthExpiredMessage = false
        }, 1500)
      }
      clearAuth()
      window.localStorage.removeItem(PERMISSION_POINTS_CACHE_KEY)
      window.localStorage.removeItem(MENU_ACCESS_CACHE_KEY)
      if (!onLoginPage) {
        window.location.href = `/login?redirect=${encodeURIComponent(current)}`
      }
    }

    const backendDetail = error?.response?.data?.detail
    const normalizedDetail = typeof backendDetail === 'string' ? backendDetail : ''
    if (status === 403 && normalizedDetail.includes('租户已停用') && !isLoginApi) {
      const current = window.location.pathname + window.location.search
      setLastRoute(current)
      pushGlobalNotice(
        {
          title: '所属租户已停用，已退出登录',
          type: 'warning',
          duration: 3500,
          detail: `当前账号所属租户处于停用状态，无法继续访问系统。请求地址：${url || '-'}`,
          errorCode: 'TENANT-INACTIVE',
        },
        { persistForNextLoad: true, skipDedupe: true },
      )
      clearAuth()
      window.localStorage.removeItem(PERMISSION_POINTS_CACHE_KEY)
      window.localStorage.removeItem(MENU_ACCESS_CACHE_KEY)
      if (!onLoginPage) {
        window.location.href = '/login'
      }
    }

    if (status === 403 && !normalizedDetail.includes('租户已停用') && !isLoginApi && !onLoginPage) {
      const msg403 = error?.response?.data?.detail || '当前账号无权限执行该操作'
      pushGlobalNotice({
        title: typeof msg403 === 'string' ? msg403 : '当前账号无权限执行该操作',
        type: 'warning',
        duration: 3000,
        detail: `接口返回 403。请求地址：${url || '-'}`,
        errorCode: 'AUTH-403',
      })
    }

    if (typeof backendDetail === 'string' && backendDetail) {
      const zhDetail = toChineseErrorMessage(backendDetail, backendDetail)
      error.response.data.detail = zhDetail
      error.message = zhDetail
    } else if (!error?.response && error?.message?.includes('timeout')) {
      error.message = '请求超时，请稍后重试'
    } else if (!error?.response) {
      error.message = '网络异常，请检查网络连接'
    } else if (!error?.response?.data?.detail) {
      if (status === 400) error.message = '请求参数有误'
      else if (status === 401) error.message = '用户名或密码错误'
      else if (status === 403) error.message = '当前账号无权限执行该操作'
      else if (status === 404) error.message = '请求资源不存在'
      else if (status >= 500) error.message = '服务器繁忙，请稍后再试'
      else error.message = '请求失败，请稍后重试'
    }
    if (!error?.response?.data?.detail && error?.message) {
      error.message = toChineseErrorMessage(error.message, error.message)
    }
    return Promise.reject(error)
  },
)

export default request
