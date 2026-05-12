const TITLE_EVENT = 'system-settings-updated'

export interface SiteTitlePayload {
  site_name?: string
  site_subtitle?: string
}

export const buildPageTitle = (siteName: string, pageName?: string) => {
  const cleanSite = (siteName || '').trim() || '咨询话术模拟训练系统'
  const cleanPage = (pageName || '').trim()
  return cleanPage ? `${cleanPage} - ${cleanSite}` : cleanSite
}

export const applyPageTitle = (siteName: string, pageName?: string) => {
  if (typeof document === 'undefined') return
  document.title = buildPageTitle(siteName, pageName)
}

export const broadcastSiteTitleUpdate = (payload: SiteTitlePayload) => {
  if (typeof window === 'undefined') return
  window.dispatchEvent(new CustomEvent<SiteTitlePayload>(TITLE_EVENT, { detail: payload }))
}

export const onSiteTitleUpdate = (handler: (payload: SiteTitlePayload) => void) => {
  if (typeof window === 'undefined') return () => {}
  const listener = (event: Event) => {
    const custom = event as CustomEvent<SiteTitlePayload>
    handler(custom.detail || {})
  }
  window.addEventListener(TITLE_EVENT, listener)
  return () => window.removeEventListener(TITLE_EVENT, listener)
}
