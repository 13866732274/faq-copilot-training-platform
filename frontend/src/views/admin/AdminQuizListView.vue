<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import {
  getQuizDetail,
  getQuizList,
  getQuizMetaOptions,
  hardDeleteQuiz,
  restoreQuiz,
  softDeleteQuiz,
  batchUpdateQuizMeta,
  updateQuiz,
  type QuizDetailData,
  type QuizListItem,
  type UpdateQuizPayload,
} from '../../api/quiz'
import { getHospitals, type HospitalItem } from '../../api/hospital'
import { getDepartments, type DepartmentItem } from '../../api/department'
import { useUserStore } from '../../stores/user'
import AdminTableSkeleton from '../../components/admin/AdminTableSkeleton.vue'
import {
  DRAWER_DESKTOP_SIZE,
  UI_TEXT,
  buildPositionText,
  confirmDangerousAction,
  createDebouncedFn,
  getDrawerSize,
} from '../../composables/useUiStandards'
import { evaluatePermissionPoint } from '../../utils/permissionPoints'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()
const isSuperAdmin = ref(false)
const loading = ref(false)
const rows = ref<QuizListItem[]>([])
const selectedRows = ref<QuizListItem[]>([])
const hospitals = ref<HospitalItem[]>([])
const departments = ref<DepartmentItem[]>([])
const categoryOptions = ref<Array<{ name: string; count: number }>>([])
const tagOptions = ref<Array<{ name: string; count: number }>>([])
const isMobile = ref(false)
const mobileFilterOpen = ref(false)
const detailDrawerVisible = ref(false)
const detailLoading = ref(false)
const detail = ref<QuizDetailData | null>(null)
const editDialogVisible = ref(false)
const editSaving = ref(false)
const editLoading = ref(false)
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
const selectedQuizId = ref<number | null>(null)
const recycleMode = ref(false)
const detailPager = reactive({ page: 1, page_size: 20 })
const pager = reactive({
  page: 1,
  page_size: 20,
  total: 0,
  keyword: '',
  scope: '' as '' | 'common' | 'hospital' | 'department',
  hospital_id: undefined as number | undefined,
  department_id: undefined as number | undefined,
  chat_type: '' as '' | 'active' | 'passive',
})

const departmentOptionsByHospital = (hospitalId?: number) => {
  if (!hospitalId) return departments.value
  return departments.value.filter((d) => d.hospital_id === hospitalId)
}

const detailMessages = computed(() => {
  if (!detail.value) return []
  const start = (detailPager.page - 1) * detailPager.page_size
  return detail.value.messages.slice(start, start + detailPager.page_size)
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

const scopeText = (scope: 'common' | 'hospital' | 'department') => {
  if (scope === 'common') return '通用案例库'
  if (scope === 'department') return '科室专属'
  return '医院专属'
}

const currentQuizIndex = computed(() => {
  if (!selectedQuizId.value) return -1
  return rows.value.findIndex((q) => q.id === selectedQuizId.value)
})

const canViewPrev = computed(() => currentQuizIndex.value > 0)
const canViewNext = computed(() => currentQuizIndex.value >= 0 && currentQuizIndex.value < rows.value.length - 1)
const restorePerm = computed(() => evaluatePermissionPoint('quiz.restore'))
const softDeletePerm = computed(() => evaluatePermissionPoint('quiz.delete.soft'))
const hardDeletePerm = computed(() => evaluatePermissionPoint('quiz.delete.hard'))
const updatePerm = computed(() => evaluatePermissionPoint('quiz.update'))
const positionText = computed(() => {
  return buildPositionText(currentQuizIndex.value, rows.value.length)
})
const editRules: FormRules = {
  title: [{ required: true, message: '请输入案例标题', trigger: 'blur' }],
  chat_type: [{ required: true, message: '请选择聊天类型', trigger: 'change' }],
  difficulty: [{ required: true, message: '请选择难度', trigger: 'change' }],
}

const load = async () => {
  loading.value = true
  try {
    const data = await getQuizList({
      page: pager.page,
      page_size: pager.page_size,
      keyword: pager.keyword || undefined,
      scope: pager.scope || undefined,
      hospital_id: pager.hospital_id,
      department_id: pager.department_id,
      chat_type: pager.chat_type || undefined,
      deleted_only: recycleMode.value || undefined,
    })
    rows.value = data.items
    selectedRows.value = []
    pager.total = data.total
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || '获取案例库列表失败')
  } finally {
    loading.value = false
  }
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

const loadMetaOptions = async () => {
  try {
    const data = await getQuizMetaOptions({
      scope: pager.scope || undefined,
      hospital_id: pager.hospital_id,
      department_id: pager.department_id,
      chat_type: pager.chat_type || undefined,
    })
    categoryOptions.value = data.categories || []
    tagOptions.value = data.tags || []
  } catch {
    categoryOptions.value = []
    tagOptions.value = []
  }
}

const parseCsvValues = (text: string) =>
  text
    .replace(/，/g, ',')
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)

const selectedQuizIds = computed(() => selectedRows.value.map((row) => row.id))
const onSelectionChange = (val: QuizListItem[]) => {
  selectedRows.value = val
}

const ensureSelectedForBatch = () => {
  if (!selectedQuizIds.value.length) {
    ElMessage.warning('请先勾选要批量修改的案例')
    return false
  }
  return true
}

const batchSetCategory = async () => {
  if (!updatePerm.value.allowed) return ElMessage.warning(updatePerm.value.reason)
  if (!ensureSelectedForBatch()) return
  try {
    const { value } = await ElMessageBox.prompt('请输入分类（留空可清空）', '批量设置分类', {
      inputPlaceholder: '例如：耳鼻喉科',
      confirmButtonText: '确认',
      cancelButtonText: '取消',
    })
    const category = (value || '').trim()
    const result = await batchUpdateQuizMeta({
      quiz_ids: selectedQuizIds.value,
      set_category: category || undefined,
      clear_category: !category,
    })
    ElMessage.success(`批量修改完成：命中 ${result.matched}，更新 ${result.updated}`)
    await Promise.all([load(), loadMetaOptions()])
  } catch (error: any) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(error?.response?.data?.detail || error?.message || '批量设置分类失败')
  }
}

