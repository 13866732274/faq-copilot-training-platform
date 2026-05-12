<script setup lang="ts">
import { onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  getAvailablePracticeOptions,
  getAvailablePractices,
  startPractice,
  startRandomPractice,
  type PracticeQuizItem,
} from '../../api/practice'
import AdminTableSkeleton from '../../components/admin/AdminTableSkeleton.vue'
import { createDebouncedFn } from '../../composables/useUiStandards'

const router = useRouter()
const route = useRoute()
const loading = ref(false)
const rows = ref<PracticeQuizItem[]>([])
const chatType = ref<'' | 'active' | 'passive'>('')
const keyword = ref('')
const category = ref('')
const tag = ref('')
const isMobile = ref(false)
const randomStarting = ref(false)
const categoryOptions = ref<Array<{ name: string; count: number }>>([])
const tagOptions = ref<Array<{ name: string; count: number }>>([])
const pager = reactive({ page: 1, page_size: 10, total: 0 })

const load = async () => {
  loading.value = true
  try {
    const data = await getAvailablePractices({
      chat_type: chatType.value || undefined,
      keyword: keyword.value.trim() || undefined,
      category: category.value || undefined,
      tag: tag.value || undefined,
      page: pager.page,
      page_size: pager.page_size,
    })
    rows.value = data.items
    pager.total = data.total
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || '获取可训练案例失败')
  } finally {
    loading.value = false
  }
}

const loadOptions = async () => {
  try {
    const data = await getAvailablePracticeOptions({
      chat_type: chatType.value || undefined,
      keyword: keyword.value.trim() || undefined,
    })
    categoryOptions.value = data.categories || []
    tagOptions.value = data.tags || []
  } catch {
    categoryOptions.value = []
    tagOptions.value = []
  }
}

const onFilter = () => {
  triggerFilter.cancel()
  pager.page = 1
  loadOptions()
  load()
}

const triggerFilter = createDebouncedFn(() => {
  pager.page = 1
  load()
}, 280)

const onPageChange = () => {
  load()
}

const onStart = async (quizId: number) => {
  try {
    const data = await startPractice(quizId)
    router.push(`/practice/${data.practice_id}/chat`)
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || '开始训练失败')
  }
}

const onStartRandom = async () => {
  if (randomStarting.value) return
  randomStarting.value = true
  try {
    const data = await startRandomPractice({
      chat_type: chatType.value || undefined,
      keyword: keyword.value.trim() || undefined,
      category: category.value || undefined,
      tag: tag.value || undefined,
    })
    ElMessage.success('已为你匹配一题（尽量避开最近重复）')
    router.push(`/practice/${data.practice_id}/chat`)
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || '随机训练失败')
  } finally {
    randomStarting.value = false
  }
}

const updateViewport = () => {
  isMobile.value = window.innerWidth < 992
}

onMounted(() => {
  const q = typeof route.query.q === 'string' ? route.query.q.trim() : ''
  if (q) keyword.value = q
  updateViewport()
  window.addEventListener('resize', updateViewport)
  loadOptions()
  load()
})

onBeforeUnmount(() => {
  triggerFilter.cancel()
  window.removeEventListener('resize', updateViewport)
})

watch([chatType, keyword, category, tag], () => {
  triggerFilter()
})

watch(
  () => route.query.q,
  (value) => {
    const q = typeof value === 'string' ? value.trim() : ''
    if (q === keyword.value) return
    keyword.value = q
  },
)
</script>

<template>
  <el-card shadow="never">
    <template #header>
      <div class="header">
        <strong>开始训练</strong>
        <div class="ops">
          <el-input v-model="keyword" clearable placeholder="搜索案例标题" style="width: 220px" />
          <el-select v-model="chatType" clearable placeholder="聊天类型" style="width: 140px">
            <el-option label="主动聊天" value="active" />
            <el-option label="被动聊天" value="passive" />
          </el-select>
          <el-select v-model="category" clearable filterable placeholder="分类" style="width: 160px">
            <el-option v-for="item in categoryOptions" :key="item.name" :label="`${item.name} (${item.count})`" :value="item.name" />
          </el-select>
          <el-select v-model="tag" clearable filterable placeholder="标签" style="width: 180px">
            <el-option v-for="item in tagOptions" :key="item.name" :label="`${item.name} (${item.count})`" :value="item.name" />
          </el-select>
          <el-button type="success" :loading="randomStarting" @click="onStartRandom">随机训练</el-button>
          <el-button type="primary" @click="onFilter">筛选</el-button>
        </div>
      </div>
    </template>
    <AdminTableSkeleton v-if="!isMobile && loading" :is-mobile="false" :rows="8" />
    <el-table v-else-if="!isMobile" class="admin-list-table" :data="rows" border stripe>
      <el-table-column prop="id" label="编号" width="80" />
      <el-table-column prop="title" label="案例标题" min-width="260" />
      <el-table-column label="来源" width="180">
        <template #default="{ row }">
          <el-tag size="small" :type="row.scope === 'common' ? 'success' : 'info'">
            {{
              row.scope === 'common'
                ? '通用案例库'
                : row.scope === 'department'
                  ? `科室专属${row.department_name ? `（${row.department_name}）` : ''}`
                  : `医院专属${row.hospital_name ? `（${row.hospital_name}）` : ''}`
            }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="聊天类型" width="120">
        <template #default="{ row }">
          <el-tag :type="row.chat_type === 'active' ? 'success' : 'warning'">
            {{ row.chat_type === 'active' ? '主动聊天' : '被动聊天' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="category" label="分类" width="120" />
      <el-table-column prop="tags" label="标签" min-width="180" />
      <el-table-column prop="difficulty" label="难度" width="90" />
      <el-table-column prop="message_count" label="消息数" width="90" />
      <el-table-column label="操作" width="120">
        <template #default="{ row }">
          <el-button type="primary" link @click="onStart(row.id)">开始训练</el-button>
        </template>
      </el-table-column>
    </el-table>

    <div v-else class="mobile-list">
      <AdminTableSkeleton v-if="loading" :is-mobile="true" :mobile-rows="4" />
      <el-empty v-else-if="!rows.length" description="暂无可训练案例" />
      <template v-else>
        <el-card v-for="row in rows" :key="row.id" class="mobile-item" shadow="never">
          <div class="mobile-title-row">
            <strong>{{ row.title }}</strong>
            <el-tag size="small" :type="row.chat_type === 'active' ? 'success' : 'warning'">
              {{ row.chat_type === 'active' ? '主动聊天' : '被动聊天' }}
            </el-tag>
          </div>
          <div class="meta">
            来源：{{
              row.scope === 'common'
                ? '通用案例库'
                : row.scope === 'department'
                  ? `科室专属${row.department_name ? `（${row.department_name}）` : ''}`
                  : `医院专属${row.hospital_name ? `（${row.hospital_name}）` : ''}`
            }}
          </div>
          <div class="meta">分类：{{ row.category || '-' }}</div>
          <div class="meta">标签：{{ row.tags || '-' }}</div>
          <div class="meta">难度：{{ row.difficulty }} | 消息数：{{ row.message_count }}</div>
          <div class="actions">
            <el-button type="primary" size="small" @click="onStart(row.id)">开始训练</el-button>
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
.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.ops {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}

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
  margin-top: 10px;
  display: flex;
  justify-content: flex-end;
}

.pager {
  margin-top: var(--space-3);
  display: flex;
  justify-content: flex-end;
}

@media (max-width: 768px) {
  .header {
    align-items: flex-start;
    flex-direction: column;
    gap: 8px;
  }
  .pager {
    justify-content: center;
  }
}
</style>
