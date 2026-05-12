<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { refreshPermissionPoints } from '../../utils/permissionPoints'
import {
  batchDeletePermissionPolicyEvents,
  clearPermissionPolicyEvents,
  deletePermissionPolicyEvent,
  listPermissionPolicyEvents,
  type PermissionPolicyEventItem,
} from '../../api/permissionPolicyEvents'

const loading = ref(false)
const refreshing = ref(false)
const rows = ref<PermissionPolicyEventItem[]>([])
const selectedIds = ref<number[]>([])
const exportSanitizeMode = ref<'error_only' | 'full'>('error_only')
const page = ref(1)
const pageSize = ref(50)
const total = ref(0)

const load = async () => {
  loading.value = true
  try {
    const data = await listPermissionPolicyEvents(page.value, pageSize.value)
    rows.value = data.items
    total.value = data.total
    selectedIds.value = []
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '加载诊断日志失败')
  } finally {
    loading.value = false
  }
}

const onSelectionChange = (rowsSelected: PermissionPolicyEventItem[]) => {
  selectedIds.value = rowsSelected.map((r) => r.id)
}

const handlePageChange = (p: number) => {
  page.value = p
  load()
}

const statusType = (s: string) => {
  if (s === 'success') return 'success'
  if (s === 'retry') return 'warning'
  return 'danger'
}

const statusLabel = (s: string) => {
  if (s === 'success') return '成功'
  if (s === 'retry') return '重试'
  return '失败'
}

