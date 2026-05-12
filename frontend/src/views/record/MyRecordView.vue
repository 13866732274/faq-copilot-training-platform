<script setup lang="ts">
import { onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { getMyRecords, type RecordListItem } from '../../api/records'
import AdminTableSkeleton from '../../components/admin/AdminTableSkeleton.vue'

const router = useRouter()
const rows = ref<RecordListItem[]>([])
const loading = ref(false)
const isMobile = ref(false)
const pager = reactive({ page: 1, page_size: 10, total: 0 })

const formatDateTime = (value?: string | null) => {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  const y = date.getFullYear()
  const m = String(date.getMonth() + 1).padStart(2, '0')
  const d = String(date.getDate()).padStart(2, '0')
  const hh = String(date.getHours()).padStart(2, '0')
  const mm = String(date.getMinutes()).padStart(2, '0')
  const ss = String(date.getSeconds()).padStart(2, '0')
  return `${y}-${m}-${d} ${hh}:${mm}:${ss}`
}

const formatStatus = (status: string) => {
  if (status === 'completed') return '已完成'
  if (status === 'in_progress') return '进行中'
  return '未知'
}

const formatDuration = (startedAt: string, completedAt?: string | null) => {
  if (!completedAt) return '-'
  const start = new Date(startedAt).getTime()
  const end = new Date(completedAt).getTime()
  if (Number.isNaN(start) || Number.isNaN(end) || end < start) return '-'
  const totalSeconds = Math.floor((end - start) / 1000)
  const h = Math.floor(totalSeconds / 3600)
  const m = Math.floor((totalSeconds % 3600) / 60)
  const s = totalSeconds % 60
  if (h > 0) return `${h}小时${m}分${s}秒`
  if (m > 0) return `${m}分${s}秒`
  return `${s}秒`
}

const load = async () => {
  loading.value = true
  try {
    const data = await getMyRecords({ page: pager.page, page_size: pager.page_size })
    rows.value = data.items
    pager.total = data.total
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || '获取记录失败')
  } finally {
    loading.value = false
  }
}

const onPageChange = () => load()

const updateViewport = () => {
  isMobile.value = window.innerWidth < 992
}

onMounted(() => {
  updateViewport()
  window.addEventListener('resize', updateViewport)
  load()
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', updateViewport)
})
</script>

<template>
  <el-card shadow="never">
    <template #header><strong>我的训练记录</strong></template>
    <AdminTableSkeleton v-if="!isMobile && loading" :is-mobile="false" :rows="8" />
    <el-table v-else-if="!isMobile" class="admin-list-table" :data="rows" border stripe>
      <el-table-column prop="practice_id" label="练习ID" width="90" />
      <el-table-column prop="quiz_title" label="案例标题" min-width="260" />
      <el-table-column label="状态" width="120">
        <template #default="{ row }">
          <el-tag :type="row.status === 'completed' ? 'success' : 'warning'">
            {{ formatStatus(row.status) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="开始时间" width="180">
        <template #default="{ row }">{{ formatDateTime(row.started_at) }}</template>
      </el-table-column>
      <el-table-column label="完成时间" width="180">
        <template #default="{ row }">{{ formatDateTime(row.completed_at) }}</template>
      </el-table-column>
      <el-table-column label="用时" width="130">
        <template #default="{ row }">
          {{ formatDuration(row.started_at, row.completed_at) }}
        </template>
      </el-table-column>
      <el-table-column label="操作" width="110">
        <template #default="{ row }">
          <el-button
            link
            type="primary"
            @click="
              row.status === 'in_progress'
                ? router.push(`/practice/${row.practice_id}/chat?resume=1`)
                : router.push(`/records/${row.practice_id}`)
            "
          >
            {{ row.status === 'in_progress' ? '继续训练' : '详情' }}
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <div v-else class="mobile-list">
      <AdminTableSkeleton v-if="loading" :is-mobile="true" :mobile-rows="4" />
      <el-empty v-else-if="!rows.length" description="暂无训练记录" />
      <template v-else>
        <el-card v-for="row in rows" :key="row.practice_id" class="mobile-item" shadow="never">
          <div class="mobile-title-row">
            <strong>{{ row.quiz_title }}</strong>
            <el-tag :type="row.status === 'completed' ? 'success' : 'warning'" size="small">
              {{ formatStatus(row.status) }}
            </el-tag>
          </div>
          <div class="meta">开始：{{ formatDateTime(row.started_at) }}</div>
          <div class="meta">完成：{{ formatDateTime(row.completed_at) }}</div>
          <div class="meta">用时：{{ formatDuration(row.started_at, row.completed_at) }}</div>
          <div class="actions">
            <el-button
              link
              type="primary"
              @click="
                row.status === 'in_progress'
                  ? router.push(`/practice/${row.practice_id}/chat?resume=1`)
                  : router.push(`/records/${row.practice_id}`)
              "
            >
              {{ row.status === 'in_progress' ? '继续训练' : '查看详情' }}
            </el-button>
          </div>
        </el-card>
      </template>
    </div>
    <div class="pager">
      <el-pagination
        v-model:current-page="pager.page"
        v-model:page-size="pager.page_size"
        :page-sizes="[10, 20, 50, 100]"
        :layout="isMobile ? 'prev, pager, next' : 'total, sizes, prev, pager, next, jumper'"
        :small="isMobile"
        :total="pager.total"
        @size-change="onPageChange"
        @current-change="onPageChange"
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
  align-items: flex-start;
}

.meta {
  margin-top: 6px;
  font-size: var(--font-size-sm);
  color: var(--el-text-color-secondary);
}

.actions {
  margin-top: 8px;
  display: flex;
  justify-content: flex-end;
}

.pager {
  margin-top: var(--space-3);
  display: flex;
  justify-content: flex-end;
}

@media (max-width: 768px) {
  .pager {
    justify-content: center;
  }
}
</style>
