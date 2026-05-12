<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  getFaqClusterDetail,
  updateFaqCluster,
  toggleBestAnswer,
  upvoteAnswer,
  deleteFaqCluster,
  type FaqClusterDetailData,
} from '../../api/faq'

const route = useRoute()
const router = useRouter()
const loading = ref(false)
const saving = ref(false)
const detail = ref<FaqClusterDetailData | null>(null)
const editMode = ref(false)
const editTitle = ref('')
const editCategory = ref('')
const editBestAnswer = ref('')

const clusterId = Number(route.params.id)

const load = async () => {
  loading.value = true
  try {
    detail.value = await getFaqClusterDetail(clusterId)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '加载失败')
  } finally {
    loading.value = false
  }
}

const enterEdit = () => {
  if (!detail.value) return
  editTitle.value = detail.value.cluster.title
  editCategory.value = detail.value.cluster.category || ''
  editBestAnswer.value = detail.value.cluster.best_answer || ''
  editMode.value = true
}

const saveEdit = async () => {
  saving.value = true
  try {
    await updateFaqCluster(clusterId, {
      title: editTitle.value.trim(),
      category: editCategory.value.trim() || null,
      best_answer: editBestAnswer.value.trim() || null,
    } as any)
    ElMessage.success('已保存')
    editMode.value = false
    await load()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '保存失败')
  } finally {
    saving.value = false
  }
}

const handleToggleBest = async (answerId: number) => {
  try {
    await toggleBestAnswer(answerId)
    await load()
  } catch {
    ElMessage.error('操作失败')
  }
}

const handleUpvote = async (answerId: number) => {
  try {
    await upvoteAnswer(answerId)
    await load()
  } catch {
    ElMessage.error('操作失败')
  }
}

const handleDelete = async () => {
  try {
    await ElMessageBox.confirm('确认删除此 FAQ 条目？相关问题和答案将一并删除。', '确认删除', { type: 'warning' })
    await deleteFaqCluster(clusterId)
    ElMessage.success('已删除')
    router.push('/admin/faq/clusters')
  } catch { /* cancelled */ }
}

onMounted(load)
</script>

<template>
  <div v-loading="loading" class="cluster-detail">
    <template v-if="detail">
      <div class="detail-header">
        <div class="detail-header-main">
          <div class="breadcrumb-nav">
            <el-button link @click="router.push('/admin/faq/clusters')">← 返回知识库</el-button>
          </div>
          <template v-if="!editMode">
            <h2 class="cluster-title">{{ detail.cluster.title }}</h2>
            <div class="cluster-meta">
              <el-tag v-if="detail.cluster.category" size="small">{{ detail.cluster.category }}</el-tag>
              <span class="meta-text">{{ detail.cluster.question_count }} 个问题 · {{ detail.cluster.answer_count }} 个回答</span>
              <el-tag :type="detail.cluster.is_active ? 'success' : 'info'" size="small">
                {{ detail.cluster.is_active ? '已启用' : '已停用' }}
              </el-tag>
            </div>
            <p v-if="detail.cluster.summary" class="cluster-summary">{{ detail.cluster.summary }}</p>
          </template>
          <template v-else>
            <el-input v-model="editTitle" placeholder="FAQ 标题" style="max-width: 500px; margin-bottom: 8px" />
            <el-input v-model="editCategory" placeholder="分类" style="max-width: 300px" />
          </template>
        </div>
        <div class="detail-header-actions">
          <template v-if="!editMode">
            <el-button @click="enterEdit">编辑</el-button>
            <el-button type="danger" plain @click="handleDelete">删除</el-button>
          </template>
          <template v-else>
            <el-button @click="editMode = false">取消</el-button>
            <el-button type="primary" :loading="saving" @click="saveEdit">保存</el-button>
          </template>
        </div>
      </div>

      <div class="qa-layout">
        <el-card shadow="never" class="qa-panel questions-panel">
          <template #header>
            <strong>患者问题归类 ({{ detail.questions.length }})</strong>
          </template>
          <div class="question-list">
            <div
              v-for="q in detail.questions"
              :key="q.id"
              class="question-item"
              :class="{ representative: q.is_representative }"
            >
              <div class="question-content">{{ q.content }}</div>
              <div class="question-meta">
                <el-tag v-if="q.is_representative" type="success" size="small">代表性问题</el-tag>
                <span v-if="q.source_context && q.source_context !== q.content" class="source-hint">
                  原文：{{ q.source_context }}
                </span>
                <span v-if="q.quiz_id" class="quiz-link">
                  来源对话 #{{ q.quiz_id }}
                </span>
              </div>
            </div>
            <div v-if="detail.questions.length === 0" class="empty-hint">暂无问题记录</div>
          </div>
        </el-card>

        <el-card shadow="never" class="qa-panel answers-panel">
          <template #header>
            <div class="answers-header">
              <strong>咨询回答 ({{ detail.answers.length }})</strong>
            </div>
          </template>

          <div v-if="detail.cluster.best_answer" class="best-answer-section">
            <div class="best-answer-label">AI 综合最佳回答</div>
            <div v-if="!editMode" class="best-answer-content">{{ detail.cluster.best_answer }}</div>
            <el-input
              v-else
              v-model="editBestAnswer"
              type="textarea"
              :autosize="{ minRows: 3, maxRows: 10 }"
              placeholder="最佳回答"
            />
          </div>

          <div class="answer-list">
            <div
              v-for="a in detail.answers"
              :key="a.id"
              class="answer-item"
              :class="{ best: a.is_best }"
            >
              <div class="answer-content">{{ a.content }}</div>
              <div class="answer-footer">
                <div class="answer-meta">
                  <el-tag v-if="a.is_best" type="success" size="small">最佳</el-tag>
                  <span class="quality-score">质量 {{ (a.quality_score * 100).toFixed(0) }}%</span>
                  <span v-if="a.quiz_id" class="quiz-link">来源 #{{ a.quiz_id }}</span>
                </div>
                <div class="answer-actions">
                  <el-button link size="small" @click="handleUpvote(a.id)">
                    👍 {{ a.upvotes || 0 }}
                  </el-button>
                  <el-button
                    link
                    size="small"
                    :type="a.is_best ? 'warning' : 'success'"
                    @click="handleToggleBest(a.id)"
                  >
                    {{ a.is_best ? '取消最佳' : '设为最佳' }}
                  </el-button>
                </div>
              </div>
            </div>
            <div v-if="detail.answers.length === 0" class="empty-hint">暂无回答记录</div>
          </div>
        </el-card>
      </div>
    </template>
  </div>
