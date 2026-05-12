<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getMyRecordDetail, type RecordDetailData } from '../../api/records'
import { addPracticeComment, deletePracticeComment, updatePracticeComment } from '../../api/stats'
import { useUserStore } from '../../stores/user'
import PracticeComparePanel from '../../components/practice/PracticeComparePanel.vue'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
const practiceId = Number(route.params.id)
const loading = ref(false)
const detail = ref<RecordDetailData | null>(null)
const commentText = ref('')
const commentSubmitting = ref(false)
const commentUpdating = ref(false)
const commentRemoving = ref(false)
const nowTick = ref(Date.now())
let metricTimer: number | null = null

const getLatestTime = (times: Array<string | null | undefined>) => {
  const valid = times.map((item) => item?.trim()).filter((item): item is string => !!item)
  if (!valid.length) return '--'
  const first = valid[0] || ''
  let latestText = first
  let latestValue = Number.isNaN(Date.parse(first)) ? -1 : Date.parse(first)
  valid.slice(1).forEach((item) => {
    const parsed = Date.parse(item)
    if (!Number.isNaN(parsed) && parsed >= latestValue) {
      latestValue = parsed
      latestText = item
      return
    }
    if (latestValue < 0) latestText = item
  })
  return latestText
}

const metricRounds = computed(() => detail.value?.dialogues.length || 0)
const metricComments = computed(() => detail.value?.comments.length || 0)
const metricRecentUpdateRaw = computed(() => {
  return getLatestTime([
    ...(detail.value?.comments || []).map((item) => item.created_at),
    ...(detail.value?.dialogues || []).map((round) => round.student_reply?.reply_time),
  ])
})

const formatExactTime = (input: string) => {
  if (!input || input === '--') return '--'
  const date = new Date(input)
  if (Number.isNaN(date.getTime())) return input
  const pad = (num: number) => String(num).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
}

const formatRelativeTime = (input: string, nowMs: number) => {
  if (!input || input === '--') return '--'
  const targetMs = Date.parse(input)
  if (Number.isNaN(targetMs)) return input
  const diffSec = Math.max(0, Math.floor((nowMs - targetMs) / 1000))
  if (diffSec < 60) return `${diffSec} 秒前`
  const diffMin = Math.floor(diffSec / 60)
  if (diffMin < 60) return `${diffMin} 分钟前`
  const diffHour = Math.floor(diffMin / 60)
  if (diffHour < 24) return `${diffHour} 小时前`
  const diffDay = Math.floor(diffHour / 24)
  return `${diffDay} 天前`
}

const metricRecentUpdateRelative = computed(() => formatRelativeTime(metricRecentUpdateRaw.value, nowTick.value))
const metricRecentUpdateExact = computed(() => formatExactTime(metricRecentUpdateRaw.value))

const isAdmin = () => {
  const role = userStore.user?.role
  return role === 'admin' || role === 'super_admin'
}

const load = async () => {
  loading.value = true
  try {
    detail.value = await getMyRecordDetail(practiceId)
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || '获取详情失败')
  } finally {
    loading.value = false
  }
}

const submitComment = async () => {
  if (commentSubmitting.value) return
  if (!commentText.value.trim()) return
  commentSubmitting.value = true
  try {
    await addPracticeComment(practiceId, commentText.value.trim())
    commentText.value = ''
    ElMessage.success('点评已添加')
    await load()
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || '添加点评失败')
  } finally {
    commentSubmitting.value = false
  }
}

const editComment = async (commentId: number, oldContent: string) => {
  if (commentUpdating.value) return
  try {
    const { value } = await ElMessageBox.prompt('修改点评内容', '编辑点评', {
      inputValue: oldContent,
      confirmButtonText: '保存',
      cancelButtonText: '取消',
    })
    commentUpdating.value = true
    await updatePracticeComment(commentId, value)
    ElMessage.success('点评已更新')
    await load()
  } catch (error: any) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(error?.response?.data?.detail || '编辑点评失败')
  } finally {
    commentUpdating.value = false
  }
}

const removeComment = async (commentId: number) => {
  if (commentRemoving.value) return
  try {
    await ElMessageBox.confirm('确认删除该点评？', '提示', { type: 'warning' })
    commentRemoving.value = true
    await deletePracticeComment(commentId)
    ElMessage.success('点评已删除')
    await load()
  } catch (error: any) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(error?.response?.data?.detail || '删除点评失败')
  } finally {
    commentRemoving.value = false
  }
}

onMounted(() => {
  load()
  metricTimer = window.setInterval(() => {
    nowTick.value = Date.now()
  }, 60 * 1000)
})

onBeforeUnmount(() => {
  if (metricTimer) {
    window.clearInterval(metricTimer)
    metricTimer = null
  }
})
</script>

