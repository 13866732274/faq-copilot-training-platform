<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getFaqStats, getFaqDataQuality, startFaqProcessing, startFaqIncremental, type FaqStatsData, type FaqDataQuality } from '../../api/faq'

const router = useRouter()
const loading = ref(false)
const processing = ref(false)
const stats = ref<FaqStatsData | null>(null)
const dataQuality = ref<FaqDataQuality | null>(null)

const load = async () => {
  loading.value = true
  try {
    const [s, dq] = await Promise.all([getFaqStats(), getFaqDataQuality()])
    stats.value = s
    dataQuality.value = dq
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '加载统计失败')
  } finally {
    loading.value = false
  }
}

const healthScoreClass = computed(() => {
  const score = dataQuality.value?.health_score ?? 0
  if (score >= 0.8) return 'health-good'
  if (score >= 0.5) return 'health-warn'
  return 'health-bad'
})

const healthScoreLabel = computed(() => {
  const score = dataQuality.value?.health_score ?? 0
  if (score >= 0.8) return '健康'
  if (score >= 0.5) return '一般'
  return '需关注'
})

const incrementalProcessing = ref(false)

const startProcessing = async () => {
  try {
    await ElMessageBox.confirm(
      '将对所有已导入的对话记录进行智能分析：\n\n1. 提取患者问答对\n2. 语义聚类相似问题\n3. AI 精炼标题和最佳答案\n\n⚠ 全量模式会清除未锁定的旧 FAQ 重新生成。',
      '全量生成知识库',
      { confirmButtonText: '开始处理', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }
  processing.value = true
  try {
    const result = await startFaqProcessing()
    ElMessage.success(`全量处理任务已启动（任务 #${result.task_id}）`)
    router.push('/admin/faq/tasks')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '启动处理任务失败')
  } finally {
    processing.value = false
  }
}

const startIncremental = async () => {
  try {
    await ElMessageBox.confirm(
      '仅处理新导入的对话（已生成过 FAQ 的对话会跳过）：\n\n• 不会删除已有 FAQ 条目\n• 新提取的聚类会追加到知识库中\n• 推荐日常使用此模式',
      '增量更新知识库',
      { confirmButtonText: '增量更新', cancelButtonText: '取消', type: 'info' },
    )
  } catch {
    return
  }
  incrementalProcessing.value = true
  try {
    const result = await startFaqIncremental()
    if (result.skipped_reason) {
      ElMessage.info(result.skipped_reason)
    } else {
      ElMessage.success(`增量任务已启动（任务 #${result.task_id}，待处理 ${result.new_quiz_count ?? '?'} 个新对话）`)
      router.push('/admin/faq/tasks')
    }
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '启动增量任务失败')
  } finally {
    incrementalProcessing.value = false
  }
}

const taskStatusLabel = (status: string) => {
  const map: Record<string, string> = {
    pending: '等待中',
    extracting: '提取问答对',
    embedding: '向量化',
    clustering: '聚类分析',
    refining: 'AI 精炼',
    completed: '已完成',
    failed: '失败',
  }
  return map[status] || status
}

const taskStatusType = (status: string) => {
  if (status === 'completed') return 'success'
  if (status === 'failed') return 'danger'
  return 'warning'
}

const trend = computed(() => stats.value?.copilot_7d_trend || [])
const maxCalls = computed(() => Math.max(1, ...trend.value.map((d) => d.calls || 0)))
const maxLatency = computed(() => Math.max(1, ...trend.value.map((d) => d.avg_latency_ms || 0)))
const maxFailRate = computed(() => Math.max(1, ...trend.value.map((d) => d.failure_rate || 0)))

const barWidth = (v: number, max: number) => `${Math.max(4, Math.round((v / Math.max(1, max)) * 100))}%`
const dayLabel = (iso: string) => (iso || '').slice(5)

