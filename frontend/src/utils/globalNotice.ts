export type GlobalNoticeType = 'success' | 'info' | 'warning' | 'error'

export interface GlobalNoticePayload {
  title: string
  type?: GlobalNoticeType
  duration?: number
  detail?: string
  errorCode?: string
}

interface GlobalNoticeOptions {
  persistForNextLoad?: boolean
  dedupeMs?: number
  skipDedupe?: boolean
}

const GLOBAL_NOTICE_EVENT = 'global-notice-event'
const GLOBAL_NOTICE_STORAGE_KEY = 'global-notice-pending'
const DEFAULT_DEDUPE_MS = 3000
const DEDUPE_CACHE_TTL_MS = 60 * 1000
const noticeDedupeCache = new Map<string, number>()

const buildNoticeDedupeKey = (payload: GlobalNoticePayload) => {
  const title = payload.title.trim()
  const type = payload.type || 'info'
  const errorCode = (payload.errorCode || '').trim()
  const detail = (payload.detail || '').trim()
  const normalizedDetail = detail.length > 120 ? detail.slice(0, 120) : detail
  return `${type}::${title}::${errorCode}::${normalizedDetail}`
}

const shouldSuppressDuplicate = (payload: GlobalNoticePayload, options?: GlobalNoticeOptions) => {
  if (options?.skipDedupe) return false
  const dedupeMs = typeof options?.dedupeMs === 'number' ? Math.max(0, options.dedupeMs) : DEFAULT_DEDUPE_MS
  if (dedupeMs <= 0) return false
  const now = Date.now()
  const key = buildNoticeDedupeKey(payload)
  const lastAt = noticeDedupeCache.get(key) || 0
  if (now - lastAt < dedupeMs) return true
  noticeDedupeCache.set(key, now)
  // Cleanup stale keys to keep cache bounded.
  for (const [cacheKey, cacheAt] of noticeDedupeCache.entries()) {
    if (now - cacheAt > DEDUPE_CACHE_TTL_MS) {
      noticeDedupeCache.delete(cacheKey)
    }
  }
  return false
}

export const pushGlobalNotice = (
  payload: GlobalNoticePayload,
  options?: GlobalNoticeOptions,
) => {
  if (typeof window === 'undefined') return
  const normalized: GlobalNoticePayload = {
    title: payload.title,
    type: payload.type || 'info',
    duration: typeof payload.duration === 'number' ? payload.duration : 3000,
    detail: payload.detail || '',
    errorCode: payload.errorCode || '',
  }
  if (shouldSuppressDuplicate(normalized, options)) return
  if (options?.persistForNextLoad) {
    window.sessionStorage.setItem(GLOBAL_NOTICE_STORAGE_KEY, JSON.stringify(normalized))
  }
  window.dispatchEvent(new CustomEvent<GlobalNoticePayload>(GLOBAL_NOTICE_EVENT, { detail: normalized }))
}

export const onGlobalNotice = (handler: (payload: GlobalNoticePayload) => void) => {
  if (typeof window === 'undefined') return () => {}
  const listener = (event: Event) => {
    const payload = (event as CustomEvent<GlobalNoticePayload>).detail
    if (payload?.title) handler(payload)
  }
  window.addEventListener(GLOBAL_NOTICE_EVENT, listener)
  return () => window.removeEventListener(GLOBAL_NOTICE_EVENT, listener)
}

export const consumePendingGlobalNotice = (): GlobalNoticePayload | null => {
  if (typeof window === 'undefined') return null
  try {
    const raw = window.sessionStorage.getItem(GLOBAL_NOTICE_STORAGE_KEY)
    if (!raw) return null
    window.sessionStorage.removeItem(GLOBAL_NOTICE_STORAGE_KEY)
    const parsed = JSON.parse(raw) as GlobalNoticePayload
    if (!parsed?.title) return null
    return {
      title: parsed.title,
      type: parsed.type || 'info',
      duration: typeof parsed.duration === 'number' ? parsed.duration : 3000,
      detail: parsed.detail || '',
      errorCode: parsed.errorCode || '',
    }
  } catch {
    window.sessionStorage.removeItem(GLOBAL_NOTICE_STORAGE_KEY)
    return null
  }
}

export const consumePendingGlobalNoticeQueue = (): GlobalNoticePayload[] => {
  const first = consumePendingGlobalNotice()
  return first ? [first] : []
}