</template>

<style scoped>
.cluster-detail {
  display: grid;
  gap: var(--space-4);
}

.detail-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: var(--space-3);
  flex-wrap: wrap;
}

.detail-header-main {
  display: grid;
  gap: 6px;
  flex: 1;
  min-width: 0;
}

.breadcrumb-nav {
  margin-bottom: 4px;
}

.cluster-title {
  margin: 0;
  font-size: var(--font-size-h4);
  line-height: var(--line-height-tight);
}

.cluster-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.meta-text {
  font-size: var(--font-size-xs);
  color: var(--el-text-color-secondary);
}

.cluster-summary {
  margin: 0;
  color: var(--el-text-color-secondary);
  font-size: var(--font-size-sm);
}

.detail-header-actions {
  display: flex;
  gap: var(--space-2);
  flex-shrink: 0;
}

.qa-layout {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-3);
  align-items: start;
}

@media (max-width: 900px) {
  .qa-layout { grid-template-columns: 1fr; }
}

.qa-panel {
  max-height: 70vh;
  overflow-y: auto;
}

.answers-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.question-list, .answer-list {
  display: grid;
  gap: 10px;
}

.question-item {
  padding: 12px 14px;
  border-radius: 10px;
  border: 1px solid var(--ui-border-soft);
  background: var(--ui-surface-1);
  transition: border-color 0.15s;
}

.question-item.representative {
  border-color: var(--el-color-success-light-3);
  background: color-mix(in srgb, var(--el-color-success-light-9) 40%, var(--ui-surface-1) 60%);
}

.question-content {
  font-size: var(--font-size-sm);
  line-height: 1.5;
}

.question-meta {
  margin-top: 6px;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.source-hint {
  font-size: 11px;
  color: var(--el-text-color-placeholder);
  font-style: italic;
}

.quiz-link {
  font-size: 11px;
  color: var(--el-color-primary);
}

.best-answer-section {
  padding: 14px;
  border-radius: 12px;
  border: 2px solid var(--el-color-success-light-3);
  background: color-mix(in srgb, var(--el-color-success-light-9) 30%, var(--ui-surface-1) 70%);
  margin-bottom: var(--space-3);
}

.best-answer-label {
  font-weight: 700;
  font-size: var(--font-size-xs);
  color: var(--el-color-success);
  margin-bottom: 6px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.best-answer-content {
  font-size: var(--font-size-sm);
  line-height: 1.6;
  white-space: pre-wrap;
}

.answer-item {
  padding: 12px 14px;
  border-radius: 10px;
  border: 1px solid var(--ui-border-soft);
  background: var(--ui-surface-1);
}

.answer-item.best {
  border-color: var(--el-color-warning-light-3);
}

.answer-content {
  font-size: var(--font-size-sm);
  line-height: 1.5;
  white-space: pre-wrap;
}

.answer-footer {
  margin-top: 8px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
}

.answer-meta {
  display: flex;
  align-items: center;
  gap: 8px;
}

.quality-score {
  font-size: 11px;
  color: var(--el-text-color-secondary);
}

.answer-actions {
  display: flex;
  gap: 4px;
}

.empty-hint {
  text-align: center;
  color: var(--el-text-color-placeholder);
  padding: 20px 0;
}
</style>
