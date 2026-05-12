<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { getTenants, type TenantItem } from '../../api/tenant'
import {
  getBillingMonthlyEstimate,
  getBillingRecords,
  getBillingSummary,
  getBillingTrend,
  type BillingMonthlyEstimateData,
} from '../../api/billing'

const loading = ref(false)
const trendLoading = ref(false)
const tableLoading = ref(false)
const estimateLoading = ref(false)
const tenants = ref<TenantItem[]>([])

const moduleOptions = [
  { label: '全部模块', value: '' },
  { label: '对话训练', value: 'mod_training' },
  { label: 'FAQ 知识库', value: 'mod_faq' },
  { label: 'AI 评分', value: 'mod_ai_scoring' },
  { label: '统计分析', value: 'mod_stats' },
  { label: '数据导出', value: 'mod_export' },
  { label: '审计增强', value: 'mod_audit' },
]

const form = reactive({
  tenant_id: undefined as number | undefined,
  module_id: '',
  days: 30,
  date_range: [] as string[],
  page: 1,
  page_size: 20,
})

const summary = ref<any>(null)
const trend = ref<any[]>([])
const records = ref<any[]>([])
const total = ref(0)
const estimate = ref<BillingMonthlyEstimateData | null>(null)

const queryParams = computed(() => ({
  tenant_id: form.tenant_id,
  module_id: form.module_id || undefined,
  start_date: form.date_range?.[0],
  end_date: form.date_range?.[1],
}))

const monthValue = computed(() => {
  const now = new Date()
  const yyyy = now.getFullYear()
  const mm = String(now.getMonth() + 1).padStart(2, '0')
  return `${yyyy}-${mm}`
})

const loadSummary = async () => {
  summary.value = await getBillingSummary(queryParams.value)
}

const loadTrend = async () => {
  trendLoading.value = true
  try {
    const data = await getBillingTrend({
      days: form.days,
      tenant_id: form.tenant_id,
      module_id: form.module_id || undefined,
    })
    trend.value = data.items || []
  } finally {
    trendLoading.value = false
  }
}

const loadRecords = async () => {
  tableLoading.value = true
  try {
    const data = await getBillingRecords({
      ...queryParams.value,
      page: form.page,
      page_size: form.page_size,
    })
    records.value = data.items || []
    total.value = data.total || 0
  } finally {
    tableLoading.value = false
  }
}

const loadEstimate = async () => {
  estimateLoading.value = true
  try {
    estimate.value = await getBillingMonthlyEstimate({
      month: monthValue.value,
      tenant_id: form.tenant_id,
      module_id: form.module_id || undefined,
    })
  } finally {
    estimateLoading.value = false
  }
}

const load = async () => {
  loading.value = true
  try {
    const [tenantData] = await Promise.all([getTenants()])
    tenants.value = tenantData.items || []
    await Promise.all([loadSummary(), loadTrend(), loadRecords(), loadEstimate()])
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || '计费中心数据加载失败')
  } finally {
    loading.value = false
  }
}

const search = async () => {
  form.page = 1
  try {
    await Promise.all([loadSummary(), loadTrend(), loadRecords(), loadEstimate()])
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || '查询失败')
  }
}

const reset = async () => {
  form.tenant_id = undefined
  form.module_id = ''
  form.days = 30
  form.date_range = []
  form.page = 1
  await search()
}

const onPageChange = async (page: number) => {
  form.page = page
  await loadRecords()
}

const onPageSizeChange = async (size: number) => {
  form.page_size = size
  form.page = 1
  await loadRecords()
}

onMounted(load)
</script>

