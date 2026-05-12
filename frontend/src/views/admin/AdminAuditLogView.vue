<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRoute } from 'vue-router'
import {
  batchDeleteAuditLogs,
  clearAuditLogs,
  deleteAuditLog,
  getAuditLogs,
  type AuditLogItem,
  type AuditLogQuery,
} from '../../api/audit'
import { getHospitals, type HospitalItem } from '../../api/hospital'
import { getDepartments, type DepartmentItem } from '../../api/department'
import { createDebouncedFn } from '../../composables/useUiStandards'
import AdminTableSkeleton from '../../components/admin/AdminTableSkeleton.vue'

const loading = ref(false)
const route = useRoute()
const rows = ref<AuditLogItem[]>([])
const hospitals = ref<HospitalItem[]>([])
const departments = ref<DepartmentItem[]>([])
const isMobile = ref(false)
const dateRange = ref<[Date, Date] | []>([])
const pager = reactive({
  page: 1,
  page_size: 20,
  total: 0,
  action: '',
  keyword: '',
  hospital_id: undefined as number | undefined,
  department_id: undefined as number | undefined,
})
const selectedIds = ref<number[]>([])

const actionOptions = [
  { label: '全部动作', value: '' },
  { label: '登录成功', value: 'login_success' },
  { label: '登录失败', value: 'login_fail' },
  { label: '导入案例库', value: 'quiz_import' },
  { label: '案例库版本更新', value: 'quiz_version_update' },
  { label: '医院分配', value: 'hospital_assign' },
  { label: '科室分配', value: 'department_assign' },
  { label: '用户权限变更', value: 'user_permission_change' },
  { label: '点评变更', value: 'comment_change' },
]

const actionText = (action: string) => actionOptions.find((opt) => opt.value === action)?.label || action

const formatDetailValue = (value: unknown) => {
  if (value === null || value === undefined) return '-'
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  try {
    return JSON.stringify(value)
  } catch {
    return String(value)
  }
}

const detailEntries = (detail?: Record<string, any> | null) => {
  if (!detail || typeof detail !== 'object') return []
  const entries: Array<{ key: string; value: string; kind: 'before' | 'after' | 'normal' }> = []
  for (const [key, value] of Object.entries(detail)) {
    if ((key === 'before' || key === 'after') && value && typeof value === 'object' && !Array.isArray(value)) {
      for (const [subKey, subValue] of Object.entries(value as Record<string, unknown>)) {
        entries.push({
          key: `${key}.${subKey}`,
          value: formatDetailValue(subValue),
          kind: key === 'before' ? 'before' : 'after',
        })
      }
      continue
    }
    entries.push({
      key,
      value: formatDetailValue(value),
      kind: 'normal',
    })
  }
  return entries
}

const actorText = (row: AuditLogItem) => {
  const name = row.real_name || row.username || '系统'
  if (row.username && row.real_name && row.real_name !== row.username) return `${row.real_name}(${row.username})`
  return name
}

const targetText = (row: AuditLogItem) => {
  const targetTypeMap: Record<string, string> = {
    user: '用户',
    hospital: '医院',
    department: '科室',
    quiz: '案例库',
    practice: '练习',
    comment: '点评',
    system: '系统',
  }
  const targetTypeText = targetTypeMap[row.target_type] || row.target_type
  if (!row.target_id) return targetTypeText
  return `${targetTypeText}#${row.target_id}`
}

const queryParams = computed<AuditLogQuery>(() => {
  const params: AuditLogQuery = {
    page: pager.page,
    page_size: pager.page_size,
    action: pager.action || undefined,
    keyword: pager.keyword || undefined,
    hospital_id: pager.hospital_id,
    department_id: pager.department_id,
  }
  if (dateRange.value.length === 2) {
    params.start_at = dateRange.value[0].toISOString()
    params.end_at = dateRange.value[1].toISOString()
  }
  return params
})

const load = async () => {
  loading.value = true
  try {
    const data = await getAuditLogs(queryParams.value)
    rows.value = data.items
    pager.total = data.total
    selectedIds.value = []
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || '获取审计日志失败')
  } finally {
    loading.value = false
  }
}

const onSelectionChange = (selected: AuditLogItem[]) => {
  selectedIds.value = selected.map((item) => item.id)
}

const handleDeleteOne = async (row: AuditLogItem) => {
  await ElMessageBox.confirm(`确认删除审计日志 #${row.id} 吗？`, '删除确认', {
    type: 'warning',
    confirmButtonText: '确认删除',
    cancelButtonText: '取消',
  })
  await deleteAuditLog(row.id)
  ElMessage.success('删除成功')
  await load()
}