<template>
  <el-card shadow="never" v-loading="loading" class="result-page-card">
    <template #header>
      <div class="result-header">
        <div class="result-header-content">
          <div class="result-header-main">
            <span class="result-badge">训练结果</span>
            <strong class="result-title">{{ detail?.quiz_title || '' }}</strong>
          </div>
          <div class="result-metrics">
            <span class="metric-item">对话轮次 {{ metricRounds }}</span>
            <span class="metric-item">点评数 {{ metricComments }}</span>
            <el-tooltip v-if="metricRecentUpdateRaw !== '--'" :content="metricRecentUpdateExact" placement="top">
              <span class="metric-item metric-item-time">最近更新时间 {{ metricRecentUpdateRelative }}</span>
            </el-tooltip>
            <span v-else class="metric-item">最近更新时间 --</span>
          </div>
        </div>
        <div class="header-ops">
          <el-button class="result-back-btn" @click="router.push('/records')">返回列表</el-button>
        </div>
      </div>
    </template>

    <div v-if="detail">
      <PracticeComparePanel :dialogues="detail.dialogues" />

      <el-card shadow="never" class="comment-card">
        <template #header>
          <div class="comment-card-header">
            <span>管理员点评</span>
            <span class="comment-total">共 {{ detail.comments.length }} 条</span>
          </div>
        </template>
        <el-empty v-if="!detail.comments.length" description="暂无点评" />
        <div v-for="item in detail.comments" :key="item.comment_id" class="comment-item">
          <div class="comment-meta">
            <strong class="comment-admin">{{ item.admin_name }}</strong>
            <span class="comment-time">{{ item.created_at }}</span>
          </div>
          <div class="comment-line">
            <div class="comment-content">{{ item.content }}</div>
            <div v-if="isAdmin()" class="comment-actions">
              <el-button link type="primary" @click="editComment(item.comment_id, item.content)">编辑</el-button>
              <el-button link type="danger" @click="removeComment(item.comment_id)">删除</el-button>
            </div>
          </div>
        </div>
      </el-card>

      <el-card v-if="isAdmin()" shadow="never" class="comment-card add-comment-card">
        <template #header>添加点评</template>
        <el-input v-model="commentText" type="textarea" :rows="3" placeholder="输入点评内容" />
        <div class="comment-submit-wrap">
          <el-button type="primary" :loading="commentSubmitting" @click="submitComment">提交点评</el-button>
        </div>
      </el-card>
    </div>
  </el-card>
</template>

<style scoped>
.result-page-card {
  --result-head-bg: linear-gradient(
    150deg,
    color-mix(in srgb, var(--ui-surface-1) 88%, #fff 12%) 0%,
    color-mix(in srgb, var(--ui-surface-2) 90%, #fff 10%) 100%
  );
  --result-head-border: var(--ui-border-soft);
  --result-chip-bg: color-mix(in srgb, var(--el-color-primary-light-9) 76%, transparent 24%);
  --result-chip-border: color-mix(in srgb, var(--el-color-primary-light-6) 50%, var(--ui-border-soft) 50%);
  --result-comment-bg: color-mix(in srgb, var(--ui-surface-1) 94%, #fff 6%);
  --result-comment-border: var(--ui-border-soft);
}

.result-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--space-3);
  border: 1px solid var(--result-head-border);
  border-radius: var(--radius-md);
  padding: 10px var(--space-3);
  background: var(--result-head-bg);
  box-shadow: var(--ui-shadow-soft);
}

.result-header-content {
  min-width: 0;
  display: grid;
  gap: var(--space-2);
}

.result-header-main {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 10px;
}

.result-badge {
  border: 1px solid var(--result-chip-border);
  border-radius: 999px;
  padding: 2px 10px;
  font-size: var(--font-size-xs);
  line-height: 18px;
  color: var(--el-color-primary);
  background: var(--result-chip-bg);
  white-space: nowrap;
}

.result-title {
  font-size: var(--font-size-h5);
  line-height: var(--line-height-tight);
  color: var(--el-text-color-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.header-ops {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.result-back-btn {
  border: 1px solid var(--ui-border-soft);
  background: var(--ui-surface-1);
}

.result-metrics {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}

.metric-item {
  border: 1px solid var(--ui-border-soft);
  border-radius: 999px;
  padding: 1px 10px;
  font-size: var(--font-size-xs);
  line-height: 19px;
  color: var(--el-text-color-secondary);
  background: color-mix(in srgb, var(--ui-surface-1) 92%, transparent 8%);
}

.metric-item-time {
  cursor: help;
}

.comment-card {
  margin-top: var(--space-3);
}

.comment-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
}

.comment-total {
  color: var(--el-text-color-secondary);
  font-size: var(--font-size-xs);
}

.comment-item {
  border: 1px solid var(--result-comment-border);
  border-radius: var(--radius-sm);
  background: var(--result-comment-bg);
  padding: 10px var(--space-3);
}

.comment-item + .comment-item {
  margin-top: var(--space-2);
}

.comment-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  margin-bottom: 6px;
}

.comment-admin {
  color: var(--el-text-color-primary);
}

.comment-time {
  color: var(--el-text-color-secondary);
  font-size: var(--font-size-xs);
}

.comment-line {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
}

.comment-content {
  color: var(--el-text-color-regular);
  line-height: var(--line-height-base);
  white-space: pre-wrap;
  flex: 1;
}

.comment-actions {
  white-space: nowrap;
}

.add-comment-card :deep(.el-textarea__inner) {
  background: var(--result-comment-bg);
  border-color: var(--result-comment-border);
}

.comment-submit-wrap {
  margin-top: var(--space-2);
  text-align: right;
}

:global(.dark) .result-page-card {
  --result-head-bg: linear-gradient(150deg, rgb(31 37 46 / 92%) 0%, rgb(21 26 34 / 96%) 100%);
  --result-head-border: #3d4b5f;
  --result-chip-bg: rgb(41 71 112 / 48%);
  --result-chip-border: #3f669b;
  --result-comment-bg: linear-gradient(145deg, rgb(26 31 39 / 95%) 0%, rgb(20 25 32 / 96%) 100%);
  --result-comment-border: #3a485d;
}

:global(.dark) .result-page-card .metric-item {
  color: #c3d2e6;
  background: rgb(32 40 51 / 68%);
  border-color: #3e4f66;
}

@media (max-width: 768px) {
  .result-header {
    align-items: flex-start;
    flex-direction: column;
  }

  .result-title {
    white-space: normal;
  }

  .comment-meta {
    align-items: flex-start;
    flex-direction: column;
    gap: 2px;
  }

  .comment-line {
    flex-direction: column;
    gap: 6px;
  }
}
</style>