const batchAddTags = async () => {
  if (!updatePerm.value.allowed) return ElMessage.warning(updatePerm.value.reason)
  if (!ensureSelectedForBatch()) return
  try {
    const { value } = await ElMessageBox.prompt('请输入要追加的标签（逗号分隔）', '批量追加标签', {
      inputPlaceholder: '例如：耳道清洗,用药指导',
      confirmButtonText: '确认',
      cancelButtonText: '取消',
    })
    const tags = parseCsvValues(value || '')
    if (!tags.length) return ElMessage.warning('请输入至少一个标签')
    const result = await batchUpdateQuizMeta({
      quiz_ids: selectedQuizIds.value,
      add_tags: tags,
    })
    ElMessage.success(`批量追加完成：命中 ${result.matched}，更新 ${result.updated}`)
    await Promise.all([load(), loadMetaOptions()])
  } catch (error: any) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(error?.response?.data?.detail || error?.message || '批量追加标签失败')
  }
}

const batchRemoveTags = async () => {
  if (!updatePerm.value.allowed) return ElMessage.warning(updatePerm.value.reason)
  if (!ensureSelectedForBatch()) return
  try {
    const { value } = await ElMessageBox.prompt('请输入要移除的标签（逗号分隔）', '批量移除标签', {
      inputPlaceholder: '例如：耳道清洗,用药指导',
      confirmButtonText: '确认',
      cancelButtonText: '取消',
    })
    const tags = parseCsvValues(value || '')
    if (!tags.length) return ElMessage.warning('请输入至少一个标签')
    const result = await batchUpdateQuizMeta({
      quiz_ids: selectedQuizIds.value,
      remove_tags: tags,
    })
    ElMessage.success(`批量移除完成：命中 ${result.matched}，更新 ${result.updated}`)
    await Promise.all([load(), loadMetaOptions()])
  } catch (error: any) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(error?.response?.data?.detail || error?.message || '批量移除标签失败')
  }
}

const batchClearMeta = async () => {
  if (!updatePerm.value.allowed) return ElMessage.warning(updatePerm.value.reason)
  if (!ensureSelectedForBatch()) return
  try {
    await confirmDangerousAction(
      `确认清空已勾选 ${selectedQuizIds.value.length} 条案例的分类和标签吗？`,
      '批量清空分类标签',
    )
    const result = await batchUpdateQuizMeta({
      quiz_ids: selectedQuizIds.value,
      clear_category: true,
      clear_tags: true,
    })
    ElMessage.success(`批量清空完成：命中 ${result.matched}，更新 ${result.updated}`)
    await Promise.all([load(), loadMetaOptions()])
  } catch (error: any) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(error?.response?.data?.detail || error?.message || '批量清空失败')
  }
}