const trendDelta = computed(() => {
  const arr = trend.value
  if (arr.length < 2) return null
  const today = arr[arr.length - 1]
  const yesterday = arr[arr.length - 2]
  if (!today || !yesterday) return null
  const calc = (todayValue: number, yValue: number) => {
    if (yValue <= 0) {
      return {
        percent: todayValue > 0 ? 100 : 0,
        direction: todayValue > 0 ? 'up' as const : 'flat' as const,
      }
    }
    const p = ((todayValue - yValue) / yValue) * 100
    return {
      percent: Math.round(Math.abs(p) * 10) / 10,
      direction: p > 0 ? 'up' as const : p < 0 ? 'down' as const : 'flat' as const,
    }
  }
  return {
    calls: calc(today.calls, yesterday.calls),
    latency: calc(today.avg_latency_ms, yesterday.avg_latency_ms),
    failure: calc(today.failure_rate, yesterday.failure_rate),
  }
})

const deltaText = (
  metric: 'calls' | 'latency' | 'failure',
  direction: 'up' | 'down' | 'flat',
  percent: number,
) => {
  if (direction === 'flat') return '较昨日持平'
  const label = metric === 'calls' ? '调用量' : metric === 'latency' ? '耗时' : '失败率'
  const arrow = direction === 'up' ? '↑' : '↓'
  return `较昨日${arrow} ${percent.toFixed(1)}%（${label}）`
}

const deltaClass = (
  metric: 'calls' | 'latency' | 'failure',
  direction: 'up' | 'down' | 'flat',
) => {
  if (direction === 'flat') return 'flat'
  if (metric === 'calls') return direction === 'up' ? 'down' : 'up'
  return direction === 'up' ? 'up' : 'down'
}

onMounted(load)
</script>

