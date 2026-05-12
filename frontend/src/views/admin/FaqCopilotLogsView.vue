<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  batchDeleteFaqCopilotLogs,
  clearFaqCopilotLogs,
  deleteFaqCopilotLog,
} from '../../api/faq'
import request from '../../api/request'
import { useUserStore } from '../../stores/user'

interface LogItem {
  id: number
  user_id: number | null
  username: string
  mode: string
  query: string
  reply: string | null
  confidence: number
  sources_json: string | null
  matched_count: number
  latency_ms: number
  created_at: string | null
}

const loading = ref(false)
const items = ref<LogItem[]>([])
const total = ref(0)
const avgLatency = ref(0)
const page = ref(1)
const pageSize = ref(20)
const selectedIds = ref<number[]>([])
const userStore = useUserStore()
const canManage = ref(false)

const modeLabel = (m: string) => {
  const map: Record<string, string> = {
    copilot: 'AI 推荐',
    copilot_stream: 'AI 流式',
    search: '语义搜索',
  }
  return map[m] || m
}

const modeType = (m: string) => {
  if (m.startsWith('copilot')) return 'success'
  return 'info'
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

const load = async () => {
  loading.value = true
  try {
    const resp = await request.get('/faq/copilot/logs', {
      params: { page: page.value, page_size: pageSize.value },
    })
    const data = resp.data.data
    items.value = data.items
    total.value = data.total
    avgLatency.value = data.avg_latency_ms
    selectedIds.value = []
  } catch {
    ElMessage.error('加载查询日志失败')
  } finally {
    loading.value = false
  }
}

const onSelectionChange = (rows: LogItem[]) => {
  selectedIds.value = rows.map((r) => r.id)
}

const handleDeleteOne = async (row: LogItem) => {
  await ElMessageBox.confirm(`确认删除日志 #${row.id} 吗？`, '删除确认', {
    type: 'warning',
    confirmButtonText: '确认删除',
    cancelButtonText: '取消',
  })
  await deleteFaqCopilotLog(row.id)
  ElMessage.success('删除成功')
  await load()
}

const handleBatchDelete = async () => {
  if (!selectedIds.value.length) {
    ElMessage.warning('请先勾选要删除的日志')
    return
  }
  await ElMessageBox.confirm(`确认删除已选 ${selectedIds.value.length} 条日志吗？`, '批量删除确认', {
    type: 'warning',
    confirmButtonText: '确认删除',
    cancelButtonText: '取消',
  })
  const data = await batchDeleteFaqCopilotLogs(selectedIds.value)
  ElMessage.success(`批量删除完成：${data.deleted} 条`)
  await load()
}

const handleClearAll = async () => {
  await ElMessageBox.confirm('确认一键清空当前租户的 AI 调用统计日志吗？此操作不可恢复。', '清空确认', {
    type: 'warning',
    confirmButtonText: '确认清空',
    cancelButtonText: '取消',
  })
  const data = await clearFaqCopilotLogs()
  ElMessage.success(`已清空 ${data.deleted} 条日志`)
  await load()
}

const handlePageChange = (p: number) => {
  page.value = p
  load()
}

onMounted(async () => {
  canManage.value = userStore.user?.role === 'super_admin'
  await load()
})
</script>

<template>
  <div class="logs-page">
    <div class="page-header">
      <div class="page-header-main">
        <strong class="page-title">Copilot 查询日志</strong>
        <p class="page-desc">
          记录所有 AI 问答助手和语义搜索的使用情况，便于追踪和分析。
          <span v-if="avgLatency" class="avg-latency">
            平均响应：{{ (avgLatency / 1000).toFixed(1) }}s
          </span>
        </p>
      </div>
      <div class="header-actions">
        <el-button @click="load" :loading="loading">刷新</el-button>
        <el-button
          v-if="canManage"
          type="danger"
          plain
          :disabled="!selectedIds.length"
          @click="handleBatchDelete"
        >
          批量删除
        </el-button>
        <el-button v-if="canManage" type="danger" @click="handleClearAll">一键清空</el-button>
      </div>
    </div>

    <el-table :data="items" v-loading="loading" stripe @selection-change="onSelectionChange">
      <el-table-column v-if="canManage" type="selection" width="48" />
      <el-table-column label="ID" prop="id" width="60" />
      <el-table-column label="用户" prop="username" width="130" />
      <el-table-column label="模式" width="100">
        <template #default="{ row }">
          <el-tag :type="modeType(row.mode)" size="small">{{ modeLabel(row.mode) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="查询内容" min-width="200">
        <template #default="{ row }">
          <span class="query-text">{{ row.query }}</span>
        </template>
      </el-table-column>
      <el-table-column label="AI 回复" min-width="250">
        <template #default="{ row }">
          <span v-if="row.reply" class="reply-text">{{ row.reply }}</span>
          <span v-else class="text-muted">—</span>
        </template>
      </el-table-column>
      <el-table-column label="匹配数" prop="matched_count" width="80" align="center" />
      <el-table-column label="耗时" width="90" align="center">
        <template #default="{ row }">
          <el-tag :type="row.latency_ms > 3000 ? 'danger' : row.latency_ms > 1500 ? 'warning' : 'success'" size="small">
            {{ (row.latency_ms / 1000).toFixed(1) }}s
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="时间（北京）" width="180">
        <template #default="{ row }">
          {{ formatBeijingTime(row.created_at) }}
        </template>
      </el-table-column>
      <el-table-column v-if="canManage" label="操作" width="90" fixed="right">
        <template #default="{ row }">
          <el-button link type="danger" @click="handleDeleteOne(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <div class="pagination-row" v-if="total > pageSize">
      <el-pagination
        background
        layout="total, prev, pager, next"
        :total="total"
        :page-size="pageSize"
        :current-page="page"
        @current-change="handlePageChange"
      />
    </div>
  </div>
</template>

<style scoped>
.logs-page {
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
  gap: 8px;
  align-items: center;
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

.avg-latency {
  margin-left: 8px;
  color: var(--el-color-primary);
  font-weight: 500;
}

.query-text {
  font-size: var(--font-size-xs);
  color: var(--el-text-color-primary);
}

.reply-text {
  font-size: var(--font-size-xs);
  color: var(--el-text-color-regular);
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.text-muted {
  color: var(--el-text-color-placeholder);
}

.pagination-row {
  display: flex;
  justify-content: flex-end;
}
</style>
