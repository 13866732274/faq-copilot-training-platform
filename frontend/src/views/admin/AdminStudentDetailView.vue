<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  addPracticeComment,
  deletePracticeComment,
  getStudentPracticeDetail,
  getStudentPractices,
  type StudentPracticeDetail,
  type StudentPracticeItem,
  updatePracticeComment,
} from '../../api/stats'
import MessageContent from '../../components/chat/MessageContent.vue'
import AdminTableSkeleton from '../../components/admin/AdminTableSkeleton.vue'
import {
  DRAWER_DESKTOP_SIZE,
  UI_TEXT,
  buildPositionText,
  confirmDangerousAction,
  getDrawerSize,
} from '../../composables/useUiStandards'

const route = useRoute()
const userId = Number(route.params.userId)
const listLoading = ref(false)
const detailLoading = ref(false)
const practices = ref<StudentPracticeItem[]>([])
const detail = ref<StudentPracticeDetail | null>(null)
const commentText = ref('')
const selectedPracticeId = ref<number | null>(null)
const isMobile = ref(false)
const detailDrawerVisible = ref(false)
const pager = reactive({ page: 1, page_size: 10, total: 0 })

const statusText = (status: string) => {
  if (status === 'completed') return '已完成'
  if (status === 'in_progress') return '进行中'
  return status
}

const currentPracticeIndex = computed(() => {
  if (!selectedPracticeId.value) return -1
  return practices.value.findIndex((p) => p.practice_id === selectedPracticeId.value)
})
const currentPracticeGlobalIndex = computed(() => {
  if (currentPracticeIndex.value < 0) return -1
  return (pager.page - 1) * pager.page_size + currentPracticeIndex.value
})

const canViewPrev = computed(() => currentPracticeGlobalIndex.value > 0)
const canViewNext = computed(() => currentPracticeGlobalIndex.value >= 0 && currentPracticeGlobalIndex.value < pager.total - 1)
const positionText = computed(() => {
  return buildPositionText(currentPracticeGlobalIndex.value, pager.total)
})

const loadPractices = async () => {
  listLoading.value = true
  try {
    const data = await getStudentPractices(userId, { page: pager.page, page_size: pager.page_size })
    practices.value = data.items
    pager.total = data.total
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || '获取咨询员训练记录失败')
  } finally {
    listLoading.value = false
  }
}

const loadDetail = async (practiceId: number) => {
  selectedPracticeId.value = practiceId
  detailLoading.value = true
  try {
    detail.value = await getStudentPracticeDetail(userId, practiceId)
    detailDrawerVisible.value = true
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || '获取训练详情失败')
  } finally {
    detailLoading.value = false
  }
}

const openPracticeByGlobalIndex = async (globalIndex: number) => {
  if (globalIndex < 0 || globalIndex >= pager.total) return
  const targetPage = Math.floor(globalIndex / pager.page_size) + 1
  const targetIndexInPage = globalIndex % pager.page_size
  if (targetPage !== pager.page) {
    pager.page = targetPage
    await loadPractices()
  }
  const target = practices.value[targetIndexInPage]
  if (!target) return
  await loadDetail(target.practice_id)
}

const viewPrev = async () => {
  if (!canViewPrev.value || detailLoading.value) return
  await openPracticeByGlobalIndex(currentPracticeGlobalIndex.value - 1)
}

const viewNext = async () => {
  if (!canViewNext.value || detailLoading.value) return
  await openPracticeByGlobalIndex(currentPracticeGlobalIndex.value + 1)
}

const submitComment = async () => {
  if (!selectedPracticeId.value || !commentText.value.trim()) return
  try {
    await addPracticeComment(selectedPracticeId.value, commentText.value.trim())
    commentText.value = ''
    ElMessage.success('点评已添加')
    await loadDetail(selectedPracticeId.value)
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || '添加点评失败')
  }
}

const editComment = async (commentId: number, oldContent: string) => {
  try {
    const { value } = await ElMessageBox.prompt('修改点评内容', '编辑点评', {
      inputValue: oldContent,
      confirmButtonText: '保存',
      cancelButtonText: '取消',
    })
    await updatePracticeComment(commentId, value)
    ElMessage.success('点评已更新')
    if (selectedPracticeId.value) await loadDetail(selectedPracticeId.value)
  } catch (error: any) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(error?.response?.data?.detail || '编辑点评失败')
  }
}

const removeComment = async (commentId: number) => {
  try {
    await confirmDangerousAction('确认删除该点评？', '删除确认')
    await deletePracticeComment(commentId)
    ElMessage.success('点评已删除')
    if (selectedPracticeId.value) await loadDetail(selectedPracticeId.value)
  } catch (error: any) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(error?.response?.data?.detail || '删除点评失败')
  }
}

onMounted(loadPractices)

const onPracticePageChange = () => loadPractices()

const updateViewport = () => {
  isMobile.value = window.innerWidth < 992
}

onMounted(() => {
  updateViewport()
  window.addEventListener('resize', updateViewport)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', updateViewport)
})
</script>

