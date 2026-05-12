<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import { getQuizDetail, updateQuiz, type QuizDetailData, type UpdateQuizPayload } from '../../api/quiz'
import AdminTableSkeleton from '../../components/admin/AdminTableSkeleton.vue'
import { getHospitals, type HospitalItem } from '../../api/hospital'
import { getDepartments, type DepartmentItem } from '../../api/department'
import { evaluatePermissionPoint } from '../../utils/permissionPoints'
import { useUserStore } from '../../stores/user'

const route = useRoute()
const router = useRouter()
const loading = ref(false)
const detail = ref<QuizDetailData | null>(null)
const isMobile = ref(false)
const pager = reactive({ page: 1, page_size: 20 })
const userStore = useUserStore()
const isSuperAdmin = ref(false)
const hospitals = ref<HospitalItem[]>([])
const departments = ref<DepartmentItem[]>([])
const updatePerm = computed(() => evaluatePermissionPoint('quiz.update'))
const editDialogVisible = ref(false)
const editSaving = ref(false)
const editFormRef = ref<FormInstance>()
const editForm = reactive<{
  id: number | null
  title: string
  scope: 'common' | 'hospital' | 'department'
  hospital_id?: number
  department_id?: number
  chat_type: 'active' | 'passive'
  category: string
  difficulty: number
  tags: string
  description: string
  patient_name: string
  counselor_name: string
}>({
  id: null,
  title: '',
  scope: 'hospital',
  hospital_id: undefined,
  department_id: undefined,
  chat_type: 'passive',
  category: '',
  difficulty: 1,
  tags: '',
  description: '',
  patient_name: '',
  counselor_name: '',
})
const editRules: FormRules = {
  title: [{ required: true, message: '请输入案例标题', trigger: 'blur' }],
  chat_type: [{ required: true, message: '请选择聊天类型', trigger: 'change' }],
  difficulty: [{ required: true, message: '请选择难度', trigger: 'change' }],
}

const load = async () => {
  const id = Number(route.params.id)
  if (!id) return
  loading.value = true
  try {
    detail.value = await getQuizDetail(id)
    pager.page = 1
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || '获取案例详情失败')
  } finally {
    loading.value = false
  }
}

const pagedMessages = computed(() => {
  if (!detail.value) return []
  const start = (pager.page - 1) * pager.page_size
  return detail.value.messages.slice(start, start + pager.page_size)
})

const isLikelyMediaLink = (value?: string | null) => {
  const v = (value || '').trim().toLowerCase()
  if (!v) return false
  if (v.startsWith('http://') || v.startsWith('https://') || v.startsWith('/')) return true
  return (
    v.includes('/uploads/') ||
    v.includes('.png') ||
    v.includes('.jpg') ||
    v.includes('.jpeg') ||
    v.includes('.gif') ||
    v.includes('.webp') ||
    v.includes('.bmp') ||
    v.includes('.mp3') ||
    v.includes('.wav') ||
    v.includes('.amr') ||
    v.includes('.aac') ||
    v.includes('.m4a') ||
    v.includes('.ogg') ||
    v.includes('.opus')
  )
}

const formatMessageContent = (msg: { content_type?: string; content?: string | null }) => {
  const text = (msg.content || '').trim()
  if (msg.content_type === 'image') return text ? (isLikelyMediaLink(text) ? `[图片链接] ${text}` : text) : '【图片消息占位】'
  if (msg.content_type === 'audio') return text ? (isLikelyMediaLink(text) ? `[语音链接] ${text}` : text) : '【语音消息占位】'
  return text || '-'
}

const updateViewport = () => {
  isMobile.value = window.innerWidth < 992
}

const departmentOptionsByHospital = (hospitalId?: number) => {
  if (!hospitalId) return departments.value
  return departments.value.filter((d) => d.hospital_id === hospitalId)
}

const fillEditForm = (data: QuizDetailData) => {
  editForm.id = data.id
  editForm.title = data.title || ''
  editForm.scope = data.scope
  editForm.hospital_id = data.hospital_id || undefined
  editForm.department_id = data.department_id || undefined
  editForm.chat_type = data.chat_type
  editForm.category = data.category || ''
  editForm.difficulty = data.difficulty || 1
  editForm.tags = data.tags || ''
  editForm.description = data.description || ''
  editForm.patient_name = data.patient_name || ''
  editForm.counselor_name = data.counselor_name || ''
}

const loadHospitals = async () => {
  try {
    hospitals.value = await getHospitals({ active_only: true })
  } catch {
    hospitals.value = []
  }
}

const loadDepartments = async () => {
  try {
    departments.value = await getDepartments({ active_only: true })
  } catch {
    departments.value = []
  }
}

const openEditDialog = () => {
  if (!updatePerm.value.allowed) {
    ElMessage.warning(updatePerm.value.reason)
    return
  }
  if (!detail.value) return
  fillEditForm(detail.value)
  editDialogVisible.value = true
}