const onSearch = () => {
  triggerFilterSearch.cancel()
  pager.page = 1
  loadMetaOptions()
  load()
}

const triggerFilterSearch = createDebouncedFn(() => {
  pager.page = 1
  loadMetaOptions()
  load()
}, 300)

const onHospitalFilterChange = () => {
  pager.department_id = undefined
}

const toggleRecycleMode = () => {
  recycleMode.value = !recycleMode.value
  pager.page = 1
  load()
}

const openDetailDrawer = async (quizId: number) => {
  selectedQuizId.value = quizId
  detailLoading.value = true
  try {
    detail.value = await getQuizDetail(quizId)
    detailPager.page = 1
    detailDrawerVisible.value = true
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || '获取案例详情失败')
  } finally {
    detailLoading.value = false
  }
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

const openEditDialog = async (quizId: number) => {
  if (!updatePerm.value.allowed) {
    ElMessage.warning(updatePerm.value.reason)
    return
  }
  editLoading.value = true
  try {
    let data: QuizDetailData
    if (detail.value && detail.value.id === quizId) {
      data = detail.value
    } else {
      data = await getQuizDetail(quizId)
    }
    fillEditForm(data)
    editDialogVisible.value = true
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || '获取案例信息失败')
  } finally {
    editLoading.value = false
  }
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
  if (!editForm.id) return
  if (!editFormRef.value) return
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
    if (selectedQuizId.value === editForm.id && detailDrawerVisible.value) {
      detail.value = await getQuizDetail(editForm.id)
      detailPager.page = 1
    }
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || '更新失败')
  } finally {
    editSaving.value = false
  }
}

const viewPrev = async () => {
  if (!canViewPrev.value || detailLoading.value) return
  const prev = rows.value[currentQuizIndex.value - 1]
  if (!prev) return
  await openDetailDrawer(prev.id)
}

const viewNext = async () => {
  if (!canViewNext.value || detailLoading.value) return
  const next = rows.value[currentQuizIndex.value + 1]
  if (!next) return
  await openDetailDrawer(next.id)
}

const removeQuiz = async (row: QuizListItem) => {
  if (!softDeletePerm.value.allowed) {
    ElMessage.warning(softDeletePerm.value.reason)
    return
  }
  try {
    await confirmDangerousAction(
      `确认删除案例「${row.title}」吗？删除后将从案例库列表隐藏。`,
      '删除案例确认',
    )
    await softDeleteQuiz(row.id)
    ElMessage.success('删除成功（已软删除）')
    if (selectedQuizId.value === row.id) {
      detailDrawerVisible.value = false
      detail.value = null
      selectedQuizId.value = null
    }
    await load()
  } catch (error: any) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(error?.response?.data?.detail || '删除失败')
  }
}

const restoreDeletedQuiz = async (row: QuizListItem) => {
  if (!restorePerm.value.allowed) {
    ElMessage.warning(restorePerm.value.reason)
    return
  }
  try {
    await confirmDangerousAction(
      `确认恢复案例「${row.title}」吗？恢复后将重新在案例库列表显示。`,
      '恢复案例确认',
    )
    await restoreQuiz(row.id)
    ElMessage.success('恢复成功')
    await load()
  } catch (error: any) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(error?.response?.data?.detail || '恢复失败')
  }
}

const permanentlyDeleteQuiz = async (row: QuizListItem) => {
  if (!hardDeletePerm.value.allowed) {
    ElMessage.warning(hardDeletePerm.value.reason)
    return
  }
  try {
    await confirmDangerousAction(
      `确认彻底删除案例「${row.title}」吗？此操作不可恢复。`,
      '彻底删除确认',
    )
    await hardDeleteQuiz(row.id)
    ElMessage.success('彻底删除成功')
    await load()
  } catch (error: any) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(error?.response?.data?.detail || '彻底删除失败')
  }
}

const updateViewport = () => {
  isMobile.value = window.innerWidth < 992
}

onMounted(() => {
  const q = typeof route.query.q === 'string' ? route.query.q.trim() : ''
  if (q) pager.keyword = q
  isSuperAdmin.value = userStore.user?.role === 'super_admin'
  if (!isSuperAdmin.value) {
    pager.hospital_id = userStore.user?.hospital_id || undefined
    pager.department_id = userStore.user?.department_id || undefined
  }
  updateViewport()
  window.addEventListener('resize', updateViewport)
  Promise.all([loadHospitals(), loadDepartments()]).then(async () => {
    await loadMetaOptions()
    await load()
  })
})

