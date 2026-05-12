<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  faqCopilotPanel,
  type CopilotQualityMode,
  type CopilotPanelData,
  type CopilotEfficiency7dData,
  getCopilotEfficiency7d,
  faqCopilotStream,
  faqSearch,
  type FaqSearchResult,
  submitCopilotFeedback,
} from '../../api/faq'

const route = useRoute()
const router = useRouter()
const query = ref('')
const searching = ref(false)
const mode = ref<'copilot' | 'search'>('copilot')
const qualityMode = ref<CopilotQualityMode>('auto')
const resolvedMode = ref<'fast' | 'balanced' | 'quality' | ''>('')
const routeReason = ref('')

const reasonLabel = (reason: string) => {
  if (reason === 'auto:risk_keyword') return '命中高风险关键词（费用/医保/疗程等），自动切换高质量模型 qwen3-max'
  if (reason === 'auto:short_query') return '短问句（≤4字），自动使用极速模型 qwen-turbo'
  if (reason === 'auto:default_balanced') return '普通问题，自动使用平衡模型 qwen-plus'
  if (reason === 'manual:fast') return '手动极速 → qwen-turbo（最快响应，适合简单查询）'
  if (reason === 'manual:balanced') return '手动平衡 → qwen-plus（推荐，兼顾速度与质量）'
  if (reason === 'manual:quality') return '手动高质量 → qwen3-max（最精准，适合复杂/敏感问题）'
  return reason
}
const streamReply = ref('')
const streamFaqs = ref<FaqSearchResult[]>([])
const streamLatency = ref(0)
const searchResults = ref<FaqSearchResult[]>([])
const searchLatency = ref(0)
const streamDone = ref(false)
const panelData = ref<CopilotPanelData | null>(null)
const feedbackText = ref('')
const report = ref<CopilotEfficiency7dData | null>(null)
const reportLoading = ref(false)
const queryStartAt = ref(0)

const loadEfficiencyReport = async () => {
  reportLoading.value = true
  try {
    report.value = await getCopilotEfficiency7d()
  } catch {
    report.value = null
  } finally {
    reportLoading.value = false
  }
}

const sendFeedback = async (action: 'accepted' | 'edited' | 'rejected', index = 0, reply = '') => {
  if (!panelData.value) return
  const firstResponseMs = panelData.value.latency_ms || Math.max(0, Date.now() - queryStartAt.value)
  await submitCopilotFeedback({
    panel_id: panelData.value.panel_id,
    action,
    candidate_index: index,
    final_reply: reply || undefined,
    first_response_ms: firstResponseMs,
    session_duration_ms: Math.max(firstResponseMs, Date.now() - queryStartAt.value),
    channel: 'admin_faq_copilot',
  })
  ElMessage.success(
    action === 'accepted' ? '已记录：采纳' : action === 'edited' ? '已记录：改写采纳' : '已记录：拒绝',
  )
  feedbackText.value = ''
  await loadEfficiencyReport()
}

const handleSubmit = async () => {
  const q = query.value.trim()
  if (!q) {
    ElMessage.warning('请输入患者问题')
    return
  }
  searching.value = true
  streamReply.value = ''
  streamFaqs.value = []
  streamLatency.value = 0
  resolvedMode.value = ''
  routeReason.value = ''
  streamDone.value = false
  panelData.value = null
  feedbackText.value = ''
  queryStartAt.value = Date.now()
  searchResults.value = []
  searchLatency.value = 0

  try {
    if (mode.value === 'copilot') {
      panelData.value = await faqCopilotPanel(q, qualityMode.value)
      await faqCopilotStream(q, {
        onFaqs: (faqs) => {
          streamFaqs.value = faqs
        },
        onToken: (token) => {
          streamReply.value += token
        },
        onDone: (ms, _requested, effective, reason) => {
          streamLatency.value = ms
          resolvedMode.value = effective || ''
          routeReason.value = reasonLabel(reason || '')
          streamDone.value = true
          searching.value = false
        },
        onError: (err) => {
          ElMessage.error(err)
          searching.value = false
        },
      }, qualityMode.value)
      if (!streamDone.value) searching.value = false
    } else {
      const data = await faqSearch(q, 10)
      searchResults.value = data.results
      searchLatency.value = (data as any).latency_ms || 0
      searching.value = false
    }
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '查询失败，请检查 Dashscope API Key 是否已配置')
    searching.value = false
  }
}