const handleBatchDelete = async () => {
  if (!selectedIds.value.length) {
    ElMessage.warning('请先勾选要删除的日志')
    return
  }
  await ElMessageBox.confirm(`确认批量删除已选 ${selectedIds.value.length} 条审计日志吗？`, '批量删除确认', {
    type: 'warning',
    confirmButtonText: '确认删除',
    cancelButtonText: '取消',
  })
  await batchDeleteAuditLogs(selectedIds.value)
  ElMessage.success('批量删除成功')
  await load()
}

const handleClearAll = async () => {
  await ElMessageBox.confirm('确认一键清空当前租户全部审计日志吗？此操作不可恢复。', '清空确认', {
    type: 'warning',
    confirmButtonText: '确认清空',
    cancelButtonText: '取消',
  })
  await clearAuditLogs()
  ElMessage.success('审计日志已清空')
  await load()
}

const onSearch = () => {
  triggerFilterSearch.cancel()
  pager.page = 1
  load()
}

const triggerFilterSearch = createDebouncedFn(() => {
  pager.page = 1
  load()
}, 300)

const onHospitalFilterChange = () => {
  pager.department_id = undefined
}

const updateViewport = () => {
  isMobile.value = window.innerWidth < 992
}

onMounted(async () => {
  const q = typeof route.query.q === 'string' ? route.query.q.trim() : ''
  if (q) pager.keyword = q
  updateViewport()
  window.addEventListener('resize', updateViewport)
  try {
    hospitals.value = await getHospitals()
  } catch {
    hospitals.value = []
  }
  try {
    departments.value = await getDepartments()
  } catch {
    departments.value = []
  }
  await load()
})

onBeforeUnmount(() => {
  triggerFilterSearch.cancel()
  window.removeEventListener('resize', updateViewport)
})

watch(
  [() => pager.action, () => pager.keyword, () => pager.hospital_id, () => pager.department_id, dateRange],
  () => {
    triggerFilterSearch()
  },
  { deep: true },
)

watch(
  () => route.query.q,
  (value) => {
    const q = typeof value === 'string' ? value.trim() : ''
    if (q === pager.keyword) return
    pager.keyword = q
  },
)
</script>