onBeforeUnmount(() => {
  triggerFilterSearch.cancel()
  window.removeEventListener('resize', updateViewport)
})

watch(
  [
    () => pager.keyword,
    () => pager.chat_type,
    () => pager.scope,
    () => pager.hospital_id,
    () => pager.department_id,
  ],
  () => {
    triggerFilterSearch()
  },
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
        <strong class="admin-card-title">案例库列表</strong>
        <div class="admin-card-header-actions admin-toolbar-actions quiz-toolbar-desktop">
          <template v-if="!isMobile">
            <div class="quiz-toolbar-filters">
              <el-input v-model="pager.keyword" class="admin-control-w-2xl" placeholder="按标题搜索" clearable />
              <el-select v-model="pager.chat_type" class="admin-control-w-sm" clearable placeholder="聊天类型">
                <el-option label="主动聊天" value="active" />
                <el-option label="被动聊天" value="passive" />
              </el-select>
              <el-select v-model="pager.scope" class="admin-control-w-sm" clearable placeholder="案例库范围">
                <el-option label="通用案例库" value="common" />
                <el-option label="医院专属" value="hospital" />
                <el-option label="科室专属" value="department" />
              </el-select>
              <el-select
                v-model="pager.hospital_id"
                :disabled="!isSuperAdmin"
                clearable
                placeholder="所属医院"
                class="admin-control-w-md"
                @change="onHospitalFilterChange"
              >
                <el-option v-for="h in hospitals" :key="h.id" :label="h.name" :value="h.id" />
              </el-select>
              <el-select
                v-model="pager.department_id"
                :disabled="!isSuperAdmin"
                clearable
                placeholder="所属科室"
                class="admin-control-w-md"
              >
                <el-option
                  v-for="d in departmentOptionsByHospital(pager.hospital_id)"
                  :key="d.id"
                  :label="d.name"
                  :value="d.id"
                />
              </el-select>
              <el-button type="primary" @click="onSearch">查询</el-button>
              <el-button :disabled="!updatePerm.allowed || !selectedQuizIds.length" @click="batchSetCategory">
                批量设分类
              </el-button>
              <el-button :disabled="!updatePerm.allowed || !selectedQuizIds.length" @click="batchAddTags">批量加标签</el-button>
              <el-button :disabled="!updatePerm.allowed || !selectedQuizIds.length" @click="batchRemoveTags">
                批量删标签
              </el-button>
              <el-button :disabled="!updatePerm.allowed || !selectedQuizIds.length" @click="batchClearMeta">清空分类标签</el-button>
            </div>
          </template>
          <template v-else>
            <el-button @click="mobileFilterOpen = !mobileFilterOpen">
              {{ mobileFilterOpen ? '收起筛选' : '展开筛选' }}
            </el-button>
          </template>
          <div class="quiz-toolbar-actions">
            <el-button :type="recycleMode ? 'warning' : 'default'" @click="toggleRecycleMode">
              {{ recycleMode ? '返回案例库' : '回收站' }}
            </el-button>
            <el-button @click="router.push('/admin/quizzes/taxonomy')">分类标签中心</el-button>
            <el-button @click="router.push('/admin/quizzes/import')">去导入</el-button>
          </div>
        </div>
      </div>
    </template>

    <el-card v-if="isMobile && mobileFilterOpen" shadow="never" class="mobile-filter-card">
      <el-input v-model="pager.keyword" placeholder="按标题搜索" clearable />
      <el-select v-model="pager.chat_type" clearable placeholder="聊天类型" style="margin-top: 8px">
        <el-option label="主动聊天" value="active" />
        <el-option label="被动聊天" value="passive" />
      </el-select>
      <el-select v-model="pager.scope" clearable placeholder="案例库范围" style="margin-top: 8px">
        <el-option label="通用案例库" value="common" />
        <el-option label="医院专属" value="hospital" />
        <el-option label="科室专属" value="department" />
      </el-select>
      <el-select
        v-model="pager.hospital_id"
        :disabled="!isSuperAdmin"
        clearable
        placeholder="所属医院"
        style="margin-top: 8px"
        @change="onHospitalFilterChange"
      >
        <el-option v-for="h in hospitals" :key="h.id" :label="h.name" :value="h.id" />
      </el-select>
      <el-select
        v-model="pager.department_id"
        :disabled="!isSuperAdmin"
        clearable
        placeholder="所属科室"
        style="margin-top: 8px"
      >
        <el-option
          v-for="d in departmentOptionsByHospital(pager.hospital_id)"
          :key="d.id"
          :label="d.name"
          :value="d.id"
        />
      </el-select>
      <div class="mobile-filter-actions">
        <el-button type="primary" size="small" @click="onSearch">查询</el-button>
      </div>
    </el-card>

    <AdminTableSkeleton v-if="!isMobile && loading" :is-mobile="false" :rows="8" />
    <el-table
      v-else-if="!isMobile"
      class="admin-list-table"
      :data="rows"
      border
      stripe
      @selection-change="onSelectionChange"
    >
      <el-table-column type="selection" width="50" />
      <el-table-column prop="id" label="编号" width="70" />
      <el-table-column prop="title" label="标题" min-width="220" />
      <el-table-column label="范围" width="120">
        <template #default="{ row }">
          <el-tag size="small" :type="row.scope === 'common' ? 'success' : 'info'">
            {{ row.scope === 'common' ? '通用' : row.scope === 'department' ? '科室专属' : '医院专属' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="hospital_name" label="所属医院" width="150" />
      <el-table-column prop="department_name" label="所属科室" width="150" />
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
      <el-table-column prop="patient_name" label="患者" width="120" />
      <el-table-column prop="counselor_name" label="咨询师" width="120" />
      <el-table-column label="操作" width="220">
        <template #default="{ row }">
          <template v-if="row.is_deleted">
            <el-tooltip :disabled="restorePerm.allowed" :content="restorePerm.reason" placement="top">
              <span>
                <el-button link type="success" :disabled="!restorePerm.allowed" @click="restoreDeletedQuiz(row)">恢复</el-button>
              </span>
            </el-tooltip>
            <el-tooltip :disabled="hardDeletePerm.allowed" :content="hardDeletePerm.reason" placement="top">
              <span>
                <el-button link type="danger" :disabled="!hardDeletePerm.allowed" @click="permanentlyDeleteQuiz(row)">
                  彻底删除
                </el-button>
              </span>
            </el-tooltip>
          </template>
          <template v-else>
            <el-button link type="primary" @click="openDetailDrawer(row.id)">详情</el-button>
            <el-tooltip :disabled="updatePerm.allowed" :content="updatePerm.reason" placement="top">
              <span>
                <el-button link type="primary" :disabled="!updatePerm.allowed" @click="openEditDialog(row.id)">
                  编辑
                </el-button>
              </span>
            </el-tooltip>
            <el-tooltip :disabled="softDeletePerm.allowed" :content="softDeletePerm.reason" placement="top">
              <span>
                <el-button link type="danger" :disabled="!softDeletePerm.allowed" @click="removeQuiz(row)">删除</el-button>
              </span>
            </el-tooltip>
          </template>
        </template>
      </el-table-column>
    </el-table>

    <div v-else class="mobile-list">
      <AdminTableSkeleton v-if="loading" :is-mobile="true" :mobile-rows="4" />
      <el-empty v-else-if="!rows.length" class="admin-empty" description="暂无案例" />
      <template v-else>
        <el-card v-for="row in rows" :key="row.id" class="mobile-item" shadow="never">
          <div class="mobile-title-row">
            <strong>{{ row.title }}</strong>
            <el-tag size="small" :type="row.chat_type === 'active' ? 'success' : 'warning'">
              {{ row.chat_type === 'active' ? '主动聊天' : '被动聊天' }}
            </el-tag>
          </div>
          <div class="meta">
            范围：{{ row.scope === 'common' ? '通用案例库' : row.scope === 'department' ? '科室专属' : '医院专属' }} |
            医院：{{ row.hospital_name || '-' }} | 科室：{{ row.department_name || '-' }}
          </div>
          <div class="meta">分类：{{ row.category || '-' }}</div>
          <div class="meta">标签：{{ row.tags || '-' }}</div>
          <div class="meta">难度：{{ row.difficulty }} | 消息数：{{ row.message_count }}</div>
          <div class="meta">患者：{{ row.patient_name || '-' }} | 咨询师：{{ row.counselor_name || '-' }}</div>
          <div class="actions">
            <template v-if="row.is_deleted">
              <el-tooltip :disabled="restorePerm.allowed" :content="restorePerm.reason" placement="top">
                <span>
                  <el-button link type="success" :disabled="!restorePerm.allowed" @click="restoreDeletedQuiz(row)">恢复</el-button>
                </span>
              </el-tooltip>
              <el-tooltip :disabled="hardDeletePerm.allowed" :content="hardDeletePerm.reason" placement="top">
                <span>
                  <el-button link type="danger" :disabled="!hardDeletePerm.allowed" @click="permanentlyDeleteQuiz(row)">
                    彻底删除
                  </el-button>
                </span>
              </el-tooltip>
            </template>
            <template v-else>
              <el-button link type="primary" @click="openDetailDrawer(row.id)">查看详情</el-button>
              <el-tooltip :disabled="updatePerm.allowed" :content="updatePerm.reason" placement="top">
                <span>
                  <el-button link type="primary" :disabled="!updatePerm.allowed" @click="openEditDialog(row.id)">编辑</el-button>
                </span>
              </el-tooltip>
              <el-tooltip :disabled="softDeletePerm.allowed" :content="softDeletePerm.reason" placement="top">
                <span>
                  <el-button link type="danger" :disabled="!softDeletePerm.allowed" @click="removeQuiz(row)">删除</el-button>
                </span>
              </el-tooltip>
            </template>
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

    <el-drawer
      v-model="detailDrawerVisible"
      class="admin-smooth-drawer quiz-detail-drawer"
      :size="getDrawerSize(isMobile, DRAWER_DESKTOP_SIZE.detail)"
      direction="rtl"
      :with-header="false"
    >
      <div v-loading="detailLoading" class="drawer-body admin-drawer-body">
        <template v-if="detail">
          <div class="drawer-title admin-drawer-header">
            <strong>案例详情 - {{ detail.title }}<span v-if="positionText">（{{ positionText }}）</span></strong>
            <div class="drawer-actions admin-drawer-actions">
              <el-button :disabled="!canViewPrev || detailLoading" @click="viewPrev">上一条</el-button>
              <el-button :disabled="!canViewNext || detailLoading" @click="viewNext">下一条</el-button>
              <el-tooltip :disabled="updatePerm.allowed" :content="updatePerm.reason" placement="top">
                <span>
                  <el-button :disabled="!updatePerm.allowed" @click="openEditDialog(detail.id)">编辑案例信息</el-button>
                </span>
              </el-tooltip>
              <el-button link type="primary" @click="detailDrawerVisible = false">{{ UI_TEXT.close }}</el-button>
            </div>
          </div>

          <el-descriptions :column="isMobile ? 1 : 2" border>
            <el-descriptions-item label="编号">{{ detail.id }}</el-descriptions-item>
            <el-descriptions-item label="范围">{{ scopeText(detail.scope) }}</el-descriptions-item>
            <el-descriptions-item label="所属医院">{{ detail.hospital_name || '-' }}</el-descriptions-item>
            <el-descriptions-item label="所属科室">{{ detail.department_name || '-' }}</el-descriptions-item>
            <el-descriptions-item label="聊天类型">
              {{ detail.chat_type === 'active' ? '主动聊天' : '被动聊天' }}
            </el-descriptions-item>
            <el-descriptions-item label="分类">{{ detail.category || '-' }}</el-descriptions-item>
            <el-descriptions-item label="难度">{{ detail.difficulty }}</el-descriptions-item>
            <el-descriptions-item label="消息数">{{ detail.message_count }}</el-descriptions-item>
          </el-descriptions>

          <el-card shadow="never" style="margin-top: 12px">
            <template #header>
              <div class="admin-card-header">
                <strong class="admin-card-title">版本记录</strong>
              </div>
            </template>
            <el-empty v-if="!detail.versions?.length" class="admin-empty" description="暂无版本记录" />
            <el-table v-else-if="!isMobile" :data="detail.versions" border stripe>
              <el-table-column prop="version_no" label="版本号" width="100" />
              <el-table-column prop="message_count" label="消息数" width="100" />
              <el-table-column prop="source_file" label="来源文件" min-width="220" />
              <el-table-column prop="created_at" label="创建时间" width="180" />
            </el-table>
            <div v-else class="mobile-list">
              <el-card v-for="v in detail.versions" :key="v.id" class="mobile-item" shadow="never">
                <div class="mobile-title-row">
                  <strong>V{{ v.version_no }}</strong>
                  <el-tag size="small" type="info">{{ v.message_count }} 条</el-tag>
                </div>
                <div class="meta">文件：{{ v.source_file || '-' }}</div>
                <div class="meta">时间：{{ v.created_at }}</div>
              </el-card>
            </div>
          </el-card>

          <el-table v-if="!isMobile" :data="detailMessages" border stripe style="margin-top: 12px">
            <el-table-column prop="sequence" label="#" width="60" />
            <el-table-column label="角色" width="100">
              <template #default="{ row }">{{ row.role === 'patient' ? '患者' : '咨询师' }}</template>
            </el-table-column>
            <el-table-column prop="sender_name" label="发送者" width="140" />
            <el-table-column prop="content_type" label="类型" width="90" />
            <el-table-column label="内容" min-width="280">
              <template #default="{ row }">
                {{ formatMessageContent(row) }}
              </template>
            </el-table-column>
            <el-table-column prop="original_time" label="时间" width="180" />
          </el-table>
          <div v-else class="mobile-list" style="margin-top: 12px">
            <el-card v-for="msg in detailMessages" :key="msg.sequence" class="mobile-item" shadow="never">
              <div class="mobile-title-row">
                <strong>#{{ msg.sequence }}</strong>
                <el-tag size="small" :type="msg.role === 'patient' ? 'info' : 'success'">
                  {{ msg.role === 'patient' ? '患者' : '咨询师' }}
                </el-tag>
              </div>
              <div class="meta">发送者：{{ msg.sender_name || '-' }}</div>
              <div class="meta">类型：{{ msg.content_type }}</div>
              <div class="meta">内容：{{ formatMessageContent(msg) }}</div>
              <div class="meta">时间：{{ msg.original_time || '-' }}</div>
            </el-card>
          </div>

          <div class="admin-pager">
            <el-pagination
              v-model:current-page="detailPager.page"
              v-model:page-size="detailPager.page_size"
              :page-sizes="[10, 20, 50, 100]"
              :layout="isMobile ? 'prev, pager, next' : 'total, sizes, prev, pager, next, jumper'"
              :small="isMobile"
              :total="detail.messages.length"
              @size-change="detailPager.page = 1"
            />
          </div>
        </template>
      </div>
    </el-drawer>

    <el-dialog
      v-model="editDialogVisible"
      title="编辑案例"
      :width="isMobile ? '96%' : '720px'"
      destroy-on-close
    >
      <div v-loading="editLoading">
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
            <el-select
              v-model="editForm.category"
              clearable
              filterable
              allow-create
              default-first-option
              class="w-full"
              placeholder="可选择或新建分类"
            >
              <el-option v-for="item in categoryOptions" :key="item.name" :label="`${item.name} (${item.count})`" :value="item.name" />
            </el-select>
          </el-form-item>
          <el-form-item label="难度" prop="difficulty">
            <el-input-number v-model="editForm.difficulty" :min="1" :max="5" />
          </el-form-item>
          <el-form-item label="标签">
            <el-select
              v-model="editForm.tags"
              filterable
              allow-create
              default-first-option
              clearable
              class="w-full"
              placeholder="可选择标签，也可直接输入多个标签（逗号分隔）"
            >
              <el-option v-for="item in tagOptions" :key="item.name" :label="item.name" :value="item.name" />
            </el-select>
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
      </div>
      <template #footer>
        <el-button @click="editDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="editSaving" @click="submitEdit">保存修改</el-button>
      </template>
    </el-dialog>
  </el-card>
</template>

<style scoped>
.mobile-filter-card {
  margin-bottom: 10px;
}

.mobile-filter-actions {
  margin-top: 8px;
  display: flex;
  justify-content: flex-end;
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
  margin-top: 8px;
  display: flex;
  justify-content: flex-end;
}

.quiz-toolbar-desktop {
  align-items: center;
  justify-content: space-between;
  flex-wrap: nowrap;
}

.quiz-toolbar-filters {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: nowrap;
  min-width: 0;
  overflow-x: auto;
  padding-bottom: 2px;
}

.quiz-toolbar-actions {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.w-full {
  width: 100%;
}

@media (max-width: 768px) {
  .quiz-toolbar-desktop {
    flex-wrap: wrap;
    align-items: stretch;
  }

  .quiz-toolbar-actions {
    width: 100%;
    justify-content: flex-start;
  }
}
</style>
