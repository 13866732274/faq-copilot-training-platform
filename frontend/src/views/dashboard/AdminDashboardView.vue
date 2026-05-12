<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Calendar, DataAnalysis, Document, OfficeBuilding, Operation, UserFilled } from '@element-plus/icons-vue'
import * as echarts from 'echarts/core'
import { LineChart, PieChart, BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([LineChart, PieChart, BarChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer])
import { getHospitalCompareStats, getOverviewStats, getQuizStats, getStatsTrends, getSystemHealthStats } from '../../api/stats'
import MetricCardsPanel, { type MetricCardItem } from '../../components/admin/MetricCardsPanel.vue'

const loading = ref(false)
const statsRefreshTick = ref(0)
const chartLoading = ref(false)

const trendChartRef = ref<HTMLDivElement | null>(null)
const categoryChartRef = ref<HTMLDivElement | null>(null)
const hospitalChartRef = ref<HTMLDivElement | null>(null)

let trendChart: echarts.ECharts | null = null
let categoryChart: echarts.ECharts | null = null
let hospitalChart: echarts.ECharts | null = null

const stats = reactive({
  total_quizzes: 0,
  total_students: 0,
  total_practices: 0,
  today_practices: 0,
  total_hospitals: 0,
  total_departments: 0,
})

const trends = reactive({
  dates: [] as string[],
  new_practices: [] as number[],
  completed: [] as number[],
  new_students: [] as number[],
})

const quizCategoryData = ref<Array<{ name: string; value: number }>>([])
const hospitalActivityData = ref<Array<{ name: string; value: number }>>([])
const systemHealth = reactive({
  db_status: 'ok',
  db_ping_ms: 0,
  active_practice_sessions: 0,
  pending_import_tasks: 0,
  audit_logs_24h: 0,
  slow_request_threshold_ms: 500,
  server_time: '',
})

const loadStats = async () => {
  loading.value = true
  try {
    const [data, health] = await Promise.all([getOverviewStats(), getSystemHealthStats()])
    stats.total_quizzes = data.total_quizzes
    stats.total_students = data.total_students
    stats.total_practices = data.total_practices
    stats.today_practices = data.today_practices
    stats.total_hospitals = data.total_hospitals
    stats.total_departments = data.total_departments
    systemHealth.db_status = health.db_status
    systemHealth.db_ping_ms = health.db_ping_ms
    systemHealth.active_practice_sessions = health.active_practice_sessions
    systemHealth.pending_import_tasks = health.pending_import_tasks
    systemHealth.audit_logs_24h = health.audit_logs_24h
    systemHealth.slow_request_threshold_ms = health.slow_request_threshold_ms
    systemHealth.server_time = health.server_time
    statsRefreshTick.value += 1
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || '获取统计数据失败')
  } finally {
    loading.value = false
  }
}

const loadChartsData = async () => {
  chartLoading.value = true
  try {
    const [trendData, quizData, hospitalData] = await Promise.all([
      getStatsTrends({ days: 30 }),
      getQuizStats({ page: 1, page_size: 200 }),
      getHospitalCompareStats({ page: 1, page_size: 10 }),
    ])
    trends.dates = trendData.dates || []
    trends.new_practices = trendData.new_practices || []
    trends.completed = trendData.completed || []
    trends.new_students = trendData.new_students || []

    const categoryMap = new Map<string, number>()
    quizData.items.forEach((item) => {
      const key = (item.category || '未分类').trim() || '未分类'
      categoryMap.set(key, (categoryMap.get(key) || 0) + 1)
    })
    quizCategoryData.value = Array.from(categoryMap.entries())
      .map(([name, value]) => ({ name, value }))
      .sort((a, b) => b.value - a.value)
      .slice(0, 8)

    hospitalActivityData.value = hospitalData.items
      .map((item) => ({ name: item.hospital_name, value: item.practice_count }))
      .slice(0, 10)

    await nextTick()
    renderAllCharts()
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || '获取图表数据失败')
  } finally {
    chartLoading.value = false
  }
}

const renderTrendChart = () => {
  if (!trendChartRef.value) return
  if (!trendChart) trendChart = echarts.init(trendChartRef.value)
  trendChart.setOption({
    tooltip: { trigger: 'axis' },
    legend: { top: 0 },
    grid: { left: 36, right: 16, top: 36, bottom: 18, containLabel: true },
    xAxis: { type: 'category', data: trends.dates },
    yAxis: { type: 'value' },
    series: [
      { name: '新增练习', type: 'line', smooth: true, data: trends.new_practices },
      { name: '完成练习', type: 'line', smooth: true, data: trends.completed },
      { name: '新增咨询员', type: 'line', smooth: true, data: trends.new_students },
    ],
  })
}

const renderCategoryChart = () => {
  if (!categoryChartRef.value) return
  if (!categoryChart) categoryChart = echarts.init(categoryChartRef.value)
  categoryChart.setOption({
    tooltip: { trigger: 'item' },
    legend: { bottom: 0 },
    series: [
      {
        name: '案例库分类',
        type: 'pie',
        radius: ['38%', '68%'],
        center: ['50%', '44%'],
        data: quizCategoryData.value,
        label: { formatter: '{b}: {c}' },
      },
    ],
  })
}

