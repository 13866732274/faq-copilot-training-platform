export type ThemeMode = 'system' | 'light' | 'dark'

const THEME_KEY = 'chattrainer-theme-mode'

const mediaQuery = () => window.matchMedia('(prefers-color-scheme: dark)')

const resolveMode = (mode: ThemeMode) => {
  if (mode === 'system') {
    return mediaQuery().matches ? 'dark' : 'light'
  }
  return mode
}

export const getThemeMode = (): ThemeMode => {
  const value = localStorage.getItem(THEME_KEY) as ThemeMode | null
  if (value === 'light' || value === 'dark' || value === 'system') return value
  return 'system'
}

export const applyThemeMode = (mode: ThemeMode) => {
  const resolved = resolveMode(mode)
  document.documentElement.classList.toggle('dark', resolved === 'dark')
}

export const setThemeMode = (mode: ThemeMode) => {
  localStorage.setItem(THEME_KEY, mode)
  applyThemeMode(mode)
}

export const initTheme = () => {
  const mode = getThemeMode()
  applyThemeMode(mode)
  const mq = mediaQuery()
  const handler = () => {
    if (getThemeMode() === 'system') applyThemeMode('system')
  }
  mq.addEventListener('change', handler)
}

