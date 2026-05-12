import { ElMessageBox } from 'element-plus'

export const UI_TEXT = {
  close: '关闭',
  cancel: '取消',
  save: '保存',
  confirm: '确认',
  submit: '提交',
  dangerousConfirmTitle: '风险操作确认',
}

export const DRAWER_DESKTOP_SIZE = {
  form: '520px',
  compact: '460px',
  assign: '560px',
  detail: '62%',
}

export const getDrawerSize = (isMobile: boolean, desktopSize: string) => (isMobile ? '100%' : desktopSize)

export const buildPositionText = (index: number, total: number) => {
  if (index < 0 || total <= 0) return ''
  return `第 ${index + 1} 条 / 共 ${total} 条`
}

export const confirmDangerousAction = async (message: string, title = UI_TEXT.dangerousConfirmTitle) => {
  await ElMessageBox.confirm(message, title, {
    type: 'warning',
    confirmButtonText: UI_TEXT.confirm,
    cancelButtonText: UI_TEXT.cancel,
  })
}

type DebouncedFn<T extends (...args: any[]) => void> = ((...args: Parameters<T>) => void) & {
  cancel: () => void
}

export const createDebouncedFn = <T extends (...args: any[]) => void>(
  fn: T,
  delay = 300,
): DebouncedFn<T> => {
  let timer: ReturnType<typeof window.setTimeout> | null = null
  const debounced = ((...args: Parameters<T>) => {
    if (timer) window.clearTimeout(timer)
    timer = window.setTimeout(() => {
      fn(...args)
      timer = null
    }, delay)
  }) as DebouncedFn<T>
  debounced.cancel = () => {
    if (!timer) return
    window.clearTimeout(timer)
    timer = null
  }
  return debounced
}