<template>
  <el-card shadow="never">
    <template #header>
      <div class="admin-card-header">
        <strong class="admin-card-title">咨询员训练详情</strong>
      </div>
    </template>
    <AdminTableSkeleton v-if="listLoading" :is-mobile="isMobile" :rows="8" :mobile-rows="4" />
    <el-table v-else-if="!isMobile" class="admin-list-table" :data="practices" border stripe>
      <el-table-column prop="practice_id" label="练习ID" width="90" />
      <el-table-column prop="quiz_title" label="案例标题" min-width="240" />
      <el-table-column label="状态" width="120">
        <template #default="{ row }">
          <el-tag size="small" :type="row.status === 'completed' ? 'success' : 'warning'">
            {{ statusText(row.status) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="started_at" label="开始时间" width="180" />
      <el-table-column prop="completed_at" label="完成时间" width="180" />
      <el-table-column label="操作" width="100">
        <template #default="{ row }">
          <el-button link type="primary" @click="loadDetail(row.practice_id)">查看</el-button>
        </template>
      </el-table-column>
    </el-table>
    <div v-else class="admin-mobile-list">
      <el-empty v-if="!practices.length" class="admin-empty" description="暂无训练记录" />
      <template v-else>
        <el-card v-for="row in practices" :key="row.practice_id" class="admin-mobile-item" shadow="never">
          <div class="admin-mobile-title-row">
            <strong>{{ row.quiz_title }}</strong>
            <el-tag size="small" :type="row.status === 'completed' ? 'success' : 'warning'">
              {{ statusText(row.status) }}
            </el-tag>
          </div>
          <div class="admin-mobile-meta">开始：{{ row.started_at }}</div>
          <div class="admin-mobile-meta">完成：{{ row.completed_at || '-' }}</div>
          <div class="admin-mobile-actions">
            <el-button link type="primary" @click="loadDetail(row.practice_id)">查看详情</el-button>
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
        @size-change="onPracticePageChange"
        @current-change="onPracticePageChange"
      />
    </div>

    <el-drawer
      v-model="detailDrawerVisible"
      class="admin-smooth-drawer detail-drawer"
      :size="getDrawerSize(isMobile, DRAWER_DESKTOP_SIZE.detail)"
      direction="rtl"
      :with-header="false"
    >
      <div v-if="detail" class="drawer-body admin-drawer-body">
        <div class="drawer-title admin-drawer-header">
          <strong>练习详情 - {{ detail.quiz_title }}<span v-if="positionText">（{{ positionText }}）</span></strong>
          <div class="drawer-actions admin-drawer-actions">
            <el-button :disabled="!canViewPrev || detailLoading" @click="viewPrev">上一条</el-button>
            <el-button :disabled="!canViewNext || detailLoading" @click="viewNext">下一条</el-button>
            <el-button link type="primary" @click="detailDrawerVisible = false">{{ UI_TEXT.close }}</el-button>
          </div>
        </div>

        <div v-for="(round, idx) in detail.dialogues" :key="idx" class="round">
          <h4>第 {{ idx + 1 }} 轮</h4>
          <div v-for="(m, i) in round.patient_messages" :key="i">
            患者：<MessageContent :content-type="m.content_type || 'text'" :content="m.content" />
          </div>
          <div class="compare">
            <div class="col std">
              <div class="head">标准答案</div>
              <MessageContent
                :content-type="round.standard_answer.content_type || 'text'"
                :content="round.standard_answer.content"
              />
            </div>
            <div class="col mine">
              <div class="head">咨询员回复</div>
              <div>{{ round.student_reply?.content || '（未作答）' }}</div>
            </div>
          </div>
        </div>

        <el-card shadow="never">
          <template #header>管理员点评</template>
          <el-empty v-if="!detail.comments.length" class="admin-empty" description="暂无点评" />
          <div v-for="c in detail.comments" :key="c.comment_id" class="comment-item">
            <div class="comment-line">
              <div><strong>{{ c.admin_name }}</strong>（{{ c.created_at }}）：{{ c.content }}</div>
              <div class="comment-actions">
                <el-button link type="primary" @click="editComment(c.comment_id, c.content)">编辑</el-button>
                <el-button link type="danger" @click="removeComment(c.comment_id)">删除</el-button>
              </div>
            </div>
          </div>
        </el-card>

        <el-card shadow="never" style="margin-top: 12px">
          <template #header>添加点评</template>
          <el-input v-model="commentText" type="textarea" :rows="3" placeholder="输入点评内容" />
          <div style="text-align: right; margin-top: 8px">
            <el-button type="primary" @click="submitComment">提交点评</el-button>
          </div>
        </el-card>
      </div>
    </el-drawer>
  </el-card>
</template>

<style scoped>
.round {
  border: 1px solid var(--el-border-color);
  border-radius: var(--radius-sm);
  padding: 10px;
  margin-bottom: var(--space-3);
  background: var(--el-bg-color);
}
.compare {
  margin-top: var(--space-2);
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-2);
}
.col {
  border-radius: var(--radius-sm);
  padding: var(--space-2);
}
.std {
  background: color-mix(in srgb, var(--el-color-primary-light-9) 88%, var(--el-bg-color) 12%);
}
.mine {
  background: color-mix(in srgb, var(--el-color-warning-light-9) 82%, var(--el-bg-color) 18%);
}
.head {
  font-weight: 600;
  margin-bottom: var(--space-1);
  color: var(--el-text-color-primary);
}

:global(.dark) .round {
  background: #181b20;
  border-color: #4a5160;
}

:global(.dark) .std {
  background: #1d2d3f;
}

:global(.dark) .mine {
  background: #3a3423;
}
.comment-item {
  margin-bottom: var(--space-2);
}
.comment-line {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
}
.comment-actions {
  white-space: nowrap;
}

@media (max-width: 768px) {
  .compare {
    grid-template-columns: 1fr;
  }
}
</style>