onMounted(() => {
  loadEfficiencyReport()
  const q = route.query.q
  if (typeof q === 'string' && q.trim()) {
    query.value = q.trim()
    handleSubmit()
  }
})
</script>

<template>
  <div class="copilot-page">
    <div class="copilot-header">
      <strong class="copilot-title">AI 问答助手</strong>
      <p class="copilot-desc">输入患者的问题，AI 将从知识库中匹配相关 FAQ 并给出推荐回复。</p>
    </div>

    <el-card shadow="never" class="eff-card">
      <template #header>
        <div class="result-header">
          <strong>7天真实提效报表</strong>
          <el-button text size="small" :loading="reportLoading" @click="loadEfficiencyReport">刷新</el-button>
        </div>
      </template>
      <div v-if="report" class="eff-grid">
        <div class="eff-item"><span>总反馈</span><strong>{{ report.total_feedback }}</strong></div>
        <div class="eff-item"><span>采纳率</span><strong>{{ report.accept_rate }}%</strong></div>
        <div class="eff-item"><span>平均首响</span><strong>{{ (report.avg_first_response_ms / 1000).toFixed(1) }}s</strong></div>
        <div class="eff-item"><span>单会话耗时</span><strong>{{ (report.avg_session_duration_ms / 1000).toFixed(1) }}s</strong></div>
        <div class="eff-item"><span>人工负载下降</span><strong>{{ report.labor_reduction_pct }}%</strong></div>
      </div>
      <div v-else class="search-hint">暂无近7天提效数据，请先进行采纳/改写/拒绝打点。</div>
    </el-card>

    <div class="search-section">
      <div class="mode-switch">
        <el-radio-group v-model="mode" size="small">
          <el-radio-button value="copilot">AI 推荐回复</el-radio-button>
          <el-radio-button value="search">语义搜索</el-radio-button>
        </el-radio-group>
      </div>
      <div v-if="mode === 'copilot'" class="quality-switch">
        <el-radio-group v-model="qualityMode" size="small">
          <el-radio-button value="auto">自动</el-radio-button>
          <el-radio-button value="fast">极速</el-radio-button>
          <el-radio-button value="balanced">平衡</el-radio-button>
          <el-radio-button value="quality">高质量</el-radio-button>
        </el-radio-group>
        <span class="quality-hint">
          {{
            qualityMode === 'auto'
              ? '智能路由：≤4字极速(qwen-turbo)、费用/医保等高质量(qwen3-max)、其余平衡(qwen-plus)'
              : qualityMode === 'fast'
              ? 'qwen-turbo：最快响应（~1-2s），适合简短查询'
              : qualityMode === 'quality'
                ? 'qwen3-max：最精准匹配，响应稍慢（~3-5s），适合复杂/敏感问题'
                : 'qwen-plus：兼顾速度与质量（~2-3s），日常推荐'
          }}
        </span>
      </div>
      <div class="search-input-row">
        <el-input
          v-model="query"
          placeholder="输入患者问题，如：你们医院地址在哪里？"
          size="large"
          clearable
          @keyup.enter="handleSubmit"
          class="search-input"
        >
          <template #prefix>
            <span class="search-icon">🔍</span>
          </template>
        </el-input>
        <el-button type="primary" size="large" :loading="searching" @click="handleSubmit">
          {{ mode === 'copilot' ? '获取推荐回复' : '搜索' }}
        </el-button>
      </div>
      <div class="search-hint">
        提示：输入患者的原始问题，系统会自动匹配意思相近的 FAQ，即使措辞完全不同也能识别。
      </div>
    </div>

    <div v-if="searching && !streamReply" class="loading-state">
      <el-icon class="is-loading" :size="24"><Loading /></el-icon>
      <span>{{ mode === 'copilot' ? '正在匹配知识库...' : '正在语义搜索...' }}</span>
    </div>

    <template v-if="(streamReply || streamDone) && mode === 'copilot'">
      <el-card shadow="never" class="copilot-result-card">
        <template #header>
          <div class="result-header">
            <strong>AI 推荐回复</strong>
            <span v-if="streamLatency" class="latency-text">
              耗时 {{ (streamLatency / 1000).toFixed(1) }}s
            </span>
            <el-tag v-if="resolvedMode" size="small" type="info">
              实际模式：{{ resolvedMode === 'quality' ? '高质量' : resolvedMode === 'balanced' ? '平衡' : '极速' }}
            </el-tag>
            <el-tag v-if="searching" type="warning" size="small">生成中...</el-tag>
          </div>
        </template>
        <div class="recommended-reply">{{ streamReply }}<span v-if="searching" class="typing-cursor">|</span></div>
        <div v-if="routeReason" class="quality-hint">路由依据：{{ routeReason }}</div>
      </el-card>

      <el-card v-if="panelData && panelData.candidates.length" shadow="never">
        <template #header>
          <div class="result-header">
            <strong>快捷回复面板（可直接发送）</strong>
            <span class="latency-text">面板生成耗时 {{ (panelData.latency_ms / 1000).toFixed(1) }}s</span>
          </div>
        </template>
        <div class="panel-list">
          <div v-for="(candidate, idx) in panelData.candidates" :key="idx" class="panel-item">
            <div class="panel-reply">{{ candidate }}</div>
            <div class="panel-actions">
              <el-button size="small" type="success" @click="sendFeedback('accepted', idx, candidate)">采纳</el-button>
              <el-button size="small" @click="sendFeedback('rejected', idx)">拒绝</el-button>
            </div>
          </div>
        </div>
        <div class="edit-row">
          <el-input v-model="feedbackText" placeholder="如有改写后发送文案，可粘贴到这里后点击“改写采纳”" />
          <el-button
            size="small"
            type="primary"
            :disabled="!feedbackText.trim()"
            @click="sendFeedback('edited', 0, feedbackText)"
          >
            改写采纳
          </el-button>
        </div>
      </el-card>

      <div v-if="streamFaqs.length > 0" class="matched-section">
        <strong class="section-title">匹配的 FAQ 条目（{{ streamFaqs.length }} 条）</strong>
        <div class="matched-list">
          <div
            v-for="faq in streamFaqs"
            :key="faq.cluster_id"
            class="matched-item"
            @click="router.push(`/admin/faq/clusters/${faq.cluster_id}`)"
          >
            <div class="matched-title">
              {{ faq.title }}
              <el-tag size="small" type="info">{{ (faq.similarity * 100).toFixed(0) }}% 相似</el-tag>
            </div>
            <div v-if="faq.representative_question" class="matched-question">{{ faq.representative_question }}</div>
            <div v-if="faq.best_answer" class="matched-answer">{{ faq.best_answer }}</div>
          </div>
        </div>
      </div>
    </template>

    <template v-if="searchResults.length > 0 && mode === 'search'">
      <div class="matched-section">
        <strong class="section-title">
          搜索结果（{{ searchResults.length }} 条）
          <span v-if="searchLatency" class="latency-text">耗时 {{ (searchLatency / 1000).toFixed(1) }}s</span>
        </strong>
        <div class="matched-list">
          <div
            v-for="faq in searchResults"
            :key="faq.cluster_id"
            class="matched-item"
            @click="router.push(`/admin/faq/clusters/${faq.cluster_id}`)"
          >
            <div class="matched-title">
              {{ faq.title }}
              <el-tag v-if="faq.category" size="small">{{ faq.category }}</el-tag>
              <el-tag size="small" type="info">{{ (faq.similarity * 100).toFixed(0) }}%</el-tag>
            </div>
            <div v-if="faq.representative_question" class="matched-question">{{ faq.representative_question }}</div>
            <div v-if="faq.best_answer" class="matched-answer">{{ faq.best_answer }}</div>
          </div>
        </div>
      </div>
    </template>

    <div
      v-if="!searching && !streamReply && searchResults.length === 0 && query.trim() && streamDone"
      class="no-result"
    >
      暂无匹配结果，请确保已生成 FAQ 知识库。
    </div>
  </div>