const renderHospitalChart = () => {
  if (!hospitalChartRef.value) return
  if (!hospitalChart) hospitalChart = echarts.init(hospitalChartRef.value)
  hospitalChart.setOption({
    tooltip: { trigger: 'axis' },
    grid: { left: 96, right: 16, top: 20, bottom: 12, containLabel: true },
    xAxis: { type: 'value' },
    yAxis: {
      type: 'category',
      data: hospitalActivityData.value.map((item) => item.name),
      inverse: true,
    },
    series: [
      {
        type: 'bar',
        data: hospitalActivityData.value.map((item) => item.value),
        barMaxWidth: 16,
      },
    ],
  })
}

const renderAllCharts = () => {
  renderTrendChart()
  renderCategoryChart()
  renderHospitalChart()
}

const metricItems = computed<MetricCardItem[]>(() => [
  { key: 'total_quizzes', label: '案例库总数', value: stats.total_quizzes, hint: '当前全量可管理案例', tone: 'primary', icon: Document },
  { key: 'total_students', label: '咨询员总数', value: stats.total_students, hint: '含启用与禁用账号', tone: 'info', icon: UserFilled },
  { key: 'total_practices', label: '训练总次数', value: stats.total_practices, hint: '历史累计训练次数', tone: 'success', icon: DataAnalysis },
  { key: 'today_practices', label: '今日练习', value: stats.today_practices, hint: '今日新增训练活动', tone: 'warning', icon: Calendar },
  { key: 'total_hospitals', label: '医院总数', value: stats.total_hospitals, hint: '当前接入医院数量', tone: 'primary', icon: OfficeBuilding },
  { key: 'total_departments', label: '科室总数', value: stats.total_departments, hint: '覆盖运营科室规模', tone: 'danger', icon: Operation },
])

const onResize = () => {
  trendChart?.resize()
  categoryChart?.resize()
  hospitalChart?.resize()
}

onMounted(async () => {
  await Promise.all([loadStats(), loadChartsData()])
  window.addEventListener('resize', onResize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
  trendChart?.dispose()
  categoryChart?.dispose()
  hospitalChart?.dispose()
})
</script>

<template>
  <div v-loading="loading">
    <MetricCardsPanel :items="metricItems" :loading="loading" :refresh-tick="statsRefreshTick" />

    <div class="charts-grid" v-loading="chartLoading">
      <el-card shadow="never" class="chart-card chart-wide">
        <template #header>近 30 天运营趋势</template>
        <div ref="trendChartRef" class="chart-box chart-trend" />
      </el-card>

      <el-card shadow="never" class="chart-card">
        <template #header>案例库分类分布</template>
        <div ref="categoryChartRef" class="chart-box chart-pie" />
      </el-card>

      <el-card shadow="never" class="chart-card">
        <template #header>医院活跃度排行（Top 10）</template>
        <div ref="hospitalChartRef" class="chart-box chart-bar" />
      </el-card>
    </div>

    <el-card shadow="never" style="margin-top: 16px">
      <template #header>快捷入口</template>
      <el-space>
        <RouterLink to="/admin/quizzes/import"><el-button type="primary">导入案例</el-button></RouterLink>
        <RouterLink to="/admin/quizzes"><el-button>案例库列表</el-button></RouterLink>
        <RouterLink to="/admin/hospitals"><el-button>医院管理</el-button></RouterLink>
        <RouterLink to="/practice"><el-button>开始训练</el-button></RouterLink>
      </el-space>
    </el-card>

    <el-card shadow="never" style="margin-top: 16px">
      <template #header>系统健康面板</template>
      <div class="health-grid">
        <div class="health-item">
          <span class="health-label">数据库状态</span>
          <el-tag :type="systemHealth.db_status === 'ok' ? 'success' : 'danger'">
            {{ systemHealth.db_status === 'ok' ? '正常' : '异常' }}
          </el-tag>
        </div>
        <div class="health-item">
          <span class="health-label">DB Ping</span>
          <strong :class="{ warn: systemHealth.db_ping_ms > systemHealth.slow_request_threshold_ms }">
            {{ systemHealth.db_ping_ms }} ms
          </strong>
        </div>
        <div class="health-item">
          <span class="health-label">运行中训练会话</span>
          <strong>{{ systemHealth.active_practice_sessions }}</strong>
        </div>
        <div class="health-item">
          <span class="health-label">运行中导入任务</span>
          <strong>{{ systemHealth.pending_import_tasks }}</strong>
        </div>
        <div class="health-item">
          <span class="health-label">近24h审计日志</span>
          <strong>{{ systemHealth.audit_logs_24h }}</strong>
        </div>
        <div class="health-item">
          <span class="health-label">服务端时间</span>
          <strong>{{ systemHealth.server_time || '-' }}</strong>
        </div>
      </div>
    </el-card>
  </div>
</template>

<style scoped>
.charts-grid {
  margin-top: var(--space-4);
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-3);
}

.chart-wide {
  grid-column: 1 / -1;
}

.chart-box {
  width: 100%;
}

.chart-trend {
  height: 330px;
}

.chart-pie,
.chart-bar {
  height: 320px;
}

@media (max-width: 992px) {
  .charts-grid {
    grid-template-columns: 1fr;
  }
  .chart-wide {
    grid-column: auto;
  }
}

.health-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--space-3);
}

.health-item {
  border: 1px solid var(--el-border-color-light);
  border-radius: 10px;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.health-label {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.warn {
  color: var(--el-color-danger);
}

@media (max-width: 992px) {
  .health-grid {
    grid-template-columns: 1fr;
  }
}
</style>
