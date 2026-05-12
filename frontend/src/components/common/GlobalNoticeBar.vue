<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { consumePendingGlobalNoticeQueue, onGlobalNotice, type GlobalNoticePayload } from '../../utils/globalNotice'

const visible = ref(false)
const title = ref('')
const type = ref<'success' | 'info' | 'warning' | 'error'>('info')
const detail = ref('')
const errorCode = ref('')
const expanded = ref(false)
const noticeQueue = ref<GlobalNoticePayload[]>([])
let dismissTimer: number | null = null
let unbindNotice: (() => void) | null = null

const hideCurrentNotice = () => {
  visible.value = false
  title.value = ''
  detail.value = ''
  errorCode.value = ''
  expanded.value = false
}

const showNotice = (payload: GlobalNoticePayload) => {
  title.value = payload.title
  type.value = payload.type || 'info'
  detail.value = payload.detail || ''
  errorCode.value = payload.errorCode || ''
  expanded.value = false
  visible.value = true
  if (dismissTimer) {
    window.clearTimeout(dismissTimer)
  }
  dismissTimer = window.setTimeout(() => {
    hideCurrentNotice()
    dismissTimer = null
    flushQueue()
  }, payload.duration ?? 3000)
}

const flushQueue = () => {
  if (visible.value) return
  const next = noticeQueue.value.shift()
  if (!next) return
  showNotice(next)
}

const enqueueNotice = (payload: GlobalNoticePayload) => {
  noticeQueue.value.push({
    title: payload.title,
    type: payload.type || 'info',
    duration: payload.duration ?? 3000,
    detail: payload.detail || '',
    errorCode: payload.errorCode || '',
  })
  flushQueue()
}

onMounted(() => {
  consumePendingGlobalNoticeQueue().forEach((payload) => enqueueNotice(payload))
  unbindNotice = onGlobalNotice((payload) => {
    enqueueNotice(payload)
  })
})

onBeforeUnmount(() => {
  if (dismissTimer) {
    window.clearTimeout(dismissTimer)
    dismissTimer = null
  }
  unbindNotice?.()
  unbindNotice = null
})
</script>

<template>
  <transition name="global-notice-slide">
    <div v-if="visible" class="global-notice-wrap">
      <el-alert :type="type" show-icon :closable="false">
        <template #title>
          <div class="notice-title-row">
            <span class="notice-title">{{ title }}</span>
            <div class="notice-actions" v-if="detail || errorCode">
              <el-tag v-if="errorCode" size="small" effect="plain" type="danger">错误码：{{ errorCode }}</el-tag>
              <el-button link size="small" @click="expanded = !expanded">
                {{ expanded ? '收起详情' : '展开详情' }}
              </el-button>
            </div>
          </div>
        </template>
        <div v-if="expanded && (detail || errorCode)" class="notice-detail">
          <div v-if="detail" class="notice-detail-text">{{ detail }}</div>
          <div v-else class="notice-detail-text">暂无更多详情</div>
        </div>
      </el-alert>
    </div>
  </transition>
</template>

<style scoped>
.global-notice-wrap {
  position: fixed;
  top: 10px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 2200;
  width: min(760px, calc(100vw - 24px));
  pointer-events: none;
}

.global-notice-wrap :deep(.el-alert) {
  pointer-events: auto;
  border: 1px solid color-mix(in srgb, var(--ui-border-soft) 68%, transparent 32%);
  box-shadow: 0 10px 24px rgb(0 0 0 / 12%);
}

.notice-title-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
}

.notice-title {
  font-weight: 600;
}

.notice-actions {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.notice-detail {
  margin-top: 8px;
  border-top: 1px dashed color-mix(in srgb, var(--ui-border-soft) 70%, transparent 30%);
  padding-top: 8px;
}

.notice-detail-text {
  font-size: 12px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
}

.global-notice-slide-enter-active,
.global-notice-slide-leave-active {
  transition: all 220ms ease;
}

.global-notice-slide-enter-from,
.global-notice-slide-leave-to {
  opacity: 0;
  transform: translateY(-8px);
}
</style>
