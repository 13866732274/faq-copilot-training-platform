<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { getMyPracticeDashboard, startRandomPractice } from '../../api/practice'

const router = useRouter()
const route = useRoute()
const loading = ref(false)
const randomLoading = ref(false)
const data = reactive({
  total_quizzes: 0,
  completed_quizzes: 0,
  total_practices: 0,
  this_week_practices: 0,
  streak_days: 0,
  avg_rounds: 0,
  weekly_heatmap: [] as Array<{ date: string; count: number }>,
  recent_practices: [] as Array<{
    practice_id: number
    quiz_id: number
    quiz_title: string
    status: 'in_progress' | 'completed'
    started_at: string
    completed_at?: string | null
  }>,
  in_progress_count: 0,
  last_in_progress: null as null | {
    practice_id: number
    quiz_id: number
    quiz_title: string
    started_at: string
  },
})
const recentStatusFilter = ref<'all' | 'in_progress' | 'completed'>('all')

const normalizeRecentStatus = (value: unknown): 'all' | 'in_progress' | 'completed' => {
  if (value === 'in_progress' || value === 'completed' || value === 'all') return value
  return 'all'
}

const progressPercent = computed(() => {
  if (!data.total_quizzes) return 0
  return Math.min(100, Math.round((data.completed_quizzes / data.total_quizzes) * 100))
})

const heatmapMax = computed(() => Math.max(1, ...data.weekly_heatmap.map((i) => i.count)))
const filteredRecentPractices = computed(() => {
  if (recentStatusFilter.value === 'all') return data.recent_practices
  return data.recent_practices.filter((item) => item.status === recentStatusFilter.value)
})

const heatmapLevel = (count: number) => {
  if (!count) return 0
  const ratio = count / heatmapMax.value
  if (ratio >= 0.8) return 4
  if (ratio >= 0.55) return 3
  if (ratio >= 0.3) return 2
  return 1
}

const formatHeatmapDate = (date: string) => {
  const monthDay = date.slice(5)
  return monthDay.startsWith('01-') ? monthDay.replace('-', '/') : monthDay.slice(3)
}

const load = async () => {
  loading.value = true
  try {
    const res = await getMyPracticeDashboard()
    data.total_quizzes = res.total_quizzes
    data.completed_quizzes = res.completed_quizzes
    data.total_practices = res.total_practices
    data.this_week_practices = res.this_week_practices
    data.streak_days = res.streak_days
    data.avg_rounds = res.avg_rounds
    data.weekly_heatmap = res.weekly_heatmap || []
    data.recent_practices = res.recent_practices || []
    data.in_progress_count = res.in_progress_count
    data.last_in_progress = res.last_in_progress || null
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || '加载工作台失败')
  } finally {
    loading.value = false
  }
}

const continueLastInProgress = () => {
  if (!data.last_in_progress?.practice_id) return
  router.push({
    path: `/practice/${data.last_in_progress.practice_id}/chat`,
    query: { from: 'dashboard' },
  })
}

const openRecentPractice = (row: { practice_id: number; status: 'in_progress' | 'completed' }) => {
  if (row.status === 'completed') {
    router.push(`/practice/${row.practice_id}/review`)
    return
  }
  router.push({
    path: `/practice/${row.practice_id}/chat`,
    query: { from: 'dashboard_recent' },
  })
}

const startRandom = async () => {
  if (randomLoading.value) return
  randomLoading.value = true
  try {
    const res = await startRandomPractice()
    ElMessage.success('已为您匹配训练案例')
    router.push(`/practice/${res.practice_id}/chat`)
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || '随机训练失败')
  } finally {
    randomLoading.value = false
  }
}

onMounted(load)

onMounted(() => {
  recentStatusFilter.value = normalizeRecentStatus(route.query.recent_status)
})

watch(
  () => route.query.recent_status,
  (queryStatus) => {
    const normalized = normalizeRecentStatus(queryStatus)
    if (normalized !== recentStatusFilter.value) {
      recentStatusFilter.value = normalized
    }
  },
)

watch(recentStatusFilter, (status) => {
  const current = normalizeRecentStatus(route.query.recent_status)
  if (current === status) return
  const nextQuery = { ...route.query }
  if (status === 'all') {
    delete nextQuery.recent_status
  } else {
    nextQuery.recent_status = status
  }
  router.replace({ query: nextQuery })
})
</script>

