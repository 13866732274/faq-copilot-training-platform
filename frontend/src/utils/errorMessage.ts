const EN_TO_ZH_RULES: Array<[RegExp, string]> = [
  [/not authenticated/i, '登录状态已失效，请重新登录'],
  [/invalid token/i, '登录凭证无效，请重新登录'],
  [/token.*expired/i, '登录已过期，请重新登录'],
  [/permission denied|forbidden/i, '当前账号无权限执行该操作'],
  [/not found/i, '请求资源不存在'],
  [/timeout/i, '请求超时，请稍后重试'],
  [/network error/i, '网络异常，请检查网络连接'],
  [/internal server error/i, '服务器繁忙，请稍后再试'],
  [/service unavailable/i, '服务暂不可用，请稍后重试'],
  [/bad request/i, '请求参数有误'],
  [/unauthorized/i, '用户名或密码错误'],
  [/too many requests/i, '请求过于频繁，请稍后再试'],
]

export const toChineseErrorMessage = (raw?: unknown, fallback = '请求失败，请稍后重试') => {
  if (typeof raw !== 'string') return fallback
  const text = raw.trim()
  if (!text) return fallback
  for (const [rule, zh] of EN_TO_ZH_RULES) {
    if (rule.test(text)) return zh
  }
  return text
}