<template>
  <div v-loading="loading" class="faq-dashboard">
    <div class="faq-header">
      <div class="faq-header-main">
        <strong class="faq-title">FAQ 智能知识库</strong>
        <p class="faq-desc">从对话记录中自动提取、聚类、精炼常见问答，构建可检索的 FAQ 知识库。</p>
      </div>
      <div class="faq-header-actions">
        <el-button @click="router.push('/admin/quizzes')" plain>
          <el-icon><Upload /></el-icon> 导入对话
        </el-button>
        <el-button @click="load" :loading="loading">刷新</el-button>
        <el-button type="success" :loading="incrementalProcessing" @click="startIncremental">
          <el-icon><Plus /></el-icon> 增量更新
        </el-button>
        <el-button type="primary" :loading="processing" @click="startProcessing">
          全量生成
        </el-button>
      </div>
    </div>

    <div v-if="stats" class="stats-grid">
      <div class="stat-card primary" @click="router.push('/admin/faq/clusters')">
        <div class="stat-number">{{ stats.total_clusters }}</div>
        <div class="stat-label">FAQ 条目总数</div>
      </div>
      <div class="stat-card success">
        <div class="stat-number">{{ stats.active_clusters }}</div>
        <div class="stat-label">已启用</div>
      </div>
      <div class="stat-card info">
        <div class="stat-number">{{ stats.total_questions }}</div>
        <div class="stat-label">归纳问题数</div>
      </div>
      <div class="stat-card info">
        <div class="stat-number">{{ stats.total_answers }}</div>
        <div class="stat-label">收录回答数</div>
      </div>
    </div>

    <el-card v-if="dataQuality" shadow="never" class="data-quality-card">
      <template #header>
        <div class="section-header">
          <strong>数据导入质量</strong>
          <el-tag :type="healthScoreClass === 'health-good' ? 'success' : healthScoreClass === 'health-warn' ? 'warning' : 'danger'" size="small">
            {{ healthScoreLabel }} ({{ ((dataQuality.health_score ?? 0) * 100).toFixed(0) }}%)
          </el-tag>
        </div>
      </template>
      <div class="dq-grid">
        <div class="dq-item">
          <div class="dq-number">{{ dataQuality.conversations.total }}</div>
          <div class="dq-label">对话总数</div>
        </div>
        <div class="dq-item">
          <div class="dq-number">{{ dataQuality.messages.total }}</div>
          <div class="dq-label">消息总数</div>
        </div>
        <div class="dq-item">
          <div class="dq-number">{{ dataQuality.messages.patient_ratio }}%</div>
          <div class="dq-label">患者消息占比</div>
        </div>
        <div class="dq-item">
          <div class="dq-number">{{ dataQuality.messages.text_ratio }}%</div>
          <div class="dq-label">文本消息占比</div>
        </div>
        <div class="dq-item">
          <div class="dq-number">{{ dataQuality.conversations.avg_messages }}</div>
          <div class="dq-label">平均每对话消息</div>
        </div>
        <div class="dq-item">
          <div class="dq-number">{{ dataQuality.faq.locked }}</div>
          <div class="dq-label">手工锁定条目</div>
        </div>
      </div>
      <div v-if="dataQuality.warnings.length" class="dq-warnings">
        <div v-for="(w, i) in dataQuality.warnings" :key="i" class="dq-warning-item">
          ⚠ {{ w }}
        </div>
      </div>
    </el-card>

    <el-card v-if="stats" shadow="never" class="ai-stats-card" @click="router.push('/admin/faq/copilot-logs')">
      <template #header>
        <div class="section-header">
          <strong>AI 问答统计（今日）</strong>
          <el-button link type="primary" @click.stop="router.push('/admin/faq/copilot-logs')">查看调用明细</el-button>
        </div>
      </template>
      <div class="ai-stats-grid">
        <div class="ai-metric-item">
          <div class="ai-metric-value">{{ stats.copilot_today.total_calls }}</div>
          <div class="ai-metric-label">今日调用量</div>
          <div
            v-if="trendDelta"
            class="metric-delta"
            :class="deltaClass('calls', trendDelta.calls.direction)"
          >
            {{ deltaText('calls', trendDelta.calls.direction, trendDelta.calls.percent) }}
          </div>
        </div>
        <div class="ai-metric-item">
          <div class="ai-metric-value">{{ (stats.copilot_today.avg_latency_ms / 1000).toFixed(1) }}s</div>
          <div class="ai-metric-label">平均耗时</div>
          <div
            v-if="trendDelta"
            class="metric-delta"
            :class="deltaClass('latency', trendDelta.latency.direction)"
          >
            {{ deltaText('latency', trendDelta.latency.direction, trendDelta.latency.percent) }}
          </div>
        </div>
        <div class="ai-metric-item">
          <div class="ai-metric-value">{{ stats.copilot_today.quality_hit_rate.toFixed(1) }}%</div>
          <div class="ai-metric-label">命中高质量比例</div>
        </div>
        <div class="ai-metric-item danger">
          <div class="ai-metric-value">{{ stats.copilot_today.failure_rate.toFixed(1) }}%</div>
          <div class="ai-metric-label">失败率</div>
          <div
            v-if="trendDelta"
            class="metric-delta"
            :class="deltaClass('failure', trendDelta.failure.direction)"
          >
            {{ deltaText('failure', trendDelta.failure.direction, trendDelta.failure.percent) }}
          </div>
        </div>
      </div>
      <div class="ai-stats-footnote">
        统计口径：北京时间 {{ stats.copilot_today.date_bj }}，失败判定=空回复或 AI 服务异常类回复。
      </div>
      <div class="trend-block">
        <div class="trend-title">最近7日趋势</div>
        <div v-if="trend.length === 0" class="empty-hint">暂无趋势数据</div>
        <div v-else class="trend-grid">
          <div v-for="d in trend" :key="d.date_bj" class="trend-day">
            <div class="trend-date">{{ dayLabel(d.date_bj) }}</div>
            <div class="trend-row">
              <span class="trend-k">调用</span>
              <div class="trend-bar-wrap">
                <div class="trend-bar calls" :style="{ width: barWidth(d.calls, maxCalls) }" />
              </div>
              <span class="trend-v">{{ d.calls }}</span>
            </div>
            <div class="trend-row">
              <span class="trend-k">耗时</span>
              <div class="trend-bar-wrap">
                <div class="trend-bar latency" :style="{ width: barWidth(d.avg_latency_ms, maxLatency) }" />
              </div>
              <span class="trend-v">{{ (d.avg_latency_ms / 1000).toFixed(1) }}s</span>
            </div>
            <div class="trend-row">
              <span class="trend-k">失败</span>
              <div class="trend-bar-wrap">
                <div class="trend-bar fail" :style="{ width: barWidth(d.failure_rate, maxFailRate) }" />
              </div>
              <span class="trend-v">{{ d.failure_rate.toFixed(1) }}%</span>
            </div>
          </div>
        </div>
      </div>
    </el-card>

    <div class="section-row" v-if="stats">
      <el-card shadow="never" class="section-card">
        <template #header>
          <div class="section-header">
            <strong>分类分布</strong>
            <el-button link type="primary" @click="router.push('/admin/faq/clusters')">查看全部</el-button>
          </div>
        </template>
        <div v-if="stats.categories.length === 0" class="empty-hint">暂无分类数据，请先生成知识库</div>
        <div v-else class="category-list">
          <div
            v-for="cat in stats.categories"
            :key="cat.name"
            class="category-item"
            @click="router.push({ path: '/admin/faq/clusters', query: { category: cat.name } })"
          >
            <span class="cat-name">{{ cat.name }}</span>
            <el-tag size="small" round>{{ cat.count }}</el-tag>
          </div>
        </div>
      </el-card>

      <el-card shadow="never" class="section-card">
        <template #header>
          <div class="section-header">
            <strong>最近处理任务</strong>
            <el-button link type="primary" @click="router.push('/admin/faq/tasks')">查看全部</el-button>
          </div>
        </template>
        <div v-if="stats.recent_tasks.length === 0" class="empty-hint">暂无处理记录</div>
        <div v-else class="task-list">
          <div v-for="task in stats.recent_tasks" :key="task.id" class="task-item">
            <div class="task-info">
              <span class="task-id">#{{ task.id }}</span>
              <el-tag :type="taskStatusType(task.status)" size="small">{{ taskStatusLabel(task.status) }}</el-tag>
            </div>
            <div class="task-meta">
              提取 {{ task.extracted_pairs }} 条 → 生成 {{ task.clusters_created }} 个聚类
            </div>
          </div>
        </div>
      </el-card>
    </div>

    <el-card shadow="never" class="quickstart-card">
      <template #header><strong>快速操作</strong></template>
      <div class="quickstart-grid">
        <div class="qs-item" @click="router.push('/admin/quizzes')">
          <el-icon size="24"><Upload /></el-icon>
          <span>导入对话</span>
        </div>
        <div class="qs-item" @click="router.push('/admin/faq/clusters')">
          <el-icon size="24"><Document /></el-icon>
          <span>浏览知识库</span>
        </div>
        <div class="qs-item" @click="router.push('/admin/faq/tasks')">
          <el-icon size="24"><Loading /></el-icon>
          <span>处理任务</span>
        </div>
        <div class="qs-item" @click="router.push('/admin/faq/copilot')">
          <el-icon size="24"><ChatDotRound /></el-icon>
          <span>AI 问答助手</span>
        </div>
        <div class="qs-item" @click="router.push('/admin/faq/copilot-logs')">
          <el-icon size="24"><DataAnalysis /></el-icon>
          <span>AI调用统计</span>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script lang="ts">
