<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import MessageContent from '../../components/chat/MessageContent.vue'
import {
  completePractice,
  getPracticeHistory,
  nextPractice,
  replyPractice,
  type NextData,
  type PracticeMessage,
} from '../../api/practice'

const route = useRoute()
const router = useRouter()
const practiceId = Number(route.params.id)
const resumed = String(route.query.resume || '') === '1'

type TimelineMessage = PracticeMessage & {
  side: 'left' | 'right'
  timeMs: number
  minuteKey: string
  timeText: string
  dateKey: string
  dateLabel: string
  unreadLabel?: string
}

const loading = ref(false)
const sending = ref(false)
const input = ref('')
const current = ref<NextData | null>(null)
const timeline = ref<TimelineMessage[]>([])
const finished = ref(false)
const completedPersisted = ref(false)
const completing = ref(false)
const chatPanelRef = ref<HTMLElement | null>(null)
const unreadDividerShown = ref(false)
const hasHistory = ref(false)
const resumeAnchorIndex = ref<number | null>(null)
let lastTimelineMs = Date.now() - 15_000

const canSend = computed(() => !!current.value?.need_reply && !!current.value.reply_to_message_id)
const hintText = computed(() => {
  if (finished.value) return '全部对话已结束，可提交并查看答案对比。'
  if (canSend.value) return '请根据上方患者问题回复咨询话术。'
  return '系统正在加载下一批患者消息...'
})
const startTip = '对话开始：请根据患者消息进行咨询回复'
const resumeTip = '已恢复到你上次未完成的进度，可继续作答'
const endTip = computed(() =>
  finished.value ? '对话结束：本轮已无后续患者消息，可点击“完成练习，查看答案”' : '',
)

const toDateKey = (date: Date) => {
  const y = date.getFullYear()
  const m = String(date.getMonth() + 1).padStart(2, '0')
  const d = String(date.getDate()).padStart(2, '0')
  return `${y}-${m}-${d}`
}

const toDateLabel = (date: Date) => {
  const today = new Date()
  const yesterday = new Date()
  yesterday.setDate(today.getDate() - 1)
  const key = toDateKey(date)
  if (key === toDateKey(today)) return '今天'
  if (key === toDateKey(yesterday)) return '昨天'
  return `${date.getMonth() + 1}月${date.getDate()}日`
}

const showDateAt = (idx: number) => {
  if (idx === 0) return true
  const curr = timeline.value[idx]
  const prev = timeline.value[idx - 1]
  if (!curr || !prev) return false
  return curr.dateKey !== prev.dateKey
}

const showTimeAt = (idx: number) => {
  if (idx === 0) return true
  const curr = timeline.value[idx]
  const prev = timeline.value[idx - 1]
  if (!curr || !prev) return false
  if (curr.dateKey !== prev.dateKey) return true
  return curr.minuteKey !== prev.minuteKey
}

const toTimeText = (date: Date) => {
  const h = String(date.getHours()).padStart(2, '0')
  const m = String(date.getMinutes()).padStart(2, '0')
  return `${h}:${m}`
}

const toMinuteKey = (date: Date) => `${toDateKey(date)} ${toTimeText(date)}`

const allocateTimelineMs = (stepSeconds = 18) => {
  const now = Date.now()
  lastTimelineMs = Math.max(lastTimelineMs + stepSeconds * 1000, now)
  return lastTimelineMs
}

const createTimelineMessage = (
  message: PracticeMessage,
  side: 'left' | 'right',
  options?: { unreadLabel?: string; stepSeconds?: number },
): TimelineMessage => {
  const date = new Date(allocateTimelineMs(options?.stepSeconds))
  return {
    ...message,
    side,
    timeMs: date.getTime(),
    minuteKey: toMinuteKey(date),
    timeText: toTimeText(date),
    dateKey: toDateKey(date),
    dateLabel: toDateLabel(date),
    unreadLabel: options?.unreadLabel,
  }
}

const isGroupedWithPrev = (idx: number) => {
  if (idx === 0) return false
  const curr = timeline.value[idx]
  const prev = timeline.value[idx - 1]
  if (!curr || !prev) return false
  if (curr.side !== prev.side || curr.dateKey !== prev.dateKey) return false
  return !showTimeAt(idx)
}

const scrollToBottom = async () => {
  await nextTick()
  const el = chatPanelRef.value
  if (el) el.scrollTop = el.scrollHeight
}

