<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  getPracticeFaqClusters,
  practiceFaqCopilot,
  practiceFaqSearch,
  type PracticeCopilotQualityMode,
  type PracticeFaqMatchedItem,
  type PracticeFaqClusterItem,
} from '../../api/practice'

const query = ref('')
const loading = ref(false)
const reply = ref('')
const latencyMs = ref(0)
const confidence = ref(0)
const matchedFaqs = ref<PracticeFaqMatchedItem[]>([])
const qualityMode = ref<PracticeCopilotQualityMode>('auto')
const qualityModeEffective = ref<'fast' | 'balanced' | 'quality' | ''>('')
const qualityRouteReason = ref('')

const reasonLabel = (reason: string) => {
  if (reason === 'auto:short_query') return '短问句，自动切到极速'
  if (reason === 'auto:risk_keyword') return '命中风险词（费用/医保/疗程等），自动切到高质量'
  if (reason === 'auto:default_balanced') return '常规问题，自动走平衡'
  if (reason === 'manual:fast') return '手动指定极速'
  if (reason === 'manual:balanced') return '手动指定平衡'
  if (reason === 'manual:quality') return '手动指定高质量'
  return reason
}

const searchOnlyLoading = ref(false)
const searchOnlyLatencyMs = ref(0)

const listKeyword = ref('')
const listCategory = ref('')
const listLoading = ref(false)
const listRows = ref<PracticeFaqClusterItem[]>([])
const listTotal = ref(0)
const listPage = ref(1)
const listPageSize = ref(8)
const listCategories = ref<string[]>([])

const runCopilot = async () => {
  const q = query.value.trim()
  if (!q) {
    ElMessage.warning('请输入患者问题')
    return
  }
  loading.value = true
  reply.value = ''
  latencyMs.value = 0
  confidence.value = 0
  matchedFaqs.value = []
  qualityModeEffective.value = ''
  qualityRouteReason.value = ''
  try {
    const data = await practiceFaqCopilot(q, qualityMode.value)
    reply.value = data.recommended_reply || '暂未生成建议回复'
    latencyMs.value = Number(data.latency_ms || 0)
    confidence.value = Number(data.confidence || 0)
    matchedFaqs.value = Array.isArray(data.matched_faqs) ? data.matched_faqs : []
    qualityModeEffective.value = data.quality_mode_effective || ''
    qualityRouteReason.value = reasonLabel(data.quality_route_reason || '')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || 'AI问答失败，请稍后重试')
  } finally {
    loading.value = false
  }
}

const runSearchOnly = async () => {
  const q = query.value.trim()
  if (!q) {
    ElMessage.warning('请输入患者问题')
    return
  }
  searchOnlyLoading.value = true
  reply.value = ''
  confidence.value = 0
  latencyMs.value = 0
  matchedFaqs.value = []
  try {
    const data = await practiceFaqSearch(q, 10)
    matchedFaqs.value = Array.isArray(data.results) ? data.results : []
    searchOnlyLatencyMs.value = Number(data.latency_ms || 0)
    if (!matchedFaqs.value.length) ElMessage.info('未找到匹配条目，可换个问法再试')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '语义搜索失败，请稍后重试')
  } finally {
    searchOnlyLoading.value = false
  }
}

const loadLibrary = async () => {
  listLoading.value = true
  try {
    const data = await getPracticeFaqClusters({
      keyword: listKeyword.value.trim() || undefined,
      category: listCategory.value || undefined,
      page: listPage.value,
      page_size: listPageSize.value,
    })
    listRows.value = data.items || []
    listTotal.value = Number(data.total || 0)
    listCategories.value = data.categories || []
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '加载知识条目失败')
  } finally {
    listLoading.value = false
  }
}

const onListSearch = () => {
  listPage.value = 1
  loadLibrary()
}

const handleListPageChange = (p: number) => {
  listPage.value = p
  loadLibrary()
}

onMounted(() => {
  loadLibrary()
})
</script>

