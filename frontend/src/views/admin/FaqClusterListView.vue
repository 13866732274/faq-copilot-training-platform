<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  listFaqClusters,
  deleteFaqCluster,
  mergeFaqClusters,
  updateFaqCluster,
  type FaqClusterItem,
  type FaqCategoryCount,
} from '../../api/faq'

const router = useRouter()
const route = useRoute()
const loading = ref(false)
const items = ref<FaqClusterItem[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const categories = ref<FaqCategoryCount[]>([])
const filterCategory = ref<string>((route.query.category as string) || '')
const filterKeyword = ref('')
const selectedRows = ref<FaqClusterItem[]>([])

const selectedIds = computed(() => selectedRows.value.map((r) => r.id))

const load = async () => {
  loading.value = true
  try {
    const data = await listFaqClusters({
      page: page.value,
      page_size: pageSize.value,
      category: filterCategory.value || undefined,
      keyword: filterKeyword.value || undefined,
    })
    items.value = data.items
    total.value = data.total
    categories.value = data.categories
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '加载失败')
  } finally {
    loading.value = false
  }
}

const onFilter = () => {
  page.value = 1
  load()
}

const onSelectionChange = (val: FaqClusterItem[]) => {
  selectedRows.value = val
}

const handleDelete = async (cluster: FaqClusterItem) => {
  try {
    await ElMessageBox.confirm(`确认删除 FAQ「${cluster.title}」？此操作不可恢复。`, '确认删除', { type: 'warning' })
  } catch { return }
  try {
    await deleteFaqCluster(cluster.id)
    ElMessage.success('已删除')
    load()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '删除失败')
  }
}

const handleMerge = async () => {
  if (selectedIds.value.length < 2) {
    ElMessage.warning('请至少选择两个 FAQ 条目进行合并')
    return
  }
  try {
    const { value: title } = await ElMessageBox.prompt(
      `将合并 ${selectedIds.value.length} 个条目到第一个选中的条目中。可为合并后条目命名：`,
      '合并 FAQ 条目',
      { inputValue: selectedRows.value[0]?.title || '', confirmButtonText: '合并', cancelButtonText: '取消' },
    )
    await mergeFaqClusters(selectedIds.value, title || undefined)
    ElMessage.success('合并成功')
    load()
  } catch { /* cancelled */ }
}

const handleToggleActive = async (cluster: FaqClusterItem) => {
  try {
    await updateFaqCluster(cluster.id, { is_active: !cluster.is_active })
    cluster.is_active = !cluster.is_active
    ElMessage.success(cluster.is_active ? '已启用' : '已停用')
  } catch (e: any) {
    ElMessage.error('操作失败')
  }
}

watch([page, pageSize], load)

onMounted(load)
</script>

<template>
  <div class="faq-list-page">
    <div class="page-header">
      <div class="page-header-main">
        <strong class="page-title">FAQ 知识库</strong>
        <p class="page-desc">浏览和管理从对话记录中提取的常见问答条目。</p>
      </div>
      <div class="page-header-actions">
        <el-button v-if="selectedIds.length >= 2" type="warning" @click="handleMerge">
          合并选中 ({{ selectedIds.length }})
        </el-button>
        <el-button @click="router.push('/admin/faq')">返回概览</el-button>
      </div>
    </div>

    <div class="filter-bar">
      <el-select
        v-model="filterCategory"
        placeholder="全部分类"
        clearable
        @change="onFilter"
        style="width: 180px"
      >
        <el-option v-for="cat in categories" :key="cat.name" :label="`${cat.name} (${cat.count})`" :value="cat.name" />
      </el-select>
      <el-input
        v-model="filterKeyword"
        placeholder="搜索标题、问题、答案..."
        clearable
        @clear="onFilter"
        @keyup.enter="onFilter"
        style="max-width: 320px"
      />
      <el-button type="primary" @click="onFilter">搜索</el-button>
    </div>

    <el-table
      :data="items"
      v-loading="loading"
      stripe
      @selection-change="onSelectionChange"
      row-key="id"
      class="cluster-table"
    >
      <el-table-column type="selection" width="45" />
      <el-table-column label="FAQ 标题" min-width="200">
        <template #default="{ row }">
          <el-link type="primary" @click="router.push(`/admin/faq/clusters/${row.id}`)">
            {{ row.title }}
          </el-link>
        </template>
      </el-table-column>
      <el-table-column label="分类" width="120" prop="category">
        <template #default="{ row }">
          <el-tag v-if="row.category" size="small">{{ row.category }}</el-tag>
          <span v-else class="text-muted">—</span>
        </template>
      </el-table-column>
      <el-table-column label="代表性问题" min-width="220">
        <template #default="{ row }">
          <span class="rep-question">{{ row.representative_question || '—' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="问题数" width="80" align="center" prop="question_count" />
      <el-table-column label="答案数" width="80" align="center" prop="answer_count" />
      <el-table-column label="状态" width="80" align="center">
        <template #default="{ row }">
          <el-tag :type="row.is_active ? 'success' : 'info'" size="small">
            {{ row.is_active ? '启用' : '停用' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="180" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" size="small" @click="router.push(`/admin/faq/clusters/${row.id}`)">详情</el-button>
          <el-button link :type="row.is_active ? 'warning' : 'success'" size="small" @click="handleToggleActive(row)">
            {{ row.is_active ? '停用' : '启用' }}
          </el-button>
          <el-button link type="danger" size="small" @click="handleDelete(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <div class="pagination-bar">
      <el-pagination
        v-model:current-page="page"
        v-model:page-size="pageSize"
        :total="total"
        :page-sizes="[10, 20, 50, 100]"
        layout="total, sizes, prev, pager, next"
        background
      />
    </div>
  </div>
</template>

<style scoped>
.faq-list-page {
  display: grid;
  gap: var(--space-3);
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  flex-wrap: wrap;
  gap: var(--space-2);
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

.page-header-actions {
  display: flex;
  gap: var(--space-2);
}

.filter-bar {
  display: flex;
  gap: var(--space-2);
  flex-wrap: wrap;
  align-items: center;
}

.rep-question {
  font-size: var(--font-size-xs);
  color: var(--el-text-color-secondary);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.text-muted {
  color: var(--el-text-color-placeholder);
}

.pagination-bar {
  display: flex;
  justify-content: flex-end;
}
</style>