import { Document, Loading, ChatDotRound, DataAnalysis, Upload, Plus } from '@element-plus/icons-vue'
export default { components: { Document, Loading, ChatDotRound, DataAnalysis, Upload, Plus } }
</script>

<style scoped>
.faq-dashboard {
  display: grid;
  gap: var(--space-4);
}

.faq-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: var(--space-3);
  flex-wrap: wrap;
}

.faq-header-main {
  display: grid;
  gap: 4px;
}

.faq-title {
  font-size: var(--font-size-h4);
}

.faq-desc {
  margin: 0;
  color: var(--el-text-color-secondary);
  font-size: var(--font-size-sm);
}

.faq-header-actions {
  display: flex;
  gap: var(--space-2);
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: var(--space-3);
}

.stat-card {
  padding: 20px 16px;
  border-radius: 14px;
  border: 1px solid var(--ui-border-soft);
  background: var(--ui-surface-1);
  text-align: center;
  cursor: pointer;
  transition: transform 0.15s ease, box-shadow 0.15s ease;
}

.stat-card:hover {
  transform: translateY(-2px);
  box-shadow: var(--ui-shadow-soft);
}

.stat-card.primary .stat-number { color: var(--el-color-primary); }
.stat-card.success .stat-number { color: var(--el-color-success); }
.stat-card.info .stat-number { color: var(--el-color-info); }

.stat-number {
  font-size: 32px;
  font-weight: 700;
  line-height: 1.2;
}

.stat-label {
  margin-top: 4px;
  font-size: var(--font-size-xs);
  color: var(--el-text-color-secondary);
}

.section-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-3);
}