<template>
  <div class="student-faq-page">
    <el-alert
      type="success"
      :closable="false"
      show-icon
      title="使用建议：左侧先问，右侧先看。可先浏览常见问答，再快速输出推荐回复。"
    />
    <div class="two-col">
      <el-card shadow="never" class="left-panel">
        <template #header>
          <div class="card-header">
            <strong>直接搜索问答</strong>
            <span class="desc">与后台同源：Embedding + 语义召回 + AI推荐回复</span>
          </div>
        </template>
        <div class="ask-row">
          <el-input
            v-model="query"
            size="large"
            clearable
            placeholder="例如：你们医院地址在哪里？可以医保报销吗？"
            @keyup.enter="runCopilot"
          />
          <el-button type="primary" size="large" :loading="loading" @click="runCopilot">AI推荐</el-button>
          <el-button size="large" :loading="searchOnlyLoading" @click="runSearchOnly">仅搜索</el-button>
        </div>
        <div class="quality-switch">
          <el-radio-group v-model="qualityMode" size="small">
            <el-radio-button value="auto">自动</el-radio-button>
            <el-radio-button value="fast">极速</el-radio-button>
            <el-radio-button value="balanced">平衡</el-radio-button>
            <el-radio-button value="quality">高质量</el-radio-button>
          </el-radio-group>
          <span class="desc">
            {{
              qualityMode === 'auto'
                ? '自动路由：短问句->极速，费用/医保等风险词->高质量，其余->平衡'
                : qualityMode === 'fast'
                ? '极速：qwen-turbo，响应更快'
                : qualityMode === 'quality'
                ? '高质量：qwen3-max，更稳更准'
                : '平衡：qwen-plus，日常推荐'
            }}
          </span>
        </div>
        <div class="desc">
          <template v-if="latencyMs">推荐耗时 {{ (latencyMs / 1000).toFixed(1) }}s</template>
          <template v-if="searchOnlyLatencyMs">｜搜索耗时 {{ (searchOnlyLatencyMs / 1000).toFixed(1) }}s</template>
          <template v-if="confidence">｜置信度 {{ (confidence * 100).toFixed(0) }}%</template>
          <template v-if="qualityModeEffective">｜实际模式 {{ qualityModeEffective }}</template>
        </div>
        <div v-if="qualityRouteReason" class="desc">路由依据：{{ qualityRouteReason }}</div>

        <el-card v-if="reply || loading" shadow="never" class="inner-card">
          <template #header><strong>推荐回复</strong></template>
          <div class="reply-box">{{ loading ? 'AI 生成中...' : reply }}</div>
        </el-card>

        <el-card v-if="matchedFaqs.length" shadow="never" class="inner-card">
          <template #header>
            <div class="card-header">
              <strong>匹配条目</strong>
              <span class="desc">{{ matchedFaqs.length }} 条</span>
            </div>
          </template>
          <div class="matched-list">
            <div v-for="item in matchedFaqs" :key="item.cluster_id" class="matched-item">
              <div class="matched-title">
                {{ item.title }}
                <el-tag size="small" type="info">{{ (item.similarity * 100).toFixed(0) }}%</el-tag>
              </div>
              <div v-if="item.representative_question" class="matched-q">{{ item.representative_question }}</div>
              <div v-if="item.best_answer" class="matched-a">{{ item.best_answer }}</div>
            </div>
          </div>
        </el-card>
      </el-card>

      <el-card shadow="never" class="right-panel">
        <template #header>
          <div class="card-header">
            <strong>知识条目预览</strong>
            <span class="desc">先熟悉高频问题，快速熟悉业务</span>
          </div>
        </template>
        <div class="lib-toolbar">
          <el-input v-model="listKeyword" clearable placeholder="搜索标题/问题/答案关键词" @keyup.enter="onListSearch" />
          <el-select v-model="listCategory" clearable placeholder="全部分类" style="width: 150px" @change="onListSearch">
            <el-option v-for="c in listCategories" :key="c" :label="c" :value="c" />
          </el-select>
          <el-button :loading="listLoading" @click="onListSearch">查询</el-button>
        </div>
        <el-table :data="listRows" v-loading="listLoading" size="small" stripe>
          <el-table-column prop="title" label="标题" min-width="220" />
          <el-table-column prop="category" label="分类" width="120" />
          <el-table-column label="代表问题" min-width="220">
            <template #default="{ row }">
              <span class="table-text">{{ row.representative_question || '-' }}</span>
            </template>
          </el-table-column>
        </el-table>
        <div class="pager">
          <el-pagination
            background
            layout="prev, pager, next, total"
            :total="listTotal"
            :page-size="listPageSize"
            :current-page="listPage"
            @current-change="handleListPageChange"
          />
        </div>
      </el-card>
    </div>
  </div>
</template>

<style scoped>
.student-faq-page { display: grid; gap: 12px; }
.two-col { display: grid; grid-template-columns: 1.1fr 1fr; gap: 12px; align-items: start; }
.card-header { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.desc { font-size: 12px; color: var(--el-text-color-secondary); }
.ask-row { display: flex; gap: 8px; margin-bottom: 8px; }
.quality-switch { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; flex-wrap: wrap; }
.inner-card { margin-top: 10px; }
.reply-box { white-space: pre-wrap; line-height: 1.7; color: var(--el-text-color-primary); }
.matched-list { display: grid; gap: 10px; max-height: 340px; overflow: auto; }
.matched-item { border: 1px solid var(--ui-border-soft); border-radius: 10px; padding: 10px 12px; }
.matched-title { display: flex; align-items: center; gap: 8px; font-weight: 600; }
.matched-q { margin-top: 4px; color: var(--el-color-primary); font-size: 13px; }
.matched-a { margin-top: 4px; color: var(--el-text-color-secondary); font-size: 13px; }
.lib-toolbar { display: grid; grid-template-columns: 1fr 150px 80px; gap: 8px; margin-bottom: 10px; }
.table-text { color: var(--el-text-color-secondary); }
.pager { margin-top: 10px; display: flex; justify-content: flex-end; }
@media (max-width: 1200px) {
  .two-col { grid-template-columns: 1fr; }
}
</style>