</template>

<script lang="ts">
import { Loading } from '@element-plus/icons-vue'
export default { components: { Loading } }
</script>

<style scoped>
.copilot-page {
  display: grid;
  gap: var(--space-4);
  max-width: 900px;
}

.copilot-header {
  display: grid;
  gap: 4px;
}

.copilot-title {
  font-size: var(--font-size-h4);
}

.copilot-desc {
  margin: 0;
  color: var(--el-text-color-secondary);
  font-size: var(--font-size-sm);
}

.search-section {
  display: grid;
  gap: var(--space-2);
}

.mode-switch {
  display: flex;
}

.quality-switch {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.quality-hint {
  font-size: var(--font-size-xs);
  color: var(--el-text-color-secondary);
}

.search-input-row {
  display: flex;
  gap: var(--space-2);
}

.search-input {
  flex: 1;
}

.search-icon {
  font-size: 16px;
}

.search-hint {
  font-size: var(--font-size-xs);
  color: var(--el-text-color-placeholder);
}

.loading-state {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--el-color-primary);
  font-size: var(--font-size-sm);
  padding: 20px 0;
}

.copilot-result-card {
  border: 2px solid var(--el-color-primary-light-5);
}

.eff-card {
  border: 1px solid var(--ui-border-soft);
}

.eff-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(120px, 1fr));
  gap: 10px;
}

