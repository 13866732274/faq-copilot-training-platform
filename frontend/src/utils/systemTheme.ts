export const applyRuntimeBrandAccent = (brandAccent?: string | null) => {
  const color = (brandAccent || '').trim()
  if (!color || typeof document === 'undefined') return
  document.documentElement.style.setProperty('--brand-accent', color)
}

const hexColorRe = /^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/
const rgbColorRe = /^rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})(?:\s*,\s*(0|1|0?\.\d+))?\s*\)$/i

export const normalizeBrandAccent = (raw: string): string | null => {
  const input = (raw || '').trim()
  if (!input) return null
  if (hexColorRe.test(input)) {
    if (input.length === 4) {
      const r = input[1]
      const g = input[2]
      const b = input[3]
      return `#${r}${r}${g}${g}${b}${b}`.toLowerCase()
    }
    return input.toLowerCase()
  }
  const match = input.match(rgbColorRe)
  if (!match) return null
  const channels = [Number(match[1]), Number(match[2]), Number(match[3])]
  if (channels.some((v) => !Number.isFinite(v) || v < 0 || v > 255)) return null
  return `#${channels.map((v) => v.toString(16).padStart(2, '0')).join('')}`
}
