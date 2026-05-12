<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  batchDeleteFaqTasks,
  clearFaqTaskHistory,
  deleteFaqTask,
  getFaqTaskEtaBenchmarks,
  getFaqTaskFailureStats,
  listFaqTasks,
  retryFaqTask,
  type EtaBenchmarksData,
  type FaqTaskFailureStatItem,
  type FaqTaskItem,
} from '../../api/faq'
import { useUserStore } from '../../stores/user'

const loading = ref(false)
const items = ref<FaqTaskItem[]>([])
const total = ref(0)
const failureStats = ref<FaqTaskFailureStatItem[]>([])
const failedTotal = ref(0)
const activeFailureCode = ref<string | null>(null)
const etaBenchmarks = ref<EtaBenchmarksData | null>(null)
let pollTimer: ReturnType<typeof setInterval> | null = null
let nowTimer: ReturnType<typeof setInterval> | null = null
const nowMs = ref(Date.now())
const selectedIds = ref<number[]>([])
const keepDays = ref(30)
const userStore = useUserStore()
const canManage = computed(() => userStore.user?.role === 'super_admin')

const statusLabel = (s: string) => {
  const m: Record<string, string> = {
    pending: '排队中',
    extracting: '提取问答对...',
    embedding: '语义向量化...',
    clustering: '聚类分析...',
    refining: 'AI 精炼中...',
    completed: '已完成',
    failed: '失败',
  }
  return m[s] || s
}

const statusType = (s: string) => {
  if (s === 'completed') return 'success'
  if (s === 'failed') return 'danger'
  if (s === 'pending') return 'info'
  return 'warning'
}

const parseUtcIso = (value?: string | null): Date | null => {
  if (!value) return null
  const normalized = value.endsWith('Z') ? value : `${value}Z`
  const d = new Date(normalized)
  return Number.isNaN(d.getTime()) ? null : d
}

const formatBeijingTime = (value?: string | null) => {
  const d = parseUtcIso(value)
  if (!d) return '—'
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    hour12: false,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).format(d).replace(/\//g, '-')
}

const runningStatuses = ['pending', 'extracting', 'embedding', 'clustering', 'refining']

const estimateStageMinutes = (row: FaqTaskItem, status: string): number => {
  const q = Math.max(1, Number(row.total_quizzes || 0))
  const bm = etaBenchmarks.value?.benchmarks
  if (bm && bm[status]) {
    const perQuiz = bm[status].avg_per_quiz
    if (perQuiz > 0) return Math.max(0.2, (perQuiz * q) / 60)
  }
  if (status === 'pending') return 0.2
  if (status === 'extracting') return Math.min(12, Math.max(1, Math.round(q * 0.4)))
  if (status === 'embedding') return Math.min(8, Math.max(0.5, Math.round(q * 0.2)))
  if (status === 'clustering') return Math.min(2, Math.max(0.1, Math.round(q * 0.05)))
  if (status === 'refining') return Math.min(15, Math.max(1, Math.round(q * 0.5)))
  return 0
}

const stageBasePercent: Record<string, number> = {
  pending: 2,
  extracting: 10,
  embedding: 35,
  clustering: 60,
  refining: 80,
}
const stageRangePercent: Record<string, number> = {
  pending: 8,
  extracting: 25,
  embedding: 25,
  clustering: 20,
  refining: 18,
}

const stageElapsedMinutes = (row: FaqTaskItem) => {
  const start = parseUtcIso(row.stage_changed_at || row.started_at)
  if (!start) return 0
  return Math.max(0, (nowMs.value - start.getTime()) / 60000)
}

const progressPercent = (row: FaqTaskItem) => {
  if (row.status === 'completed') return 100
  if (row.status === 'failed') return 100
  if (!runningStatuses.includes(row.status)) return 0
  const expected = estimateStageMinutes(row, row.status)
  const elapsed = stageElapsedMinutes(row)
  const ratio = expected <= 0 ? 0 : Math.min(1, elapsed / expected)
  const base = stageBasePercent[row.status] || 0
  const range = stageRangePercent[row.status] || 0
  return Math.min(99, Math.round(base + ratio * range))
}

const progressStatus = (row: FaqTaskItem): 'success' | 'warning' | 'exception' => {
  if (row.status === 'completed') return 'success'
  if (row.status === 'failed') return 'exception'
  return 'warning'
}