.eff-item {
  border: 1px solid var(--ui-border-soft);
  border-radius: 10px;
  padding: 10px;
  display: grid;
  gap: 4px;
}

.eff-item span {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.eff-item strong {
  font-size: 16px;
}

.result-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
}

.latency-text {
  font-size: var(--font-size-xs);
  color: var(--el-text-color-secondary);
}

.recommended-reply {
  font-size: 15px;
  line-height: 1.7;
  white-space: pre-wrap;
  padding: 8px 0;
}

.typing-cursor {
  animation: blink 0.8s step-end infinite;
  color: var(--el-color-primary);
  font-weight: bold;
}

@keyframes blink {
  50% { opacity: 0; }
}

.matched-section {
  display: grid;
  gap: var(--space-2);
}

.section-title {
  font-size: var(--font-size-sm);
  color: var(--el-text-color-secondary);
  display: flex;
  align-items: center;
  gap: 8px;
}

.matched-list {
  display: grid;
  gap: 10px;
}

.matched-item {
  padding: 14px 16px;
  border-radius: 12px;
  border: 1px solid var(--ui-border-soft);
  background: var(--ui-surface-1);
  cursor: pointer;
  transition: all 0.15s;
  display: grid;
  gap: 6px;
}

.matched-item:hover {
  border-color: var(--el-color-primary-light-5);
  box-shadow: var(--ui-shadow-soft);
}

.matched-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  font-size: var(--font-size-sm);
}

.matched-question {
  font-size: var(--font-size-xs);
  color: var(--el-color-primary);
}

.matched-answer {
  font-size: var(--font-size-xs);
  color: var(--el-text-color-secondary);
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.no-result {
  text-align: center;
  padding: 40px 0;
  color: var(--el-text-color-placeholder);
}

.panel-list {
  display: grid;
  gap: 10px;
}

.panel-item {
  border: 1px solid var(--ui-border-soft);
  border-radius: 10px;
  padding: 10px;
  display: grid;
  gap: 8px;
}

.panel-reply {
  white-space: pre-wrap;
  line-height: 1.65;
}

.panel-actions {
  display: flex;
  gap: 8px;
}

.edit-row {
  margin-top: 10px;
  display: flex;
  gap: 8px;
}
</style>
