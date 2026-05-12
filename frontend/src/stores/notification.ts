import { defineStore } from 'pinia'

export type NoticeType = 'success' | 'warning' | 'error' | 'info'
export type NoticeModule = 'all' | 'import' | 'user' | 'audit' | 'system'

export interface NoticeItem {
  id: string
  type: NoticeType
  module: Exclude<NoticeModule, 'all'>
  title: string
  message?: string
  path?: string
  query?: Record<string, string>
  created_at: string
}

const STORAGE_KEY = 'admin-notification-center'

export const useNotificationStore = defineStore('notification', {
  state: () => ({
    unread: 0,
    items: [] as NoticeItem[],
  }),
  actions: {
    load() {
      if (typeof window === 'undefined') return
      try {
        const raw = window.localStorage.getItem(STORAGE_KEY)
        if (!raw) return
        const parsed = JSON.parse(raw) as { unread: number; items: NoticeItem[] }
        this.unread = Number(parsed?.unread || 0)
        this.items = Array.isArray(parsed?.items) ? parsed.items : []
      } catch {
        this.unread = 0
        this.items = []
      }
    },
    save() {
      if (typeof window === 'undefined') return
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ unread: this.unread, items: this.items }))
    },
    push(input: {
      type?: NoticeType
      module?: Exclude<NoticeModule, 'all'>
      title: string
      message?: string
      path?: string
      query?: Record<string, string>
    }) {
      const item: NoticeItem = {
        id: `${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
        type: input.type || 'info',
        module: input.module || 'system',
        title: input.title,
        message: input.message || '',
        path: input.path,
        query: input.query,
        created_at: new Date().toISOString(),
      }
      this.items = [item, ...this.items].slice(0, 50)
      this.unread += 1
      this.save()
    },
    markAllRead() {
      this.unread = 0
      this.save()
    },
    clear() {
      this.items = []
      this.unread = 0
      this.save()
    },
  },
})