const formatTime = (iso: string) => {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso || '—'
  return new Intl.DateTimeFormat('zh-CN', {
    hour12: false,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).format(d).replace(/\//g, '-')
}

const stat = computed(() => {
  const totalNum = rows.value.length
  const failed = rows.value.filter((r) => r.stage === 'failed').length
  const retry = rows.value.filter((r) => r.stage === 'retry').length
  const avg = totalNum > 0 ? Math.round(rows.value.reduce((s, r) => s + (r.duration_ms || 0), 0) / totalNum) : 0
  return { total: totalNum, failed, retry, avg }
})

const handleRefreshPolicies = async () => {
  refreshing.value = true
  try {
    await refreshPermissionPoints()
    await load()
    ElMessage.success('权限策略刷新成功')
  } catch (e: any) {
    await load()
    ElMessage.error(e?.response?.data?.detail || e?.message || '权限策略刷新失败')
  } finally {
    refreshing.value = false
  }
}

const handleDeleteOne = async (row: PermissionPolicyEventItem) => {
  try {
    await ElMessageBox.confirm(`确认删除诊断日志 #${row.id} 吗？`, '删除确认', {
      type: 'warning',
      confirmButtonText: '确认删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  await deletePermissionPolicyEvent(row.id)
  ElMessage.success('删除成功')
  await load()
}

const handleBatchDelete = async () => {
  if (!selectedIds.value.length) {
    ElMessage.warning('请先勾选日志')
    return
  }
  try {
    await ElMessageBox.confirm(`确认批量删除已选 ${selectedIds.value.length} 条诊断日志吗？`, '批量删除确认', {
      type: 'warning',
      confirmButtonText: '确认删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  const data = await batchDeletePermissionPolicyEvents(selectedIds.value)
  ElMessage.success(`批量删除完成：${data.deleted} 条`)
  await load()
}

const handleClear = async () => {
  try {
    await ElMessageBox.confirm('确认一键清空权限策略诊断日志吗？此操作不可恢复。', '清空确认', {
      type: 'warning',
      confirmButtonText: '确认清空',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  const data = await clearPermissionPolicyEvents()
  ElMessage.success(`已清空 ${data.deleted} 条诊断日志`)
  await load()
}

const sanitizeText = (raw: string) => {
  if (!raw) return raw
  let text = String(raw)
  text = text.replace(/Bearer\s+[A-Za-z0-9\-._~+/]+=*/gi, 'Bearer [REDACTED]')
  text = text.replace(/\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b/g, '[JWT_REDACTED]')
  text = text.replace(/(token|access_token|api[_-]?key|secret)\s*[:=]\s*['"]?[A-Za-z0-9\-._~+/=]{8,}['"]?/gi, '$1=[REDACTED]')
  text = text.replace(/\b[A-Za-z0-9+/=]{24,}\b/g, '[SECRET_REDACTED]')
  return text
}

const sanitizeEvent = (row: PermissionPolicyEventItem): PermissionPolicyEventItem => ({
  ...row,
  error: sanitizeText(row.error || ''),
})

const applySanitizeMode = <T,>(payload: T): T => {
  if (exportSanitizeMode.value === 'error_only') {
    if (Array.isArray(payload)) return payload.map((r) => sanitizeEvent(r as PermissionPolicyEventItem)) as T
    return payload
  }
  try {
    const raw = JSON.stringify(payload)
    const masked = sanitizeText(raw)
    return JSON.parse(masked) as T
  } catch {
    return payload
  }
}

const exportRows = computed(() => applySanitizeMode(rows.value))

const handleExportJson = () => {
  const rawPayload = {
    exported_at: new Date().toISOString(),
    sanitize_mode: exportSanitizeMode.value,
    stat: stat.value,
    items: rows.value,
  }
  const payload = applySanitizeMode(rawPayload)
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  const stamp = new Date().toISOString().replace(/[:.]/g, '-')
  a.href = url
  a.download = `permission-policy-diagnostics-${stamp}.json`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
  ElMessage.success('已导出 JSON')
}

const buildSummary = () => {
  const data = exportRows.value as PermissionPolicyEventItem[]
  const latest = data[0]
  const failed = data.filter((r) => r.stage === 'failed')
  const retry = data.filter((r) => r.stage === 'retry')
  const topErrors = failed
    .map((r) => (r.error || '').trim())
    .filter(Boolean)
    .slice(0, 3)

  return [
    '权限策略诊断摘要',
    `导出时间: ${formatTime(new Date().toISOString())}`,
    `脱敏策略: ${exportSanitizeMode.value === 'full' ? '全量脱敏' : '仅脱敏错误字段'}`,
    `日志总数: ${stat.value.total}`,
    `重试次数: ${retry.length}`,
    `失败次数: ${failed.length}`,
    `平均耗时: ${stat.value.avg}ms`,
    `最近一条: ${latest ? `${formatTime(latest.at)} ${statusLabel(latest.stage)}(attempt=${latest.attempt}, ${latest.duration_ms}ms)` : '无'}`,
    `高频错误: ${topErrors.length > 0 ? topErrors.join(' | ') : '无'}`,
  ].join('\n')
}

const copyByExecCommand = (text: string) => {
  const area = document.createElement('textarea')
  area.value = text
  area.style.position = 'fixed'
  area.style.left = '-9999px'
  document.body.appendChild(area)
  area.focus()
  area.select()
  const ok = document.execCommand('copy')
  document.body.removeChild(area)
  return ok
}

const handleCopySummary = async () => {
  const summary = buildSummary()
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(summary)
      ElMessage.success('已复制诊断摘要')
      return
    }
  } catch {
    // fallback below
  }
  const ok = copyByExecCommand(summary)
  if (ok) ElMessage.success('已复制诊断摘要')
  else ElMessage.error('复制失败，请手动复制')
}

onMounted(() => {
  load()
})
</script>

<template>
  <div class="diag-page" v-loading="loading">
    <div class="page-header">
      <div>
        <strong class="title">权限策略诊断</strong>
        <p class="desc">用于排查 RBAC 菜单误拦截问题，记录权限策略加载的重试与失败轨迹。</p>
      </div>
      <div class="actions">
        <el-button type="primary" :loading="refreshing" @click="handleRefreshPolicies">手动刷新策略</el-button>
        <el-button @click="handleCopySummary">复制诊断摘要</el-button>
        <el-button @click="handleExportJson">导出 JSON</el-button>
        <el-button @click="load">刷新日志</el-button>
        <el-button type="danger" plain :disabled="!selectedIds.length" @click="handleBatchDelete">批量删除</el-button>
        <el-button type="danger" plain @click="handleClear">清空日志</el-button>
      </div>
    </div>
    <div class="options-bar">
      <span class="options-label">脱敏策略：</span>
      <el-radio-group v-model="exportSanitizeMode" size="small">
        <el-radio-button value="error_only">仅脱敏错误字段</el-radio-button>
        <el-radio-button value="full">全量脱敏</el-radio-button>
      </el-radio-group>
    </div>

    <div class="stats-grid">
      <div class="card">
        <div class="num">{{ stat.total }}</div>
        <div class="label">日志总数</div>
      </div>
      <div class="card warn">
        <div class="num">{{ stat.retry }}</div>
        <div class="label">重试次数</div>
      </div>
      <div class="card danger">
        <div class="num">{{ stat.failed }}</div>
        <div class="label">失败次数</div>
      </div>
      <div class="card">
        <div class="num">{{ stat.avg }}ms</div>
        <div class="label">平均耗时</div>
      </div>
    </div>

    <el-table :data="rows" stripe @selection-change="onSelectionChange">
      <el-table-column type="selection" width="48" />
      <el-table-column label="ID" prop="id" width="80" />
      <el-table-column label="时间" width="190">
        <template #default="{ row }">
          {{ formatTime(row.at) }}
        </template>
      </el-table-column>
      <el-table-column label="阶段" width="90" align="center">
        <template #default="{ row }">
          <el-tag size="small" :type="statusType(row.stage)">{{ statusLabel(row.stage) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="尝试次数" prop="attempt" width="90" align="center" />
      <el-table-column label="耗时" width="100" align="center">
        <template #default="{ row }">
          {{ row.duration_ms }}ms
        </template>
      </el-table-column>
      <el-table-column label="错误信息" min-width="320">
        <template #default="{ row }">
          <span>{{ row.error || '—' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="90" fixed="right">
        <template #default="{ row }">
          <el-button link type="danger" @click="handleDeleteOne(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>
    <div class="pager">
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
.diag-page { display: grid; gap: var(--space-3); }
.page-header { display: flex; justify-content: space-between; gap: var(--space-2); align-items: flex-start; flex-wrap: wrap; }
.title { font-size: var(--font-size-h5); }
.desc { margin: 4px 0 0; color: var(--el-text-color-secondary); font-size: var(--font-size-xs); }
.actions { display: flex; gap: var(--space-2); flex-wrap: wrap; }
.options-bar { display: flex; align-items: center; gap: 8px; }
.options-label { font-size: var(--font-size-xs); color: var(--el-text-color-secondary); }
.stats-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: var(--space-2); }
.card { border: 1px solid var(--ui-border-soft); border-radius: 10px; padding: 12px; background: var(--ui-surface-1); }
.card.warn .num { color: var(--el-color-warning); }
.card.danger .num { color: var(--el-color-danger); }
.num { font-size: 24px; font-weight: 700; line-height: 1.2; color: var(--el-color-primary); }
.label { font-size: var(--font-size-xs); color: var(--el-text-color-secondary); margin-top: 4px; }
.pager { display: flex; justify-content: flex-end; }
</style>