const scrollToResumeAnchor = async () => {
  await nextTick()
  const panel = chatPanelRef.value
  if (!panel) return
  const anchor = panel.querySelector('[data-resume-anchor="1"]') as HTMLElement | null
  if (!anchor) return
  panel.scrollTop = Math.max(anchor.offsetTop - panel.clientHeight * 0.22, 0)
}

const loadHistory = async () => {
  const history = await getPracticeHistory(practiceId)
  hasHistory.value = history.messages.length > 0
  history.messages.forEach((m) => {
    timeline.value.push(
      createTimelineMessage(m, m.role === 'student' ? 'right' : 'left', {
        stepSeconds: m.role === 'student' ? 10 : 18,
      }),
    )
  })
}

const loadNext = async (markUnread = false) => {
  loading.value = true
  try {
    const data = await nextPractice(practiceId)
    current.value = data
    if (resumed && hasHistory.value && resumeAnchorIndex.value === null && data.messages.length > 0) {
      resumeAnchorIndex.value = timeline.value.length
    }
    data.messages.forEach((m, idx) => {
      const shouldShowUnread = markUnread && idx === 0 && !unreadDividerShown.value
      timeline.value.push(
        createTimelineMessage(m, 'left', {
          unreadLabel: shouldShowUnread ? '以下为新消息' : undefined,
        }),
      )
      if (shouldShowUnread) unreadDividerShown.value = true
    })
    await scrollToBottom()
    if (!data.need_reply && data.is_last) {
      finished.value = true
      await persistCompletion()
    }
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || '加载下一轮消息失败')
  } finally {
    loading.value = false
  }
}

const persistCompletion = async () => {
  if (completedPersisted.value || completing.value) return
  completing.value = true
  try {
    await completePractice(practiceId)
    completedPersisted.value = true
  } catch (error: any) {
    ElMessage.warning(error?.response?.data?.detail || '已结束，但完成状态保存失败，请点击下方按钮重试')
  } finally {
    completing.value = false
  }
}

const sendReply = async () => {
  if (sending.value) return
  if (!canSend.value) return
  const content = input.value.trim()
  if (!content) {
    ElMessage.warning('请输入回复内容')
    return
  }
  sending.value = true
  try {
    await replyPractice(practiceId, Number(current.value?.reply_to_message_id), content)
    timeline.value.push(
      createTimelineMessage(
        {
      id: Date.now(),
      role: 'student',
      content_type: 'text',
      content,
      sender_name: '我',
      original_time: '',
        },
        'right',
        { stepSeconds: 10 },
      ),
    )
    input.value = ''
    await scrollToBottom()
    await loadNext(true)
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || '提交回复失败')
  } finally {
    sending.value = false
  }
}

const onInputKeydown = (e: KeyboardEvent) => {
  if (e.key !== 'Enter') return
  if (e.ctrlKey) {
    const target = e.target as HTMLTextAreaElement
    const start = target.selectionStart
    const end = target.selectionEnd
    const next = `${input.value.slice(0, start)}\n${input.value.slice(end)}`
    input.value = next
    nextTick(() => {
      target.selectionStart = target.selectionEnd = start + 1
    })
    e.preventDefault()
    return
  }
  e.preventDefault()
  sendReply()
}

const completeAndReview = async () => {
  try {
    await persistCompletion()
    if (!completedPersisted.value) return
    router.push(`/practice/${practiceId}/review`)
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || '完成练习失败')
  }
}

onMounted(async () => {
  await loadHistory()
  await loadNext()
  if (resumed && hasHistory.value) {
    await scrollToResumeAnchor()
  }
})
</script>