const etaText = (row: FaqTaskItem) => {
  if (row.status === 'completed') {
    const durations = parseStageDurations(row)
    if (durations) {
      const totalSec = Object.values(durations).reduce((s, v) => s + v, 0)
      return `总耗时 ${Math.round(totalSec)}秒`
    }
    return '已完成'
  }
  if (!runningStatuses.includes(row.status)) return '—'
  const seq = ['pending', 'extracting', 'embedding', 'clustering', 'refining']
  const curIdx = seq.indexOf(row.status)
  const elapsedCur = stageElapsedMinutes(row)
  const expectedCur = estimateStageMinutes(row, row.status)
  let remain = Math.max(0, expectedCur - elapsedCur)
  for (let i = curIdx + 1; i < seq.length; i += 1) {
    const nextStage = seq[i]
    if (!nextStage) continue
    remain += estimateStageMinutes(row, nextStage)
  }
  if (remain < 0.2) return '即将完成'
  if (remain < 1) return '预计不足1分钟'
  return `预计剩余约 ${Math.round(remain)} 分钟`
}

const parseStageDurations = (row: FaqTaskItem): Record<string, number> | null => {
  if (!row.stage_durations_json) return null
  try {
    return JSON.parse(row.stage_durations_json)
  } catch {
    return null
  }
}

const etaSourceHint = computed(() => {
  const bm = etaBenchmarks.value
  if (bm && bm.benchmarks && bm.sample_count > 0) {
    return `基于 ${bm.sample_count} 个历史任务自动学习`
  }
  return '基于静态估算（无历史数据）'
})

const load = async () => {
  loading.value = true
  try {
    const taskData = await listFaqTasks(1, 50)
    items.value = taskData.items
    total.value = taskData.total
    selectedIds.value = []

    try {
      const statsData = await getFaqTaskFailureStats(30)
      failureStats.value = statsData.items
      failedTotal.value = statsData.total_failed
    } catch {
      failureStats.value = []
      failedTotal.value = 0
    }

    try {
      etaBenchmarks.value = await getFaqTaskEtaBenchmarks()
    } catch {
      etaBenchmarks.value = null
    }
  } catch (e: any) {
    ElMessage.error('加载任务列表失败')
  } finally {
    loading.value = false
  }
}

const onSelectionChange = (rows: FaqTaskItem[]) => {
  selectedIds.value = rows.map((r) => r.id)
}