const onEditScopeChange = () => {
  if (editForm.scope === 'common') {
    editForm.hospital_id = undefined
    editForm.department_id = undefined
    return
  }
  if (editForm.scope === 'hospital') {
    editForm.department_id = undefined
  }
}

const onEditHospitalChange = () => {
  if (editForm.scope === 'department') {
    editForm.department_id = undefined
  }
}

const submitEdit = async () => {
  if (!editForm.id || !editFormRef.value) return
  const valid = await editFormRef.value.validate().catch(() => false)
  if (!valid) return
  const payload: UpdateQuizPayload = {
    title: editForm.title.trim(),
    scope: editForm.scope,
    chat_type: editForm.chat_type,
    category: editForm.category.trim() || undefined,
    difficulty: editForm.difficulty,
    tags: editForm.tags.trim() || undefined,
    description: editForm.description.trim() || undefined,
    patient_name: editForm.patient_name.trim() || undefined,
    counselor_name: editForm.counselor_name.trim() || undefined,
    hospital_id: editForm.scope === 'hospital' ? editForm.hospital_id : undefined,
    department_id: editForm.scope === 'department' ? editForm.department_id : undefined,
  }
  editSaving.value = true
  try {
    await updateQuiz(editForm.id, payload)
    ElMessage.success('案例已更新')
    editDialogVisible.value = false
    await load()
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || '更新失败')
  } finally {
    editSaving.value = false
  }
}

onMounted(() => {
  updateViewport()
  isSuperAdmin.value = userStore.user?.role === 'super_admin'
  loadHospitals()
  loadDepartments()
  window.addEventListener('resize', updateViewport)
  load()
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', updateViewport)
})
</script>