<template>
  <el-card shadow="never">
    <template #header>
      <div class="admin-card-header">
        <strong class="admin-card-title">操作审计日志</strong>
      </div>
    </template>

    <div class="admin-toolbar audit-toolbar">
      <div class="audit-toolbar-filters">
        <el-select v-model="pager.action" class="admin-control-w-lg" placeholder="动作类型">
          <el-option v-for="opt in actionOptions" :key="opt.value || 'all'" :label="opt.label" :value="opt.value" />
        </el-select>
        <el-select
          v-model="pager.hospital_id"
          clearable
          placeholder="所属医院"
          class="admin-control-w-xl"
          @change="onHospitalFilterChange"
        >
          <el-option v-for="h in hospitals" :key="h.id" :label="h.name" :value="h.id" />
        </el-select>
        <el-select
          v-model="pager.department_id"
          clearable
          placeholder="所属科室"
          class="admin-control-w-xl"
        >
          <el-option
            v-for="d in pager.hospital_id ? departments.filter((i) => i.hospital_id === pager.hospital_id) : departments"
            :key="d.id"
            :label="d.name"
            :value="d.id"
          />
        </el-select>
        <el-date-picker
          class="admin-control-w-date"
          v-model="dateRange"
          type="datetimerange"
          unlink-panels
          range-separator="至"
          start-placeholder="开始时间"
          end-placeholder="结束时间"
        />
        <el-input
          v-model="pager.keyword"
          class="admin-control-w-xl"
          placeholder="按账号/姓名搜索"
          clearable
          @keyup.enter="onSearch"
        />
      </div>
      <div class="audit-toolbar-actions">
        <el-button @click="onSearch">查询</el-button>
        <el-button type="danger" plain :disabled="!selectedIds.length" @click="handleBatchDelete">批量删除</el-button>
        <el-button type="danger" @click="handleClearAll">一键清空</el-button>
      </div>
    </div>

    <AdminTableSkeleton v-if="!isMobile && loading" :is-mobile="false" :rows="8" />
    <el-table
      v-else-if="!isMobile"
      class="admin-list-table"
      :data="rows"
      border
      stripe
      @selection-change="onSelectionChange"
    >
      <el-table-column type="selection" width="48" />
      <el-table-column prop="id" label="编号" width="90" />
      <el-table-column prop="created_at" label="时间" width="180" />
      <el-table-column label="操作人" min-width="160">
        <template #default="{ row }">{{ actorText(row) }}</template>
      </el-table-column>
      <el-table-column label="动作" width="160">
        <template #default="{ row }">
          <el-tag size="small" type="info">{{ actionText(row.action) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="目标" width="170">
        <template #default="{ row }">{{ targetText(row) }}</template>
      </el-table-column>
      <el-table-column label="医院" min-width="180">
        <template #default="{ row }">{{ row.hospital_name || '-' }}</template>
      </el-table-column>
      <el-table-column label="科室" min-width="160">
        <template #default="{ row }">{{ row.department_name || '-' }}</template>
      </el-table-column>
      <el-table-column prop="ip" label="IP地址" width="150" />
      <el-table-column label="详情" min-width="360">
        <template #default="{ row }">
          <div v-if="detailEntries(row.detail).length" class="detail-kv-list">
            <div
              v-for="entry in detailEntries(row.detail)"
              :key="entry.key"
              class="detail-kv-item"
              :class="`kind-${entry.kind}`"
            >
              <span class="detail-key">{{ entry.key }}</span>
              <span class="detail-value">{{ entry.value }}</span>
            </div>
          </div>
          <span v-else>-</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="90" fixed="right">
        <template #default="{ row }">
          <el-button link type="danger" @click="handleDeleteOne(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <div v-else class="mobile-list">
      <AdminTableSkeleton v-if="loading" :is-mobile="true" :mobile-rows="4" />
      <el-empty v-else-if="!rows.length" class="admin-empty" description="暂无日志数据" />
      <template v-else>
        <el-card v-for="row in rows" :key="row.id" class="mobile-item" shadow="never">
          <div class="mobile-title-row">
            <strong>#{{ row.id }} {{ actionText(row.action) }}</strong>
            <span class="time">{{ row.created_at }}</span>
          </div>
          <div class="meta">操作人：{{ actorText(row) }}</div>
          <div class="meta">目标：{{ targetText(row) }}</div>
          <div class="meta">医院：{{ row.hospital_name || '-' }}</div>
          <div class="meta">科室：{{ row.department_name || '-' }}</div>
          <div class="meta">IP地址：{{ row.ip || '-' }}</div>
          <div class="meta">
            <el-button link type="danger" @click="handleDeleteOne(row)">删除此条</el-button>
          </div>
          <div class="meta detail">
            <div>详情：</div>
            <div v-if="detailEntries(row.detail).length" class="detail-kv-list">
              <div
                v-for="entry in detailEntries(row.detail)"
                :key="entry.key"
                class="detail-kv-item"
                :class="`kind-${entry.kind}`"
              >
                <span class="detail-key">{{ entry.key }}</span>
                <span class="detail-value">{{ entry.value }}</span>
              </div>
            </div>
            <span v-else>-</span>
          </div>
        </el-card>
      </template>
    </div>

    <div class="admin-pager">
      <el-pagination
        v-model:current-page="pager.page"
        v-model:page-size="pager.page_size"
        :page-sizes="[10, 20, 50, 100]"
        :layout="isMobile ? 'prev, pager, next' : 'total, sizes, prev, pager, next, jumper'"
        :small="isMobile"
        :total="pager.total"
        @size-change="onSearch"
        @current-change="load"
      />
    </div>
  </el-card>
</template>

<style scoped>
.mobile-list {
  display: grid;
  gap: 10px;
}

.mobile-item {
  border: 1px solid var(--el-border-color-light);
}

.mobile-title-row {
  display: flex;
  justify-content: space-between;
  gap: 8px;
}

.time {
  color: var(--el-text-color-secondary);
  font-size: var(--font-size-xs);
}

.meta {
  margin-top: 6px;
  color: var(--el-text-color-secondary);
  font-size: var(--font-size-sm);
}

.detail {
  word-break: break-all;
}

.detail-kv-list {
  display: grid;
  gap: 6px;
}

.detail-kv-item {
  border: 1px solid var(--el-border-color-light);
  border-radius: 6px;
  padding: 4px 6px;
  background: var(--el-fill-color-blank);
}

.detail-key {
  display: inline-block;
  min-width: 110px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.detail-value {
  color: var(--el-text-color-regular);
  word-break: break-all;
}

.detail-kv-item.kind-before {
  border-color: var(--el-color-danger-light-5);
  background: var(--el-color-danger-light-9);
}

.detail-kv-item.kind-after {
  border-color: var(--el-color-success-light-5);
  background: var(--el-color-success-light-9);
}

.audit-toolbar {
  align-items: center;
  justify-content: space-between;
  flex-wrap: nowrap;
}

.audit-toolbar-filters {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: nowrap;
  min-width: 0;
  overflow-x: auto;
  padding-bottom: 2px;
}

.audit-toolbar-actions {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

@media (max-width: 768px) {
  .audit-toolbar {
    flex-wrap: wrap;
    align-items: stretch;
  }

  .audit-toolbar-filters {
    width: 100%;
    flex-wrap: wrap;
    overflow-x: visible;
  }

  .audit-toolbar-filters :deep(.el-select),
  .audit-toolbar-filters :deep(.el-input),
  .audit-toolbar-filters :deep(.el-date-editor) {
    width: 100% !important;
  }

  .audit-toolbar-actions {
    width: 100%;
    justify-content: flex-start;
  }
}

</style>