<template>
  <el-card shadow="never" v-loading="loading">
    <template #header>
      <div class="admin-card-header">
        <strong class="admin-card-title">工作台</strong>
        <div class="admin-card-header-actions">
          <el-button @click="router.push('/practice/list')">案例库列表</el-button>
          <el-button
            v-if="data.last_in_progress"
            type="warning"
            plain
            @click="continueLastInProgress"
          >
            继续上次未完成的训练
          </el-button>
          <el-button type="primary" :loading="randomLoading" @click="startRandom">快速随机训练</el-button>
        </div>
      </div>
    </template>

    <div class="dashboard-grid">
      <el-card shadow="never" class="panel progress-panel">
        <template #header>训练进度</template>
        <div class="progress-wrap">
          <el-progress type="circle" :percentage="progressPercent" :width="132" />
          <div class="progress-meta">
            <div>已完成案例：{{ data.completed_quizzes }} / {{ data.total_quizzes }}</div>
            <div>进行中：{{ data.in_progress_count }} 条</div>
          </div>
        </div>
      </el-card>

      <el-card shadow="never" class="panel metrics-panel">
        <template #header>训练指标</template>
        <div class="metrics-grid">
          <div class="metric-item">
            <div class="metric-value">{{ data.total_practices }}</div>
            <div class="metric-label">累计训练</div>
          </div>
          <div class="metric-item">
            <div class="metric-value">{{ data.this_week_practices }}</div>
            <div class="metric-label">本周训练</div>
          </div>
          <div class="metric-item">
            <div class="metric-value">{{ data.streak_days }}</div>
            <div class="metric-label">连续训练天数</div>
          </div>
          <div class="metric-item">
            <div class="metric-value">{{ data.avg_rounds }}</div>
            <div class="metric-label">平均轮次</div>
          </div>
        </div>
      </el-card>

      <el-card shadow="never" class="panel heatmap-panel">
        <template #header>最近 30 天训练热力图</template>
        <div class="heatmap">
          <div v-for="item in data.weekly_heatmap" :key="item.date" class="heatmap-item-wrap">
            <div class="heatmap-date">{{ formatHeatmapDate(item.date) }}</div>
            <div class="heatmap-item" :class="`lv-${heatmapLevel(item.count)}`">{{ item.count }}</div>
          </div>
        </div>
      </el-card>
    </div>

    <el-card shadow="never" class="panel recent-panel">
      <template #header>
        <div class="recent-header">
          <span>最近训练</span>
          <el-radio-group v-model="recentStatusFilter" size="small">
            <el-radio-button label="all">全部</el-radio-button>
            <el-radio-button label="in_progress">进行中</el-radio-button>
            <el-radio-button label="completed">已完成</el-radio-button>
          </el-radio-group>
        </div>
      </template>
      <el-empty v-if="!filteredRecentPractices.length" description="当前筛选下暂无训练记录" />
      <el-table v-else :data="filteredRecentPractices" border stripe>
        <el-table-column prop="quiz_title" label="案例" min-width="260" />
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="row.status === 'completed' ? 'success' : 'warning'">
              {{ row.status === 'completed' ? '已完成' : '进行中' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="started_at" label="开始时间" width="180" />
        <el-table-column prop="completed_at" label="完成时间" width="180" />
        <el-table-column label="操作" width="130">
          <template #default="{ row }">
            <el-button type="primary" link @click="openRecentPractice(row)">
              {{ row.status === 'completed' ? '查看复盘' : '继续训练' }}
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </el-card>
</template>

<style scoped>
.dashboard-grid {
  display: grid;
  gap: 12px;
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.panel {
  border: 1px solid var(--ui-border-soft);
}

.progress-wrap {
  display: flex;
  align-items: center;
  gap: 16px;
}

.progress-meta {
  display: grid;
  gap: 8px;
  color: var(--el-text-color-regular);
}

.metrics-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.metric-item {
  border: 1px solid var(--ui-border-soft);
  border-radius: 10px;
  padding: 10px;
  background: var(--ui-surface-1);
}

.metric-value {
  font-size: 22px;
  font-weight: 700;
}

.metric-label {
  margin-top: 2px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.heatmap {
  display: grid;
  grid-template-columns: repeat(10, minmax(0, 1fr));
  gap: 6px;
}

.heatmap-item-wrap {
  display: grid;
  gap: 4px;
  justify-items: center;
}

.heatmap-date {
  font-size: 11px;
  color: var(--el-text-color-secondary);
}

.heatmap-item {
  width: 100%;
  min-height: 28px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  color: #fff;
  font-weight: 600;
  background: #d4dbe8;
}

.heatmap-item.lv-1 { background: #77c59a; }
.heatmap-item.lv-2 { background: #44ad78; }
.heatmap-item.lv-3 { background: #219462; }
.heatmap-item.lv-4 { background: #067c4f; }

.recent-panel {
  margin-top: 12px;
}

.recent-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

@media (max-width: 992px) {
  .dashboard-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 768px) {
  .heatmap {
    grid-template-columns: repeat(6, minmax(0, 1fr));
  }

  .recent-header {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