<template>
  <el-card shadow="never">
    <template #header>
      <div class="admin-card-header">
        <strong class="admin-card-title">案例详情</strong>
        <div class="admin-card-header-actions">
          <el-tooltip :disabled="updatePerm.allowed" :content="updatePerm.reason" placement="top">
            <span>
              <el-button :disabled="!updatePerm.allowed" @click="openEditDialog">编辑案例</el-button>
            </span>
          </el-tooltip>
          <el-button @click="router.push('/admin/quizzes')">返回列表</el-button>
        </div>
      </div>
    </template>

    <AdminTableSkeleton v-if="loading" :is-mobile="isMobile" :rows="10" :mobile-rows="5" />
    <template v-else-if="detail">
      <el-descriptions :column="isMobile ? 1 : 2" border>
        <el-descriptions-item label="编号">{{ detail.id }}</el-descriptions-item>
        <el-descriptions-item label="标题">{{ detail.title }}</el-descriptions-item>
        <el-descriptions-item label="范围">
          {{ detail.scope === 'common' ? '通用案例库' : detail.scope === 'department' ? '科室专属' : '医院专属' }}
        </el-descriptions-item>
        <el-descriptions-item label="所属医院">{{ detail.hospital_name || '-' }}</el-descriptions-item>
        <el-descriptions-item label="所属科室">{{ detail.department_name || '-' }}</el-descriptions-item>
        <el-descriptions-item label="聊天类型">
          {{ detail.chat_type === 'active' ? '主动聊天' : '被动聊天' }}
        </el-descriptions-item>
        <el-descriptions-item label="分类">{{ detail.category || '-' }}</el-descriptions-item>
        <el-descriptions-item label="难度">{{ detail.difficulty }}</el-descriptions-item>
        <el-descriptions-item label="患者">{{ detail.patient_name || '-' }}</el-descriptions-item>
        <el-descriptions-item label="咨询师">{{ detail.counselor_name || '-' }}</el-descriptions-item>
      </el-descriptions>

      <el-card shadow="never" style="margin-top: 12px">
        <template #header>
          <div class="admin-card-header">
            <strong class="admin-card-title">版本记录</strong>
          </div>
        </template>
        <el-empty v-if="!detail.versions?.length" class="admin-empty" description="暂无版本记录" />
        <el-table v-else-if="!isMobile" class="admin-list-table" :data="detail.versions" border stripe>
          <el-table-column prop="version_no" label="版本号" width="100" />
          <el-table-column prop="message_count" label="消息数" width="100" />
          <el-table-column prop="source_file" label="来源文件" min-width="260" />
          <el-table-column prop="created_at" label="创建时间" width="180" />
        </el-table>
        <div v-else class="admin-mobile-list">
          <el-card v-for="v in detail.versions" :key="v.id" class="admin-mobile-item" shadow="never">
            <div class="admin-mobile-title-row">
              <strong>V{{ v.version_no }}</strong>
              <el-tag size="small" type="info">{{ v.message_count }} 条</el-tag>
            </div>
            <div class="admin-mobile-meta">文件：{{ v.source_file || '-' }}</div>
            <div class="admin-mobile-meta">时间：{{ v.created_at }}</div>
          </el-card>
        </div>
      </el-card>

      <el-table v-if="!isMobile" class="admin-list-table" :data="pagedMessages" border stripe style="margin-top: 16px">
        <el-table-column prop="sequence" label="#" width="60" />
        <el-table-column prop="role" label="角色" width="100" />
        <el-table-column prop="sender_name" label="发送者" width="140" />
        <el-table-column prop="content_type" label="类型" width="90" />
        <el-table-column label="内容" min-width="300">
          <template #default="{ row }">
            {{ formatMessageContent(row) }}
          </template>
        </el-table-column>
        <el-table-column prop="original_time" label="时间" width="180" />
      </el-table>
      <div v-else class="admin-mobile-list" style="margin-top: 12px">
        <el-card v-for="msg in pagedMessages" :key="msg.sequence" class="admin-mobile-item" shadow="never">
          <div class="admin-mobile-title-row">
            <strong>#{{ msg.sequence }}</strong>
            <el-tag size="small" :type="msg.role === 'patient' ? 'info' : 'success'">
              {{ msg.role === 'patient' ? '患者' : '咨询师' }}
            </el-tag>
          </div>
          <div class="admin-mobile-meta">发送者：{{ msg.sender_name || '-' }}</div>
          <div class="admin-mobile-meta">类型：{{ msg.content_type }}</div>
          <div class="admin-mobile-meta">内容：{{ formatMessageContent(msg) }}</div>
          <div class="admin-mobile-meta">时间：{{ msg.original_time || '-' }}</div>
        </el-card>
      </div>
      <div class="admin-pager">
        <el-pagination
          v-model:current-page="pager.page"
          v-model:page-size="pager.page_size"
          :page-sizes="[10, 20, 50, 100]"
          :layout="isMobile ? 'prev, pager, next' : 'total, sizes, prev, pager, next, jumper'"
          :small="isMobile"
          :total="detail.messages.length"
          @size-change="pager.page = 1"
        />
      </div>
    </template>

    <el-dialog
      v-model="editDialogVisible"
      title="编辑案例"
      :width="isMobile ? '96%' : '720px'"
      destroy-on-close
    >
      <el-form ref="editFormRef" :model="editForm" :rules="editRules" label-width="96px">
        <el-form-item label="案例标题" prop="title">
          <el-input v-model="editForm.title" maxlength="200" show-word-limit />
        </el-form-item>
        <el-form-item label="聊天类型" prop="chat_type">
          <el-select v-model="editForm.chat_type" class="w-full">
            <el-option label="主动聊天" value="active" />
            <el-option label="被动聊天" value="passive" />
          </el-select>
        </el-form-item>
        <el-form-item label="分类">
          <el-input v-model="editForm.category" maxlength="50" show-word-limit />
        </el-form-item>
        <el-form-item label="难度" prop="difficulty">
          <el-input-number v-model="editForm.difficulty" :min="1" :max="5" />
        </el-form-item>
        <el-form-item label="标签">
          <el-input v-model="editForm.tags" maxlength="500" show-word-limit />
        </el-form-item>
        <el-form-item label="患者名">
          <el-input v-model="editForm.patient_name" maxlength="100" show-word-limit />
        </el-form-item>
        <el-form-item label="咨询师名">
          <el-input v-model="editForm.counselor_name" maxlength="100" show-word-limit />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="editForm.description" type="textarea" :rows="3" />
        </el-form-item>
        <template v-if="isSuperAdmin">
          <el-form-item label="案例库范围">
            <el-select v-model="editForm.scope" class="w-full" @change="onEditScopeChange">
              <el-option label="通用案例库" value="common" />
              <el-option label="医院专属" value="hospital" />
              <el-option label="科室专属" value="department" />
            </el-select>
          </el-form-item>
          <el-form-item v-if="editForm.scope !== 'common'" label="所属医院">
            <el-select v-model="editForm.hospital_id" class="w-full" clearable @change="onEditHospitalChange">
              <el-option v-for="h in hospitals" :key="h.id" :label="h.name" :value="h.id" />
            </el-select>
          </el-form-item>
          <el-form-item v-if="editForm.scope === 'department'" label="所属科室">
            <el-select v-model="editForm.department_id" class="w-full" clearable>
              <el-option
                v-for="d in departmentOptionsByHospital(editForm.hospital_id)"
                :key="d.id"
                :label="d.name"
                :value="d.id"
              />
            </el-select>
          </el-form-item>
        </template>
      </el-form>
      <template #footer>
        <el-button @click="editDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="editSaving" @click="submitEdit">保存修改</el-button>
      </template>
    </el-dialog>
  </el-card>
</template>

<style scoped>
.w-full {
  width: 100%;
}
</style>