@media (max-width: 768px) {
  .section-row { grid-template-columns: 1fr; }
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.empty-hint {
  color: var(--el-text-color-placeholder);
  font-size: var(--font-size-sm);
  text-align: center;
  padding: 20px 0;
}

.category-list {
  display: grid;
  gap: 8px;
}

.category-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.15s;
}

.category-item:hover {
  background: var(--el-fill-color-light);
}

.cat-name {
  font-size: var(--font-size-sm);
}

.task-list {
  display: grid;
  gap: 10px;
}

.task-item {
  display: grid;
  gap: 4px;
}

.task-info {
  display: flex;
  align-items: center;
  gap: 8px;
}

.task-id {
  font-weight: 600;
  font-size: var(--font-size-sm);
}

.task-meta {
  font-size: var(--font-size-xs);
  color: var(--el-text-color-secondary);
}

.quickstart-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: var(--space-3);
}

.ai-stats-card {
  cursor: pointer;
}

.ai-stats-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: var(--space-2);
}

.ai-metric-item {
  border: 1px solid var(--ui-border-soft);
  border-radius: 10px;
  padding: 12px;
  background: var(--ui-surface-1);
}

.ai-metric-item.danger .ai-metric-value {
  color: var(--el-color-danger);
}

.ai-metric-value {
  font-size: 22px;
  font-weight: 700;
  line-height: 1.2;
  color: var(--el-color-primary);
}

.ai-metric-label {
  margin-top: 4px;
  font-size: var(--font-size-xs);
  color: var(--el-text-color-secondary);
}

.metric-delta {
  margin-top: 4px;
  font-size: 11px;
  line-height: 1.2;
}

.metric-delta.up {
  color: var(--el-color-danger);
}

.metric-delta.down {
  color: var(--el-color-success);
}

.metric-delta.flat {
  color: var(--el-text-color-secondary);
}

.ai-stats-footnote {
  margin-top: 10px;
  font-size: var(--font-size-xs);
  color: var(--el-text-color-secondary);
}

.trend-block {
  margin-top: 12px;
}

.trend-title {
  font-size: var(--font-size-xs);
  color: var(--el-text-color-secondary);
  margin-bottom: 8px;
}

.trend-grid {
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  gap: 8px;
}

.trend-day {
  border: 1px solid var(--ui-border-soft);
  border-radius: 8px;
  padding: 8px;
  background: var(--ui-surface-1);
}

.trend-date {
  font-size: 11px;
  color: var(--el-text-color-secondary);
  margin-bottom: 6px;
}

.trend-row {
  display: grid;
  grid-template-columns: 30px 1fr 44px;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
}

.trend-k {
  font-size: 11px;
  color: var(--el-text-color-secondary);
}

.trend-v {
  font-size: 11px;
  text-align: right;
}

.trend-bar-wrap {
  height: 6px;
  border-radius: 999px;
  background: var(--el-fill-color-light);
  overflow: hidden;
}

.trend-bar {
  height: 100%;
  border-radius: 999px;
}

.trend-bar.calls {
  background: var(--el-color-primary);
}

.trend-bar.latency {
  background: var(--el-color-warning);
}

.trend-bar.fail {
  background: var(--el-color-danger);
}

@media (max-width: 960px) {
  .ai-stats-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .trend-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

.qs-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 20px 12px;
  border-radius: 12px;
  border: 1px solid var(--ui-border-soft);
  cursor: pointer;
  transition: all 0.15s;
  font-size: var(--font-size-sm);
}

.qs-item:hover {
  background: var(--el-color-primary-light-9);
  border-color: var(--el-color-primary-light-5);
  color: var(--el-color-primary);
}

.data-quality-card {
  border: 1px solid var(--ui-border-soft);
}

.dq-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
}

.dq-item {
  text-align: center;
}

.dq-number {
  font-size: 22px;
  font-weight: 700;
  color: var(--el-text-color-primary);
}

.dq-label {
  font-size: var(--font-size-xs);
  color: var(--el-text-color-secondary);
  margin-top: 2px;
}

.dq-warnings {
  margin-top: 14px;
  display: grid;
  gap: 6px;
}

.dq-warning-item {
  font-size: var(--font-size-xs);
  color: var(--el-color-warning-dark-2);
  padding: 6px 10px;
  background: var(--el-color-warning-light-9);
  border-radius: 6px;
}

@media (max-width: 960px) {
  .dq-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