const handleRetry = async (row: FaqTaskItem) => {
  if (row.status !== 'failed') return
  try {
    await ElMessageBox.confirm(`确认重试任务 #${row.id} 吗？将复用该任务的上次处理参数。`, '重试确认', {
      type: 'warning',
      confirmButtonText: '确认重试',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }

  loading.value = true
  try {
    const result = await retryFaqTask(row.id)
    ElMessage.success(`已提交重试任务 #${result.task_id}`)
    await load()
    if (hasRunning()) startPolling()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.response?.data?.message || '重试任务失败')
  } finally {
    loading.value = false
  }
}

const handleDeleteOne = async (row: FaqTaskItem) => {
  if (!canManage.value) return
  if (!['completed', 'failed'].includes(row.status)) {
    ElMessage.warning('仅已完成或失败任务允许删除')
    return
  }
  try {
    await ElMessageBox.confirm(`确认删除任务 #${row.id} 吗？`, '删除确认', {
      type: 'warning',
      confirmButtonText: '确认删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  await deleteFaqTask(row.id)
  ElMessage.success('删除成功')
  await load()
}

const handleBatchDelete = async () => {
  if (!canManage.value) return
  if (!selectedIds.value.length) {
    ElMessage.warning('请先勾选任务')
    return
  }
  try {
    await ElMessageBox.confirm(`确认批量删除已选 ${selectedIds.value.length} 条任务吗？仅会删除已完成/失败任务。`, '批量删除确认', {
      type: 'warning',
      confirmButtonText: '确认删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  const data = await batchDeleteFaqTasks(selectedIds.value)
  ElMessage.success(`批量删除完成：${data.deleted} 条`)
  await load()
}

const handleClearHistory = async () => {
  if (!canManage.value) return
  try {
    await ElMessageBox.confirm(`确认清理历史任务吗？将保留最近 ${keepDays.value} 天任务（运行中任务不会删除）。`, '清理确认', {
      type: 'warning',
      confirmButtonText: '确认清理',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  const data = await clearFaqTaskHistory(keepDays.value)
  ElMessage.success(`清理完成：删除 ${data.deleted} 条历史任务`)
  await load()
}

const filteredItems = computed(() => {
  if (!activeFailureCode.value) return items.value
  return items.value.filter((row) => row.status === 'failed' && row.failure_reason_code === activeFailureCode.value)
})

const filteredTotal = computed(() => filteredItems.value.length)

const handleFailureFilter = (code: string) => {
  activeFailureCode.value = activeFailureCode.value === code ? null : code
}

const clearFailureFilter = () => {
  activeFailureCode.value = null
}

const hasRunning = () => items.value.some((t) =>
  runningStatuses.includes(t.status),
)

const startPolling = () => {
  if (pollTimer) return
  pollTimer = setInterval(async () => {
    if (!hasRunning()) {
      if (pollTimer) clearInterval(pollTimer)
      pollTimer = null
      return
    }
    await load()
  }, 5000)
}

onMounted(async () => {
  await load()
  if (hasRunning()) startPolling()
  nowTimer = setInterval(() => {
    nowMs.value = Date.now()
  }, 1000)
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
  if (nowTimer) clearInterval(nowTimer)
})
</script>

<template>
  <div class="task-page">
    <div class="page-header">
      <div class="page-header-main">
        <strong class="page-title">FAQ 处理任务</strong>
        <p class="page-desc">
          查看知识库生成任务的执行状态和结果。
          <span v-if="activeFailureCode" class="filter-tip">
            当前按失败分类筛选（{{ filteredTotal }} 条）
            <el-link type="primary" :underline="false" @click="clearFailureFilter">清除筛选</el-link>
          </span>
        </p>
      </div>
      <div class="header-actions">
        <el-button @click="load" :loading="loading">刷新</el-button>
        <template v-if="canManage">
          <el-input-number v-model="keepDays" :min="0" :max="3650" size="small" />
          <el-button type="danger" plain @click="handleClearHistory">一键清理历史任务</el-button>
          <el-button type="danger" plain :disabled="!selectedIds.length" @click="handleBatchDelete">批量删除</el-button>
        </template>
      </div>
    </div>

    <el-table :data="filteredItems" v-loading="loading" stripe @selection-change="onSelectionChange">
      <el-table-column v-if="canManage" type="selection" width="48" />
      <el-table-column label="ID" prop="id" width="60" />
      <el-table-column label="重试来源" width="120">
        <template #default="{ row }">
          <span v-if="row.retry_from_task_id">由 #{{ row.retry_from_task_id }} 重试</span>
          <span v-else class="text-muted">—</span>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="140">
        <template #default="{ row }">
          <el-tag :type="statusType(row.status)" size="small">{{ statusLabel(row.status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="超时阈值" width="120" align="center">
        <template #default="{ row }">
          <el-tooltip :content="`来源：${row.heartbeat_timeout_source_label}`" placement="top">
            <el-tag type="info" size="small">{{ row.heartbeat_timeout_minutes }} 分钟</el-tag>
          </el-tooltip>
        </template>
      </el-table-column>
      <el-table-column width="230">
        <template #header>
          <el-tooltip :content="etaSourceHint" placement="top">
            <span>执行进度 ⓘ</span>
          </el-tooltip>
        </template>
        <template #default="{ row }">
          <el-progress
            :percentage="progressPercent(row)"
            :status="progressStatus(row)"
            :stroke-width="12"
            :show-text="false"
          />
          <div class="progress-subtext">{{ etaText(row) }}</div>
        </template>
      </el-table-column>
      <el-table-column label="失败分类" width="150">
        <template #default="{ row }">
          <el-tag v-if="row.status === 'failed' && row.failure_reason_label" type="danger" size="small">
            {{ row.failure_reason_label }}
          </el-tag>
          <span v-else class="text-muted">—</span>
        </template>
      </el-table-column>
      <el-table-column label="对话数" prop="total_quizzes" width="80" align="center" />
      <el-table-column label="消息数" prop="total_messages" width="80" align="center" />
      <el-table-column label="提取问答" prop="extracted_pairs" width="90" align="center" />
      <el-table-column label="生成聚类" prop="clusters_created" width="90" align="center" />
      <el-table-column label="错误信息" min-width="200">
        <template #default="{ row }">
          <span v-if="row.error_message" class="error-text">{{ row.error_message }}</span>
          <span v-else class="text-muted">—</span>
        </template>
      </el-table-column>
      <el-table-column label="开始时间（北京时间）" width="190">
        <template #default="{ row }">
          {{ formatBeijingTime(row.started_at) }}
        </template>
      </el-table-column>
      <el-table-column label="完成时间（北京时间）" width="190">
        <template #default="{ row }">
          {{ formatBeijingTime(row.finished_at) }}
        </template>
      </el-table-column>
      <el-table-column label="操作" width="120" fixed="right">
        <template #default="{ row }">
          <div class="op-col">
            <el-button
              v-if="row.status === 'failed'"
              size="small"
              type="warning"
              @click="handleRetry(row)"
            >
              一键重试
            </el-button>
            <el-button
              v-if="canManage && ['completed', 'failed'].includes(row.status)"
              size="small"
              type="danger"
              plain
              @click="handleDeleteOne(row)"
            >
              删除
            </el-button>
            <span v-if="row.status !== 'failed' && !(canManage && ['completed', 'failed'].includes(row.status))" class="text-muted">—</span>
          </div>
        </template>
      </el-table-column>
    </el-table>

    <el-card class="failure-card" shadow="never">
      <template #header>
        <div class="failure-card-header">
          <strong>失败原因分类统计（近 30 天）</strong>
          <span class="failure-total">
            失败总数：{{ failedTotal }}
            <span v-if="activeFailureCode">｜筛选后：{{ filteredTotal }}</span>
          </span>
        </div>
      </template>
      <div v-if="failureStats.length" class="failure-grid">
        <div
          v-for="item in failureStats"
          :key="item.code"
          class="failure-item"
          :class="{ active: activeFailureCode === item.code }"
          @click="handleFailureFilter(item.code)"
        >
          <div class="failure-item-top">
            <el-tag type="danger" size="small">{{ item.label }}</el-tag>
            <strong>{{ item.count }}</strong>
          </div>
          <div class="failure-item-meta">
            最近：#{{ item.latest_task_id }} {{ item.latest_at || '' }}
          </div>
          <div v-if="item.sample_error" class="failure-item-error">{{ item.sample_error }}</div>
        </div>
      </div>
      <div v-else class="text-muted">近 30 天无失败任务</div>
    </el-card>
  </div>
</template>

<style scoped>
.task-page {
  display: grid;
  gap: var(--space-3);
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
}

.header-actions {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.page-header-main {
  display: grid;
  gap: 4px;
}

.page-title {
  font-size: var(--font-size-h5);
}

.page-desc {
  margin: 0;
  color: var(--el-text-color-secondary);
  font-size: var(--font-size-xs);
}

.filter-tip {
  margin-left: 8px;
}

.error-text {
  color: var(--el-color-danger);
  font-size: var(--font-size-xs);
}

.text-muted {
  color: var(--el-text-color-placeholder);
}

.failure-card {
  border: 1px solid var(--el-border-color-light);
}

.failure-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.failure-total {
  color: var(--el-text-color-secondary);
  font-size: var(--font-size-xs);
}

.failure-grid {
  display: grid;
  gap: var(--space-2);
}

.failure-item {
  display: grid;
  gap: 6px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  padding: 10px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.failure-item:hover {
  border-color: var(--el-color-danger-light-5);
}

.failure-item.active {
  border-color: var(--el-color-danger);
  background: var(--el-color-danger-light-9);
}

.failure-item-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.failure-item-meta {
  color: var(--el-text-color-secondary);
  font-size: var(--font-size-xs);
}

.failure-item-error {
  color: var(--el-text-color-regular);
  font-size: var(--font-size-xs);
  line-height: 1.4;
  word-break: break-all;
}

.progress-subtext {
  margin-top: 4px;
  color: var(--el-text-color-secondary);
  font-size: var(--font-size-xs);
}

.op-col {
  display: inline-flex;
  gap: 6px;
}
</style>