<template>
  <el-card shadow="never" v-loading="loading">
    <template #header>
      <div class="admin-card-header">
        <strong class="admin-card-title">计费中心（基础版）</strong>
      </div>
    </template>

    <div class="filter-grid">
      <el-select v-model="form.tenant_id" clearable placeholder="租户筛选">
        <el-option v-for="t in tenants" :key="t.id" :label="`${t.name}（${t.code}）`" :value="t.id" />
      </el-select>
      <el-select v-model="form.module_id" placeholder="模块筛选">
        <el-option v-for="m in moduleOptions" :key="m.value || 'all'" :label="m.label" :value="m.value" />
      </el-select>
      <el-date-picker
        v-model="form.date_range"
        type="daterange"
        value-format="YYYY-MM-DD"
        start-placeholder="开始日期"
        end-placeholder="结束日期"
        unlink-panels
      />
      <el-select v-model="form.days" placeholder="趋势窗口（天）">
        <el-option :value="7" label="最近 7 天" />
        <el-option :value="30" label="最近 30 天" />
        <el-option :value="60" label="最近 60 天" />
      </el-select>
      <div class="filter-actions">
        <el-button type="primary" @click="search">查询</el-button>
        <el-button @click="reset">重置</el-button>
      </div>
    </div>

    <div v-if="summary" class="stats-grid">
      <div class="stat-card">
        <div class="stat-num">{{ summary.cards.total_requests }}</div>
        <div class="stat-label">请求总量</div>
      </div>
      <div class="stat-card">
        <div class="stat-num">{{ summary.cards.total_tenants }}</div>
        <div class="stat-label">活跃租户数</div>
      </div>
      <div class="stat-card">
        <div class="stat-num">{{ summary.cards.total_users }}</div>
        <div class="stat-label">活跃用户数</div>
      </div>
      <div class="stat-card">
        <div class="stat-num">{{ summary.cards.avg_duration_ms }}</div>
        <div class="stat-label">平均耗时(ms)</div>
      </div>
    </div>

    <div class="section-grid">
      <el-card shadow="never">
        <template #header><strong>按模块聚合</strong></template>
        <el-table :data="summary?.by_module || []" size="small" border>
          <el-table-column prop="label" label="模块" min-width="160" />
          <el-table-column prop="requests" label="请求量" width="120" />
          <el-table-column prop="ratio" label="占比(%)" width="120" />
        </el-table>
      </el-card>
      <el-card shadow="never">
        <template #header><strong>按租户聚合</strong></template>
        <el-table :data="summary?.by_tenant || []" size="small" border>
          <el-table-column prop="label" label="租户" min-width="160" />
          <el-table-column prop="requests" label="请求量" width="120" />
          <el-table-column prop="ratio" label="占比(%)" width="120" />
        </el-table>
      </el-card>
    </div>

    <el-card shadow="never" class="section-card" v-loading="trendLoading">
      <template #header><strong>时间趋势（按天）</strong></template>
      <el-table :data="trend" size="small" border>
        <el-table-column prop="day" label="日期" width="140" />
        <el-table-column prop="requests" label="请求量" width="120" />
        <el-table-column prop="avg_duration_ms" label="平均耗时(ms)" width="140" />
      </el-table>
    </el-card>

    <el-card shadow="never" class="section-card" v-loading="estimateLoading">
      <template #header><strong>费用试算（{{ estimate?.month || monthValue }}）</strong></template>
      <div v-if="estimate" class="estimate-cards">
        <div class="stat-card">
          <div class="stat-num">{{ estimate.total_requests }}</div>
          <div class="stat-label">本月计费请求量</div>
        </div>
        <div class="stat-card">
          <div class="stat-num">¥ {{ estimate.total_estimated_cost.toFixed(2) }}</div>
          <div class="stat-label">本月预估费用</div>
        </div>
      </div>
      <div class="section-grid">
        <el-card shadow="never">
          <template #header><strong>模块单价规则（元/请求）</strong></template>
          <el-table :data="estimate?.price_rules || []" size="small" border>
            <el-table-column prop="module_label" label="模块" min-width="140" />
            <el-table-column prop="module_id" label="模块ID" min-width="130" />
            <el-table-column prop="unit_price" label="单价" width="120">
              <template #default="{ row }">¥ {{ Number(row.unit_price || 0).toFixed(4) }}</template>
            </el-table-column>
          </el-table>
        </el-card>
        <el-card shadow="never">
          <template #header><strong>租户月度费用试算</strong></template>
          <el-table :data="estimate?.tenants || []" size="small" border>
            <el-table-column prop="tenant_name" label="租户" min-width="150" />
            <el-table-column prop="total_requests" label="请求量" width="120" />
            <el-table-column prop="total_estimated_cost" label="预估费用(¥)" width="140">
              <template #default="{ row }">{{ Number(row.total_estimated_cost || 0).toFixed(2) }}</template>
            </el-table-column>
          </el-table>
        </el-card>
      </div>
    </el-card>

    <el-card shadow="never" class="section-card" v-loading="tableLoading">
      <template #header><strong>明细记录</strong></template>
      <el-table :data="records" size="small" border>
        <el-table-column prop="id" label="ID" width="80" />
        <el-table-column prop="tenant_name" label="租户" min-width="140" />
        <el-table-column prop="module_id" label="模块" min-width="130" />
        <el-table-column prop="method" label="方法" width="90" />
        <el-table-column prop="endpoint" label="接口" min-width="220" show-overflow-tooltip />
        <el-table-column prop="duration_ms" label="耗时(ms)" width="110" />
        <el-table-column prop="created_at" label="时间" min-width="180" />
      </el-table>
      <div class="pager">
        <el-pagination
          layout="total, sizes, prev, pager, next"
          :current-page="form.page"
          :page-size="form.page_size"
          :page-sizes="[20, 50, 100]"
          :total="total"
          @current-change="onPageChange"
          @size-change="onPageSizeChange"
        />
      </div>
    </el-card>
  </el-card>
</template>

<style scoped>
.filter-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: var(--space-3);
  margin-bottom: var(--space-3);
}

.filter-actions {
  display: flex;
  gap: var(--space-2);
  align-items: center;
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: var(--space-3);
  margin-bottom: var(--space-3);
}

.stat-card {
  border: 1px solid var(--ui-border-soft);
  border-radius: 12px;
  padding: 16px;
  background: var(--ui-surface-1);
}

.stat-num {
  font-size: 28px;
  font-weight: 700;
  color: var(--el-color-primary);
}

.stat-label {
  font-size: var(--font-size-sm);
  color: var(--el-text-color-secondary);
}

.section-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-3);
  margin-bottom: var(--space-3);
}

.section-card {
  margin-bottom: var(--space-3);
}

.pager {
  margin-top: var(--space-3);
  display: flex;
  justify-content: flex-end;
}

@media (max-width: 1200px) {
  .filter-grid {
    grid-template-columns: 1fr;
  }
  .stats-grid {
    grid-template-columns: 1fr 1fr;
  }
  .section-grid {
    grid-template-columns: 1fr;
  }
}
</style>

