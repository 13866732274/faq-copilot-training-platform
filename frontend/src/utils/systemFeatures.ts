export interface SystemFeatureFlags {
  enable_export_center: boolean
  enable_audit_enhanced: boolean
  enable_ai_scoring: boolean
}

interface CachedFeatureFlags extends SystemFeatureFlags {
  updated_at: number
}

const FEATURE_STORAGE_KEY = 'system-feature-flags-cache'
const FEATURE_EVENT = 'system-feature-flags-updated'
const CACHE_TTL_MS = 5 * 60 * 1000

const DEFAULT_FLAGS: SystemFeatureFlags = {
  enable_export_center: true,
  enable_audit_enhanced: true,
  enable_ai_scoring: false,
}

export const toFeatureFlags = (value: Partial<SystemFeatureFlags> | null | undefined): SystemFeatureFlags => ({
  enable_export_center: Boolean(value?.enable_export_center ?? DEFAULT_FLAGS.enable_export_center),
  enable_audit_enhanced: Boolean(value?.enable_audit_enhanced ?? DEFAULT_FLAGS.enable_audit_enhanced),
  enable_ai_scoring: Boolean(value?.enable_ai_scoring ?? DEFAULT_FLAGS.enable_ai_scoring),
})

export const readFeatureFlagsCache = (): SystemFeatureFlags | null => {
  if (typeof window === 'undefined') return null
  try {
    const raw = window.localStorage.getItem(FEATURE_STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as CachedFeatureFlags
    if (!parsed || typeof parsed !== 'object') return null
    if (!parsed.updated_at || Date.now() - parsed.updated_at > CACHE_TTL_MS) return null
    return toFeatureFlags(parsed)
  } catch {
    return null
  }
}

export const writeFeatureFlagsCache = (flags: Partial<SystemFeatureFlags>) => {
  if (typeof window === 'undefined') return
  const normalized = toFeatureFlags(flags)
  const payload: CachedFeatureFlags = {
    ...normalized,
    updated_at: Date.now(),
  }
  window.localStorage.setItem(FEATURE_STORAGE_KEY, JSON.stringify(payload))
}

export const clearFeatureFlagsCache = () => {
  if (typeof window === 'undefined') return
  window.localStorage.removeItem(FEATURE_STORAGE_KEY)
}

export const broadcastFeatureFlagsUpdate = (flags: Partial<SystemFeatureFlags>) => {
  if (typeof window === 'undefined') return
  const normalized = toFeatureFlags(flags)
  window.dispatchEvent(new CustomEvent<SystemFeatureFlags>(FEATURE_EVENT, { detail: normalized }))
}

export const onFeatureFlagsUpdate = (handler: (flags: SystemFeatureFlags) => void) => {
  if (typeof window === 'undefined') return () => {}
  const listener = (event: Event) => {
    const detail = (event as CustomEvent<SystemFeatureFlags>).detail
    handler(toFeatureFlags(detail))
  }
  window.addEventListener(FEATURE_EVENT, listener)
  return () => window.removeEventListener(FEATURE_EVENT, listener)
}

export const isFeatureMenuEnabled = (menuKey: string, flags: SystemFeatureFlags | null | undefined): boolean => {
  if (!flags) return true
  if (menuKey === 'export-center') return flags.enable_export_center
  if (menuKey === 'audit-logs') return flags.enable_audit_enhanced
  return true
}
