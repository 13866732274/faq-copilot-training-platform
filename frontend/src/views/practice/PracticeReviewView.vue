<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { getPracticeAiScore, reviewPractice, type PracticeAiScoreData, type ReviewDialogue } from '../../api/practice'
import PracticeComparePanel from '../../components/practice/PracticeComparePanel.vue'

const route = useRoute()
const router = useRouter()
const practiceId = Number(route.params.id)
const loading = ref(false)
const title = ref('')
const dialogues = ref<ReviewDialogue[]>([])
const comments = ref<Array<{ comment_id: number; admin_name: string; content: string; created_at: string }>>([])
const aiScoreLoading = ref(false)
const aiScore = ref<PracticeAiScoreData | null>(null)
const aiScoreDisabledMsg = ref('')
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

const metricRounds = computed(() => dialogues.value.length)
const metricComments = computed(() => comments.value.length)
const metricRecentUpdateRaw = computed(() => {
  return getLatestTime([
    ...comments.value.map((item) => item.created_at),
    ...dialogues.value.map((round) => round.student_reply?.reply_time),
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

const scoreDimensionItems = computed(() => {
  const dims = aiScore.value?.dimension_scores || {}
  const mapping: Array<{ key: string; label: string }> = [
    { key: 'task_completion', label: '任务完成度' },
    { key: 'semantic_alignment', label: '语义贴合度' },
    { key: 'keypoint_coverage', label: '关键点命中' },
    { key: 'communication_quality', label: '沟通质量' },
    { key: 'risk_control', label: '风险控制' },
  ]
  return mapping
    .filter((item) => typeof dims[item.key] === 'number')
    .map((item) => ({ ...item, score: Number(dims[item.key] || 0) }))
})

const load = async () => {
  loading.value = true
  aiScore.value = null
  aiScoreDisabledMsg.value = ''
  try {
    const data = await reviewPractice(practiceId)
    title.value = data.quiz_title
    dialogues.value = data.dialogues
    comments.value = data.comments || []
    aiScoreLoading.value = true
    try {
      aiScore.value = await getPracticeAiScore(practiceId)
    } catch (error: any) {
      const status = error?.response?.status
      if (status === 403) {
        aiScoreDisabledMsg.value = error?.response?.data?.detail || 'AI评分能力当前不可用'
      } else if (status === 400) {
        aiScoreDisabledMsg.value = error?.response?.data?.detail || '当前练习暂不支持评分'
      } else {
        aiScoreDisabledMsg.value = 'AI评分暂时不可用'
      }
    } finally {
      aiScoreLoading.value = false
    }
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || '获取答案对比失败')
  } finally {
    loading.value = false
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
            <strong class="result-title">{{ title }}</strong>
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
          <el-button class="result-back-btn" @click="router.push('/practice')">返回列表</el-button>
        </div>
      </div>
    </template>
    <PracticeComparePanel :dialogues="dialogues" />

    <el-card shadow="never" class="score-card">
      <template #header>
        <div class="score-card-header">
          <span>AI 评分</span>
          <el-tag v-if="aiScore" type="success">已生成</el-tag>
          <el-tag v-else type="info">未启用</el-tag>
        </div>
      </template>
      <div v-loading="aiScoreLoading">
        <template v-if="aiScore">
          <div class="score-main">
            <div class="score-value">{{ aiScore.overall_score }}</div>
            <div class="score-meta">综合评分（100分）</div>
          </div>
          <div class="score-metrics">
            <div class="score-row">
              <span>回复覆盖率</span>
              <el-progress :percentage="aiScore.completion_rate" :stroke-width="10" />
            </div>
            <div class="score-row">
              <span>平均回复长度</span>
              <span class="score-right">{{ aiScore.avg_reply_length }} 字</span>
            </div>
            <div class="score-row">
              <span>共情命中次数</span>
              <span class="score-right">{{ aiScore.empathy_hits }}</span>
            </div>
          </div>
          <div class="score-suggestions">
            <div v-for="(tip, idx) in aiScore.suggestions" :key="idx" class="score-tip">
              {{ tip }}
            </div>
          </div>
          <div v-if="scoreDimensionItems.length" class="score-dimension-block">
            <div class="score-subtitle">五维评分明细</div>
            <div class="score-dimension-list">
              <div v-for="item in scoreDimensionItems" :key="item.key" class="score-dimension-item">
                <span class="score-dimension-label">{{ item.label }}</span>
                <el-progress :percentage="item.score" :stroke-width="8" />
              </div>
            </div>
          </div>
          <div v-if="aiScore.deduction_reasons?.length" class="score-deduction-block">
            <div class="score-subtitle">扣分原因</div>
            <div class="score-deduction-item" v-for="(reason, idx) in aiScore.deduction_reasons" :key="idx">
              {{ reason }}
            </div>
          </div>
          <div v-if="aiScore.llm_audit" class="llm-audit-block">
            <div class="score-subtitle">
              LLM 审核（{{ aiScore.llm_audit.model || 'qwen3-max' }}）
              <el-tag
                v-if="aiScore.llm_audit.status === 'success'"
                type="success"
                size="small"
                style="margin-left: 8px"
              >已完成</el-tag>
              <el-tag
                v-else-if="aiScore.llm_audit.status === 'error'"
                type="danger"
                size="small"
                style="margin-left: 8px"
              >异常</el-tag>
              <el-tag
                v-else-if="aiScore.llm_audit.status === 'not_configured'"
                type="info"
                size="small"
                style="margin-left: 8px"
              >未配置</el-tag>
              <el-tag
                v-else
                type="warning"
                size="small"
                style="margin-left: 8px"
              >{{ aiScore.llm_audit.status }}</el-tag>
              <span v-if="aiScore.llm_audit.latency_ms" class="llm-latency">
                {{ aiScore.llm_audit.latency_ms }}ms
              </span>
            </div>
            <template v-if="aiScore.llm_audit.status === 'success'">
              <div v-if="aiScore.llm_audit.summary" class="llm-summary">
                {{ aiScore.llm_audit.summary }}
              </div>
              <div v-if="aiScore.llm_audit.highlights?.length" class="llm-highlights">
                <span class="llm-hl-label">亮点：</span>
                <el-tag
                  v-for="(hl, i) in aiScore.llm_audit.highlights"
                  :key="i"
                  type="success"
                  size="small"
                  class="llm-hl-tag"
                >{{ hl }}</el-tag>
              </div>
              <div v-if="aiScore.llm_audit.fusion_weights" class="llm-fusion-info">
                融合权重：规则 {{ Math.round((aiScore.llm_audit.fusion_weights.rule || 0.7) * 100) }}% ·
                LLM {{ Math.round((aiScore.llm_audit.fusion_weights.llm || 0.3) * 100) }}%
              </div>
            </template>
            <template v-else-if="aiScore.llm_audit.error">
              <el-alert
                class="llm-hint-alert"
                type="warning"
                :closable="false"
                show-icon
                :title="aiScore.llm_audit.error"
                description="当前使用纯规则评分，LLM审核维度暂不可用。"
              />
            </template>
            <template v-else>
              <el-alert
                class="llm-hint-alert"
                type="info"
                :closable="false"
                show-icon
                title="LLM 审核未配置"
                description="系统管理员可在 .env 中配置 DASHSCOPE_API_KEY 以启用 LLM Rubric 审核。"
              />
            </template>
          </div>
        </template>
        <el-empty v-else :description="aiScoreDisabledMsg || 'AI评分未开启'" />
      </div>
    </el-card>

    <el-card shadow="never" class="comment-card">
      <template #header>
        <div class="comment-card-header">
          <span>管理员点评</span>
          <span class="comment-total">共 {{ comments.length }} 条</span>
        </div>
      </template>
      <el-empty v-if="!comments.length" description="暂无点评" />
      <div v-for="c in comments" :key="c.comment_id" class="comment-item">
        <div class="comment-meta">
          <strong class="comment-admin">{{ c.admin_name }}</strong>
          <span class="comment-time">{{ c.created_at }}</span>
        </div>
        <div class="comment-content">{{ c.content }}</div>
      </div>
    </el-card>
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

.score-card {
  margin-top: var(--space-3);
}

.score-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.score-main {
  display: grid;
  justify-items: center;
  margin-bottom: var(--space-3);
}

.score-value {
  font-size: 46px;
  line-height: 1;
  font-weight: 800;
  color: var(--el-color-primary);
}

.score-meta {
  margin-top: 6px;
  color: var(--el-text-color-secondary);
  font-size: var(--font-size-xs);
}

.score-metrics {
  display: grid;
  gap: var(--space-2);
}

.score-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
}

.score-row > span:first-child {
  color: var(--el-text-color-secondary);
  min-width: 88px;
}

.score-right {
  color: var(--el-text-color-primary);
  font-weight: 600;
}

.score-suggestions {
  margin-top: var(--space-3);
  display: grid;
  gap: 6px;
}

.score-tip {
  border: 1px solid var(--ui-border-soft);
  border-radius: var(--radius-sm);
  padding: 8px 10px;
  background: color-mix(in srgb, var(--ui-surface-1) 94%, #fff 6%);
  font-size: var(--font-size-sm);
}

.score-subtitle {
  margin-bottom: 6px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.score-dimension-block {
  margin-top: var(--space-3);
}

.score-dimension-list {
  display: grid;
  gap: 8px;
}

.score-dimension-item {
  display: grid;
  gap: 4px;
}

.score-dimension-label {
  font-size: var(--font-size-xs);
  color: var(--el-text-color-secondary);
}

.score-deduction-block {
  margin-top: var(--space-3);
}

.score-deduction-item {
  border: 1px solid color-mix(in srgb, var(--el-color-warning) 30%, var(--ui-border-soft) 70%);
  border-radius: var(--radius-sm);
  padding: 6px 10px;
  background: color-mix(in srgb, var(--el-color-warning-light-9) 76%, transparent 24%);
  font-size: var(--font-size-xs);
}

.score-deduction-item + .score-deduction-item {
  margin-top: 6px;
}

.llm-audit-block {
  margin-top: var(--space-3);
  padding: 12px 14px;
  border-radius: var(--radius-m);
  background: color-mix(in srgb, var(--el-color-primary) 4%, var(--ui-card-bg) 96%);
  border: 1px solid color-mix(in srgb, var(--el-color-primary) 12%, var(--ui-border-soft) 88%);
}

.llm-summary {
  margin-top: 8px;
  font-size: var(--font-size-s);
  color: var(--el-text-color-primary);
  line-height: 1.6;
}

.llm-highlights {
  margin-top: 8px;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
}

.llm-hl-label {
  font-size: var(--font-size-xs);
  color: var(--el-text-color-secondary);
}

.llm-hl-tag {
  margin: 0;
}

.llm-fusion-info {
  margin-top: 8px;
  font-size: var(--font-size-xs);
  color: var(--el-text-color-secondary);
}

.llm-latency {
  margin-left: 8px;
  font-size: var(--font-size-xs);
  color: var(--el-text-color-secondary);
  font-weight: 400;
}

.llm-hint-alert {
  margin-top: 8px;
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

.comment-content {
  color: var(--el-text-color-regular);
  line-height: var(--line-height-base);
  white-space: pre-wrap;
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
}
</style>