<template>
  <el-card shadow="never" v-loading="loading">
    <template #header>
      <div style="display: flex; justify-content: space-between; align-items: center">
        <strong>对话模拟训练</strong>
        <el-button @click="router.push('/practice')">返回案例列表</el-button>
      </div>
    </template>

    <div class="chat-tip">{{ hintText }}</div>
    <div class="chat-panel" ref="chatPanelRef">
      <div class="edge-tip start">{{ startTip }}</div>
      <div v-if="resumed" class="edge-tip resume">{{ resumeTip }}</div>
      <div
        v-for="(msg, idx) in timeline"
        :key="`${msg.id}-${idx}`"
        class="message-block"
      >
        <div
          v-if="resumed && hasHistory && resumeAnchorIndex === idx"
          class="resume-anchor"
          data-resume-anchor="1"
        >
          <span>从这里继续</span>
        </div>
        <div v-if="showDateAt(idx)" class="date-divider">{{ msg.dateLabel }}</div>
        <div v-if="msg.unreadLabel" class="unread-divider">
          <span>{{ msg.unreadLabel }}</span>
        </div>
        <div v-if="showTimeAt(idx)" class="time-divider">{{ msg.timeText }}</div>
        <div class="row" :class="[msg.side, { grouped: isGroupedWithPrev(idx) }]">
          <div class="avatar" :class="[msg.side, { compact: isGroupedWithPrev(idx) }]">
            {{ msg.side === 'left' ? '患' : '我' }}
          </div>
          <div class="bubble-wrap" :class="msg.side">
            <div v-if="!isGroupedWithPrev(idx)" class="name">
              {{ msg.sender_name || (msg.side === 'left' ? '患者' : '我') }}
            </div>
            <div class="bubble" :class="msg.side">
              <MessageContent :content-type="msg.content_type" :content="msg.content" />
            </div>
          </div>
        </div>
      </div>
      <div v-if="endTip" class="edge-tip end">{{ endTip }}</div>
      <transition name="send-fade">
        <div v-if="sending" class="row right sending-row">
          <div class="avatar right">我</div>
          <div class="bubble-wrap right">
            <div class="bubble right sending-bubble">
              <span class="dot" />
              <span class="dot" />
              <span class="dot" />
            </div>
          </div>
        </div>
      </transition>
    </div>

    <div v-if="!finished" class="input-bar">
      <el-input
        v-model="input"
        type="textarea"
        :autosize="{ minRows: 2, maxRows: 6 }"
        maxlength="500"
        placeholder="请输入规范、严谨的文本回复..."
        @keydown="onInputKeydown"
      />
      <div class="input-actions">
        <div class="tip">回车发送，Ctrl+回车换行</div>
        <el-button type="primary" :loading="sending" :disabled="!canSend" @click="sendReply">发送回复</el-button>
      </div>
    </div>

    <div v-else class="input-bar">
      <el-button type="success" :loading="completing" @click="completeAndReview">完成练习，查看答案</el-button>
    </div>
  </el-card>
</template>

<style scoped>
.chat-tip {
  margin-bottom: var(--space-2);
  color: var(--el-text-color-secondary);
  font-size: var(--font-size-sm);
}

.chat-panel {
  --chat-panel-bg: #eaeaea;
  --chat-text-secondary: #606266;
  --chat-time-text: #8f949c;
  --chat-left-bg: #fff;
  --chat-left-border: #dbdbdb;
  --chat-right-bg: #8fe064;
  --chat-right-text: #17331c;
  --chat-avatar-left: #8d97a5;
  --chat-avatar-right: #5abf40;
  --chat-anchor-text: #1f8f37;
  --chat-anchor-bg: #e4f7e3;
  --chat-anchor-border: #b7e6b3;
  --chat-anchor-shadow: rgb(33 152 78 / 15%);
  --chat-unread-text: #3a8f2e;
  --chat-unread-bg: #dff3d7;

  min-height: 420px;
  max-height: 520px;
  overflow: auto;
  background: var(--chat-panel-bg);
  border-radius: var(--radius-sm);
  padding: var(--space-4) var(--space-3);
}

.message-block {
  margin-bottom: 10px;
}

.edge-tip {
  width: 100%;
  text-align: center;
  font-size: var(--font-size-xs);
  color: var(--chat-text-secondary);
  margin: 2px 0 var(--space-2);
}

.resume-anchor {
  width: 100%;
  text-align: center;
  margin: 6px 0 8px;
}

.resume-anchor span {
  display: inline-block;
  padding: 2px 10px;
  border-radius: var(--radius-md);
  font-size: var(--font-size-xs);
  color: var(--chat-anchor-text);
  background: var(--chat-anchor-bg);
  border: 1px solid var(--chat-anchor-border);
  box-shadow: 0 0 0 2px var(--chat-anchor-shadow);
}

.row {
  display: flex;
  margin-bottom: 0;
  align-items: flex-start;
  gap: var(--space-2);
}

.row.grouped {
  margin-top: -6px;
}

.row.left {
  justify-content: flex-start;
}

.row.right {
  justify-content: flex-start;
  flex-direction: row-reverse;
}

.time-divider {
  width: 100%;
  text-align: center;
  font-size: 11px;
  color: var(--chat-time-text);
  margin: 2px 0 6px;
}

.date-divider {
  width: 100%;
  text-align: center;
  font-size: 11px;
  color: var(--chat-text-secondary);
  margin: 6px 0 4px;
}

.unread-divider {
  width: 100%;
  text-align: center;
  margin: 6px 0;
}

