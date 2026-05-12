import { ref } from 'vue'
import { getPermissionPointsApi, type MenuAccessItem, type PermissionPointItem } from '../api/auth'
import { appendPermissionPolicyEvent } from '../api/permissionPolicyEvents'

export type PermissionPoint =
  | 'system.settings.update'
  | 'system.export.users'
  | 'system.export.practices'
  | 'system.export.quizzes'
  | 'quiz.batch.reparse'
  | 'quiz.update'
  | 'quiz.restore'
  | 'quiz.delete.soft'
  | 'quiz.delete.hard'
  | 'import.batch.submit'
  | 'import.task.export_failed'

export interface PermissionDecision {
  allowed: boolean
  reason: string
}

const PERMISSION_POINTS_CACHE_KEY = 'permission-points-cache'
const MENU_ACCESS_CACHE_KEY = 'menu-access-cache'
const PERMISSION_POLICY_LOG_KEY = 'permission-policy-events'
const defaultDenied: PermissionDecision = { allowed: false, reason: '权限点加载中，请稍后重试' }
const permissionPointMap = ref<Record<string, PermissionDecision>>({})
const menuAccessMap = ref<Record<string, PermissionDecision>>({})
let loadPromise: Promise<void> | null = null

const sleep = (ms: number) => new Promise<void>((resolve) => {
  window.setTimeout(resolve, ms)
})

const writePolicyEventLog = (event: {
  stage: 'success' | 'retry' | 'failed'
  attempt: number
  duration_ms: number
  error?: string
}) => {
  if (typeof window === 'undefined') return
  const payload = {
    at: new Date().toISOString(),
    ...event,
  }
  try {
    const raw = window.localStorage.getItem(PERMISSION_POLICY_LOG_KEY)
    const list = raw ? (JSON.parse(raw) as Array<Record<string, unknown>>) : []
    const next = [payload, ...list].slice(0, 30)
    window.localStorage.setItem(PERMISSION_POLICY_LOG_KEY, JSON.stringify(next))
  } catch {
    // ignore logging failures
  }
  if (event.stage === 'failed') {
    // eslint-disable-next-line no-console
    console.error('[permission-points] load failed', payload)
  } else if (event.stage === 'retry') {
    // eslint-disable-next-line no-console
    console.warn('[permission-points] retrying load', payload)
  }
  // 后端持久化（异步、失败不阻断主流程）
  appendPermissionPolicyEvent({
    at: payload.at,
    stage: payload.stage,
    attempt: payload.attempt,
    duration_ms: payload.duration_ms,
    error: payload.error,
  }).catch(() => {
    // ignore diagnostics persistence errors
  })
}

const normalize = (items: PermissionPointItem[]): Record<string, PermissionDecision> => {
  return items.reduce<Record<string, PermissionDecision>>((acc, item) => {
    if (!item?.point) return acc
    acc[item.point] = {
      allowed: Boolean(item.allowed),
      reason: item.reason || '',
    }
    return acc
  }, {})
}

const normalizeMenus = (items: MenuAccessItem[]): Record<string, PermissionDecision> => {
  return items.reduce<Record<string, PermissionDecision>>((acc, item) => {
    if (!item?.menu_key) return acc
    acc[item.menu_key] = {
      allowed: Boolean(item.allowed),
      reason: item.reason || '',
    }
    return acc
  }, {})
}

const readCache = () => {
  if (typeof window === 'undefined') return
  try {
    const raw = window.localStorage.getItem(PERMISSION_POINTS_CACHE_KEY)
    if (raw) {
      const parsed = JSON.parse(raw) as Record<string, PermissionDecision>
      if (parsed && typeof parsed === 'object') {
        permissionPointMap.value = parsed
      }
    }
    const menuRaw = window.localStorage.getItem(MENU_ACCESS_CACHE_KEY)
    if (menuRaw) {
      const parsedMenu = JSON.parse(menuRaw) as Record<string, PermissionDecision>
      if (parsedMenu && typeof parsedMenu === 'object') {
        menuAccessMap.value = parsedMenu
      }
    }
  } catch {
    permissionPointMap.value = {}
    menuAccessMap.value = {}
  }
}

const writeCache = (nextPoints: Record<string, PermissionDecision>, nextMenus: Record<string, PermissionDecision>) => {
  permissionPointMap.value = nextPoints
  menuAccessMap.value = nextMenus
  if (typeof window === 'undefined') return
  window.localStorage.setItem(PERMISSION_POINTS_CACHE_KEY, JSON.stringify(nextPoints))
  window.localStorage.setItem(MENU_ACCESS_CACHE_KEY, JSON.stringify(nextMenus))
}

readCache()

export const clearPermissionPointsCache = () => {
  permissionPointMap.value = {}
  menuAccessMap.value = {}
  if (typeof window === 'undefined') return
  window.localStorage.removeItem(PERMISSION_POINTS_CACHE_KEY)
  window.localStorage.removeItem(MENU_ACCESS_CACHE_KEY)
}

export const refreshPermissionPoints = async () => {
  let lastError: unknown = null
  const maxAttempts = 3 // 首次 + 2次重试
  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    const startedAt = performance.now()
    try {
      const data = await getPermissionPointsApi()
      writeCache(normalize(data.points || []), normalizeMenus(data.menus || []))
      writePolicyEventLog({
        stage: 'success',
        attempt,
        duration_ms: Math.round(performance.now() - startedAt),
      })
      return {
        points: permissionPointMap.value,
        menus: menuAccessMap.value,
      }
    } catch (error: any) {
      lastError = error
      const msg = error?.response?.data?.detail || error?.message || 'unknown error'
      const duration = Math.round(performance.now() - startedAt)
      if (attempt < maxAttempts) {
        writePolicyEventLog({
          stage: 'retry',
          attempt,
          duration_ms: duration,
          error: String(msg),
        })
        await sleep(180 * attempt)
        continue
      }
      writePolicyEventLog({
        stage: 'failed',
        attempt,
        duration_ms: duration,
        error: String(msg),
      })
    }
  }
  throw lastError || new Error('权限策略加载失败')
}

export const getPermissionPolicyEventLogs = () => {
  if (typeof window === 'undefined') return [] as Array<Record<string, unknown>>
  try {
    const raw = window.localStorage.getItem(PERMISSION_POLICY_LOG_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

export const clearPermissionPolicyEventLogs = () => {
  if (typeof window === 'undefined') return
  window.localStorage.removeItem(PERMISSION_POLICY_LOG_KEY)
}

export const evaluatePermissionPoint = (point: PermissionPoint): PermissionDecision => {
  const hit = permissionPointMap.value[point]
  if (hit) return hit
  return defaultDenied
}

export const hasPermissionPoint = (point: PermissionPoint) => {
  return evaluatePermissionPoint(point).allowed
}

export const evaluateMenuAccess = (menuKey: string): PermissionDecision => {
  const hit = menuAccessMap.value[menuKey]
  if (hit) return hit
  return defaultDenied
}

export const hasMenuAccessByPolicy = (menuKey: string) => {
  return evaluateMenuAccess(menuKey).allowed
}

export const ensurePermissionPoliciesLoaded = async () => {
  if (Object.keys(permissionPointMap.value).length > 0 && Object.keys(menuAccessMap.value).length > 0) return
  if (!loadPromise) {
    loadPromise = refreshPermissionPoints()
      .then(() => undefined)
      .finally(() => {
        loadPromise = null
      })
  }
  await loadPromise
}

export const hasPermissionPoliciesLoaded = () => {
  return Object.keys(permissionPointMap.value).length > 0 && Object.keys(menuAccessMap.value).length > 0
}