.unread-divider span {
  display: inline-block;
  padding: 1px var(--space-2);
  border-radius: 10px;
  font-size: var(--font-size-xs);
  color: var(--chat-unread-text);
  background: var(--chat-unread-bg);
}

.avatar {
  width: 36px;
  height: 36px;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: var(--font-size-sm);
  color: #fff;
  box-shadow: 0 1px 2px rgb(0 0 0 / 10%);
}

.avatar.compact {
  visibility: hidden;
}

.avatar.left {
  background: var(--chat-avatar-left);
}

.avatar.right {
  background: var(--chat-avatar-right);
}

.bubble-wrap {
  max-width: 70%;
}

.bubble {
  padding: 10px 11px;
  border-radius: 6px;
  word-break: break-word;
  position: relative;
  line-height: var(--line-height-base);
  font-size: var(--font-size-body);
  box-shadow: 0 1px 2px rgb(0 0 0 / 6%);
}

.bubble.left {
  background: var(--chat-left-bg);
  border: 1px solid var(--chat-left-border);
  color: var(--el-text-color-primary);
}

.bubble.right {
  background: var(--chat-right-bg);
  color: var(--chat-right-text);
}

.bubble.left::before {
  content: '';
  position: absolute;
  left: -6px;
  top: 10px;
  border-top: 6px solid transparent;
  border-bottom: 6px solid transparent;
  border-right: 6px solid var(--chat-left-bg);
}

.bubble.right::before {
  content: '';
  position: absolute;
  right: -6px;
  top: 10px;
  border-top: 6px solid transparent;
  border-bottom: 6px solid transparent;
  border-left: 6px solid var(--chat-right-bg);
}

.sending-row {
  margin-top: 2px;
}

.sending-bubble {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  min-width: 44px;
}

.dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: rgb(0 0 0 / 36%);
  animation: pulse 1.15s infinite ease-in-out;
}

.dot:nth-child(2) {
  animation-delay: 0.12s;
}

.dot:nth-child(3) {
  animation-delay: 0.24s;
}

@keyframes pulse {
  0%,
  100% {
    transform: scale(0.9);
    opacity: 0.45;
  }
  50% {
    transform: scale(1);
    opacity: 0.9;
  }
}

.send-fade-enter-active,
.send-fade-leave-active {
  transition: all 0.2s ease;
}

.send-fade-enter-from,
.send-fade-leave-to {
  opacity: 0;
  transform: translateY(4px);
}

.name {
  font-size: var(--font-size-sm);
  color: var(--chat-text-secondary);
  margin-bottom: 3px;
}

.bubble-wrap.right .name {
  text-align: right;
}

.input-bar {
  margin-top: var(--space-3);
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.input-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--space-2);
}

.tip {
  font-size: var(--font-size-xs);
  color: var(--chat-time-text);
  text-align: right;
}

:global(.dark) .chat-panel {
  --chat-panel-bg: #1b1d21;
  --chat-text-secondary: #d1d5dc;
  --chat-time-text: #969ba3;
  --chat-left-bg: #2a2f36;
  --chat-left-border: #404751;
  --chat-right-bg: #2f965a;
  --chat-right-text: #f4fff6;
  --chat-avatar-left: #6e7683;
  --chat-avatar-right: #2da562;
  --chat-anchor-text: #caf6d8;
  --chat-anchor-bg: #214234;
  --chat-anchor-border: #376c52;
  --chat-anchor-shadow: rgb(21 204 102 / 20%);
  --chat-unread-text: #caf6d8;
  --chat-unread-bg: #294e3c;
}

:global(.dark) .chat-panel .bubble {
  box-shadow: 0 1px 2px rgb(0 0 0 / 20%);
}

:global(.dark) .dot {
  background: rgb(231 238 245 / 42%);
  animation-duration: 1.55s;
}

:deep(.input-bar .el-textarea__inner) {
  line-height: 1.52;
}

:global(.dark) :deep(.input-bar .el-textarea__inner) {
  color: #e5eaf3;
}

:global(.dark) :deep(.input-bar .el-input__count-inner) {
  color: #9aa1aa;
}

@media (max-width: 768px) {
  .chat-panel {
    min-height: 52vh;
    max-height: 60vh;
    padding: 10px 8px;
  }

  .bubble-wrap {
    max-width: 82%;
  }

  .avatar {
    width: 30px;
    height: 30px;
    font-size: 12px;
  }

  .input-actions {
    flex-direction: column;
    align-items: stretch;
  }

  .tip {
    text-align: left;
  }
}
</style>
