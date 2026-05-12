<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { UploadFilled, WarningFilled } from '@element-plus/icons-vue'
import {
  batchReparseQuizzes,
  getQuizMetaOptions,
  confirmQuizImport,
  confirmQuizNewVersion,
  estimateBatchReparseQuizzes,
  getQuizList,
  uploadQuizHtml,
  type BatchReparseEstimateResult,
  type BatchReparseResult,
  type UploadPreviewData,
} from '../../api/quiz'
import { getHospitals, type HospitalItem } from '../../api/hospital'
import { getDepartments, type DepartmentItem } from '../../api/department'
import {
  createImportTask,
  exportImportTaskFailedCsv,
  finishImportTask,
  getImportTaskDetail,
  getImportTaskList,
  type ImportTaskItem,
} from '../../api/importTasks'
import { useUserStore } from '../../stores/user'
import { useNotificationStore } from '../../stores/notification'
import { confirmDangerousAction, createDebouncedFn } from '../../composables/useUiStandards'
import { evaluatePermissionPoint } from '../../utils/permissionPoints'

const userStore = useUserStore()
const notificationStore = useNotificationStore()
const isSuperAdmin = ref(false)
const isMobile = ref(false)
const importWorkbenchVisible = ref(false)
const activeMainTab = ref<'workbench' | 'records'>('workbench')

const hospitals = ref<HospitalItem[]>([])
const departments = ref<DepartmentItem[]>([])
const quizOptions = ref<Array<{ id: number; title: string }>>([])
const categoryOptions = ref<Array<{ name: string; count: number }>>([])
const tagOptions = ref<Array<{ name: string; count: number }>>([])

const form = reactive({
  scope: 'hospital' as 'common' | 'hospital' | 'department',
  hospital_id: undefined as number | undefined,
  department_id: undefined as number | undefined,
  chat_type: 'passive' as 'active' | 'passive',
  category: '',
  difficulty: 2,
  tags: '',
  description: '',
})

const importTagsModel = computed<string[]>({
  get: () =>
    (form.tags || '')
      .replace(/，/g, ',')
      .split(',')
      .map((item) => item.trim())
      .filter(Boolean),
  set: (values) => {
    form.tags = values.map((item) => item.trim()).filter(Boolean).join(',')
  },
})

interface BatchQueueItem {
  uid: string
  file_name: string
  preview_id?: string
  title: string
  chat_type: 'active' | 'passive'
  patient_name?: string | null
  counselor_name?: string | null
  message_count: number
  preview_messages: UploadPreviewData['messages']
  status: 'ready' | 'importing' | 'success' | 'duplicate' | 'error'
  result_text?: string
  duplicate_action?: 'skip' | 'update'
  update_quiz_id?: number
  duplicate_quiz_id?: number
  duplicate_quiz_title?: string
}

interface LastImportSummary {
  executed: number
  success: number
  duplicate: number
  failed: number
  updated: number
  finished_at: string
}

interface ImportTaskFailedItem {
  file_name: string
  title: string
  chat_type: string
  message_count: number
  status: string
  result_text: string
}

const batchQueue = ref<BatchQueueItem[]>([])
const batchUploading = ref(false)
const batchSubmitting = ref(false)
const batchRetryPendingOnly = ref(true)
const batchParseToastTimer = ref<number | null>(null)
const batchParseSummary = reactive({
  added: 0,
  failed: 0,
  duplicated: 0,
})
const batchSummary = computed(() => {
  const total = batchQueue.value.length
  const success = batchQueue.value.filter((item) => item.status === 'success').length
  const duplicate = batchQueue.value.filter((item) => item.status === 'duplicate').length
  const failed = batchQueue.value.filter((item) => item.status === 'error').length
  const pending = batchQueue.value.filter((item) => item.status === 'ready' || item.status === 'importing').length
  return { total, success, duplicate, failed, pending }
})

const queuePreviewVisible = ref(false)
const queuePreviewItem = ref<BatchQueueItem | null>(null)
const queuePreviewFilter = ref<'all' | 'image_placeholder' | 'audio_placeholder' | 'valid_link'>('all')
const queuePreviewPager = reactive({ page: 1, page_size: 20 })
const checklistConfirmVisible = ref(false)
const checklistConfirmAcknowledge = ref(false)
const checklistConfirmText = ref('')
const checklistRequireAcknowledge = ref(false)
let checklistConfirmResolver: ((ok: boolean) => void) | null = null

const reparseLoading = ref(false)
const reparseLimit = ref(500)
const reparseOnlyLegacyOrEmpty = ref(true)
const reparseEstimateLoading = ref(false)
const reparseEstimate = ref<BatchReparseEstimateResult | null>(null)
const reparseResult = ref<BatchReparseResult | null>(null)
const importWorkbenchDialogWidth = computed(() => (isMobile.value ? '100%' : 'min(1280px, 96vw)'))
const batchSubmitPerm = computed(() => evaluatePermissionPoint('import.batch.submit'))
const reparsePerm = computed(() => evaluatePermissionPoint('quiz.batch.reparse'))
const exportFailedPerm = computed(() => evaluatePermissionPoint('import.task.export_failed'))
const lastImportSummary = ref<LastImportSummary | null>(null)
const LAST_IMPORT_SUMMARY_STORAGE_KEY = 'admin-import-last-summary'
const importTaskLoading = ref(false)
const importTaskRows = ref<ImportTaskItem[]>([])
const importTaskPager = reactive({
  page: 1,
  page_size: 10,
  total: 0,
  scope: '' as '' | 'common' | 'hospital' | 'department',
  status: '' as '' | 'running' | 'completed' | 'partial_fail',
})
const importTaskDetailVisible = ref(false)
const importTaskDetailLoading = ref(false)
const importTaskDetail = ref<ImportTaskItem | null>(null)
const importTaskFailedItems = computed<ImportTaskFailedItem[]>(() => {
  const items = importTaskDetail.value?.detail?.failed_items
  if (!Array.isArray(items)) return []
  return items
    .filter((item) => typeof item === 'object' && item)
    .map((item: any) => ({
      file_name: String(item.file_name || ''),
      title: String(item.title || ''),
      chat_type: String(item.chat_type || ''),
      message_count: Number(item.message_count || 0),
      status: String(item.status || ''),
      result_text: String(item.result_text || ''),
    }))
})

const departmentOptionsByHospital = (hospitalId?: number) => {
  if (!hospitalId) return departments.value
  return departments.value.filter((d) => d.hospital_id === hospitalId)
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

const loadQuizOptions = async () => {
  try {
    const data = await getQuizList({
      page: 1,
      page_size: 500,
      scope: form.scope,
      hospital_id: form.scope !== 'common' ? form.hospital_id : undefined,
      department_id: form.scope === 'department' ? form.department_id : undefined,
    })
    quizOptions.value = data.items.map((i) => ({ id: i.id, title: i.title }))
  } catch {
    quizOptions.value = []
  }
}

const loadMetaOptions = async () => {
  try {
    const data = await getQuizMetaOptions({
      scope: form.scope,
      hospital_id: form.scope !== 'common' ? form.hospital_id : undefined,
      department_id: form.scope === 'department' ? form.department_id : undefined,
      chat_type: form.chat_type,
    })
    categoryOptions.value = data.categories || []
    tagOptions.value = data.tags || []
  } catch {
    categoryOptions.value = []
    tagOptions.value = []
  }
}

const triggerLoadQuizOptions = createDebouncedFn(() => {
  loadQuizOptions()
}, 260)
const triggerLoadMetaOptions = createDebouncedFn(() => {
  loadMetaOptions()
}, 260)

const validateBatchGlobalForm = () => {
  if (form.scope === 'hospital' && !form.hospital_id) return '请先选择所属医院'
  if (form.scope === 'department' && !form.hospital_id) return '请先选择所属医院'
  if (form.scope === 'department' && !form.department_id) return '请先选择所属科室'
  if (form.scope === 'common' && !isSuperAdmin.value) return '仅超级管理员可导入通用案例库'
  return ''
}

const isUploadReady = computed(() => !validateBatchGlobalForm())
const uploadBlockReason = computed(() => validateBatchGlobalForm())
const uploadOverlayTitle = computed(() => uploadBlockReason.value || '请先完成上方导入参数设置')
const uploadOverlayHint = computed(() => {
  if (form.scope === 'department') return '完成“所属医院 + 所属科室”后可拖拽上传'
  if (form.scope === 'hospital') return '完成“所属医院”后可拖拽上传'
  if (form.scope === 'common') return '仅超级管理员可导入通用案例库'
  return '请先完成导入参数设置'
})

const selectedHospitalName = computed(() => {
  if (!form.hospital_id) return ''
  return hospitals.value.find((h) => h.id === form.hospital_id)?.name || ''
})

const selectedDepartmentName = computed(() => {
  if (!form.department_id) return ''
  return departments.value.find((d) => d.id === form.department_id)?.name || ''
})

const importTargetText = computed(() => {
  if (form.scope === 'common') return '通用案例库（全院可见）'
  if (form.scope === 'department') {
    return `科室专属案例库${selectedHospitalName.value ? `（${selectedHospitalName.value}` : ''}${
      selectedDepartmentName.value ? ` / ${selectedDepartmentName.value}` : ''
    }${selectedHospitalName.value ? '）' : ''}`
  }
  return `医院专属案例库${selectedHospitalName.value ? `（${selectedHospitalName.value}）` : ''}`
})

const guessChatTypeByFilename = (fileName: string): 'active' | 'passive' => {
  const normalized = fileName.toLowerCase()
  if (normalized.includes('被动')) return 'passive'
  if (normalized.includes('主动')) return 'active'
  return form.chat_type || 'passive'
}

const parseDuplicateTarget = (detailText: string) => {
  const match = detailText.match(/编号(\d+)《([^》]+)》/)
  if (!match) return null
  return { id: Number(match[1]), title: match[2] || '' }
}

const getUpdateTargetOptions = (item: BatchQueueItem) => {
  if (!item.duplicate_quiz_id) return quizOptions.value
  if (quizOptions.value.some((q) => q.id === item.duplicate_quiz_id)) return quizOptions.value
  return [
    {
      id: item.duplicate_quiz_id,
      title: item.duplicate_quiz_title || `重复命中案例（${item.duplicate_quiz_id}）`,
    },
    ...quizOptions.value,
  ]
}

const onDuplicateActionSelectChange = (item: BatchQueueItem, value: unknown) => {
  if (value !== 'skip' && value !== 'update') return
  item.duplicate_action = value
  if (value === 'update' && item.duplicate_quiz_id) item.update_quiz_id = item.duplicate_quiz_id
}

const scheduleBatchParseToast = () => {
  if (batchParseToastTimer.value) window.clearTimeout(batchParseToastTimer.value)
  batchParseToastTimer.value = window.setTimeout(() => {
    const { added, failed, duplicated } = batchParseSummary
    const parts: string[] = []
    if (added > 0) parts.push(`加入${added}个`)
    if (failed > 0) parts.push(`失败${failed}个`)
    if (duplicated > 0) parts.push(`已在队列${duplicated}个`)
    if (parts.length) {
      ElMessage({
        type: failed > 0 ? 'warning' : 'success',
        message: `本次批量解析：${parts.join('，')}`,
      })
    }
    batchParseSummary.added = 0
    batchParseSummary.failed = 0
    batchParseSummary.duplicated = 0
    batchParseToastTimer.value = null
  }, 450)
}

const appendQueueByFile = async (file: File) => {
  const duplicated = batchQueue.value.some((item) => item.file_name === file.name)
  if (duplicated) {
    batchParseSummary.duplicated += 1
    scheduleBatchParseToast()
    return
  }
  try {
    const data = await uploadQuizHtml(file)
    batchQueue.value.push({
      uid: `${Date.now()}_${Math.random()}`,
      file_name: file.name,
      preview_id: data.preview_id,
      title: `咨询案例-${data.patient_name || file.name.replace(/\\.html?$/i, '')}`,
      chat_type: guessChatTypeByFilename(file.name),
      patient_name: data.patient_name,
      counselor_name: data.counselor_name,
      message_count: data.message_count,
      preview_messages: data.messages || [],
      status: 'ready',
      result_text: '',
    })
    batchParseSummary.added += 1
    scheduleBatchParseToast()
  } catch (error: any) {
    const detail = error?.response?.data?.detail
    const detailText = typeof detail === 'string' ? detail : `批量解析失败：${file.name}`
    batchQueue.value.push({
      uid: `${Date.now()}_${Math.random()}`,
      file_name: file.name,
      title: file.name.replace(/\.html?$/i, ''),
      chat_type: guessChatTypeByFilename(file.name),
      patient_name: null,
      counselor_name: null,
      message_count: 0,
      preview_messages: [],
      status: 'error',
      result_text: detailText,
    })
    batchParseSummary.failed += 1
    scheduleBatchParseToast()
  }
}

const onFileSelect = async (uploadFile: any) => {
  const file = uploadFile?.raw as File | undefined
  if (!file) return
  if (!isUploadReady.value) {
    ElMessage.warning(uploadBlockReason.value || '请先完成参数设置')
    return
  }
  batchUploading.value = true
  try {
    await appendQueueByFile(file)
  } finally {
    batchUploading.value = false
  }
}

const resetBatchQueue = async () => {
  if (!batchQueue.value.length) return
  try {
    await confirmDangerousAction(`确认清空批量队列吗？当前共 ${batchQueue.value.length} 条待处理记录。`, '清空队列确认')
    batchQueue.value = []
    ElMessage.success('已清空批量队列')
  } catch (error: any) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(error?.message || '清空队列失败')
  }
}

const removeBatchItem = (uid: string) => {
  batchQueue.value = batchQueue.value.filter((item) => item.uid !== uid)
}

const applyBatchChatType = (nextType: 'active' | 'passive') => {
  let changed = 0
  batchQueue.value.forEach((item) => {
    if (item.status === 'importing') return
    if (item.chat_type !== nextType) {
      item.chat_type = nextType
      changed += 1
    }
  })
  if (changed > 0) {
    ElMessage.success(`已批量设置 ${changed} 条为${nextType === 'active' ? '主动聊天' : '被动聊天'}`)
  } else {
    ElMessage.info('当前队列无需批量修改')
  }
}

const getBatchImportCandidates = () => {
  return batchQueue.value.filter((item) => {
    if (item.status === 'success' || item.status === 'importing') return false
    if (batchRetryPendingOnly.value) return item.status === 'ready'
    if (item.status === 'duplicate') return item.duplicate_action === 'update' && Boolean(item.update_quiz_id)
    return item.status === 'ready' || item.status === 'error'
  })
}

const getChatTypeSkewWarning = (total: number, activeCount: number, passiveCount: number) => {
  if (total <= 0) return ''
  const maxCount = Math.max(activeCount, passiveCount)
  const majorType = activeCount >= passiveCount ? '主动聊天' : '被动聊天'
  const ratio = (maxCount / total) * 100
  if (ratio < 95) return ''
  const rounded = Math.round(ratio * 10) / 10
  return `🟡 黄色提醒：当前聊天类型分布异常集中，${majorType}占比约 ${rounded}%（${maxCount}/${total}）。请确认是否存在批量误设。`
}

const openChecklistConfirm = (message: string, requireAcknowledge: boolean) => {
  checklistConfirmText.value = message
  checklistRequireAcknowledge.value = requireAcknowledge
  checklistConfirmAcknowledge.value = false
  checklistConfirmVisible.value = true
  return new Promise<boolean>((resolve) => {
    checklistConfirmResolver = resolve
  })
}

const closeChecklistConfirm = (ok: boolean) => {
  checklistConfirmVisible.value = false
  if (checklistConfirmResolver) {
    checklistConfirmResolver(ok)
    checklistConfirmResolver = null
  }
}

const submitBatchImport = async () => {
  if (!batchSubmitPerm.value.allowed) {
    ElMessage.warning(batchSubmitPerm.value.reason)
    return
  }
  if (!batchQueue.value.length) {
    ElMessage.warning('请先上传文件')
    return
  }
  const candidates = getBatchImportCandidates()
  if (!candidates.length) {
    ElMessage.warning(batchRetryPendingOnly.value ? '当前没有待导入项可执行' : '当前没有可重试的导入项')
    return
  }
  const formErr = validateBatchGlobalForm()
  if (formErr) {
    ElMessage.warning(formErr)
    return
  }
  const missingChatType = batchQueue.value.find((item) => !item.chat_type)
  if (missingChatType) {
    ElMessage.warning(`请确认聊天类型：${missingChatType.file_name}`)
    return
  }
  const activeCount = candidates.filter((item) => item.chat_type === 'active').length
  const passiveCount = candidates.length - activeCount
  const skewWarning = getChatTypeSkewWarning(candidates.length, activeCount, passiveCount)
  const checklistText =
    `请在导入前确认：\n` +
    `1. 导入范围：${form.scope === 'department' ? '科室专属' : form.scope === 'hospital' ? '医院专属' : '通用案例库'}\n` +
    `2. 所属医院：${selectedHospitalName.value || '-'}\n` +
    `3. 所属科室：${selectedDepartmentName.value || '-'}\n` +
    `4. 本次执行：${candidates.length} 条（主动 ${activeCount} / 被动 ${passiveCount}）\n` +
    `5. 导入目标：${importTargetText.value}` +
    (skewWarning ? `\n\n${skewWarning}` : '')

  const ok = await openChecklistConfirm(checklistText, Boolean(skewWarning))
  if (!ok) {
    return
  }

  batchSubmitting.value = true
  let successCount = 0
  let duplicateCount = 0
  let failCount = 0
  let updateCount = 0
  let importTaskId = 0
  const failedItems: ImportTaskFailedItem[] = []

  try {
    const task = await createImportTask({
      scope: form.scope,
      hospital_id: form.scope !== 'common' ? form.hospital_id : undefined,
      department_id: form.scope === 'department' ? form.department_id : undefined,
      total: candidates.length,
      detail: {
        import_target_text: importTargetText.value,
        selected_hospital_name: selectedHospitalName.value || '',
        selected_department_name: selectedDepartmentName.value || '',
      },
    })
    importTaskId = task.id
  } catch (error: any) {
    ElMessage.warning(error?.response?.data?.detail || '导入任务记录创建失败，将继续执行导入')
  }

  for (const item of candidates) {
    const previousStatus = item.status
    if (!item.preview_id) {
      item.status = 'error'
      item.result_text = item.result_text || '预解析失败，缺少 preview_id，请移除后重新选择该文件'
      failCount += 1
      failedItems.push({
        file_name: item.file_name,
        title: item.title,
        chat_type: item.chat_type,
        message_count: item.message_count,
        status: 'error',
        result_text: item.result_text,
      })
      continue
    }
    item.status = 'importing'
    item.result_text = '导入中...'
    try {
      const payload = {
        preview_id: item.preview_id,
        title: item.title.trim() || `咨询案例-${item.patient_name || '未命名患者'}`,
        scope: form.scope,
        hospital_id: form.scope === 'hospital' ? form.hospital_id : undefined,
        department_id: form.scope === 'department' ? form.department_id : undefined,
        chat_type: item.chat_type,
        category: form.category || undefined,
        difficulty: form.difficulty,
        tags: form.tags || undefined,
        description: form.description || undefined,
      }
      const shouldUpdateVersion =
        previousStatus === 'duplicate' && item.duplicate_action === 'update' && Boolean(item.update_quiz_id)
      const res =
        shouldUpdateVersion && item.update_quiz_id
          ? await confirmQuizNewVersion(item.update_quiz_id, payload)
          : await confirmQuizImport(payload)
      item.status = 'success'
      if (shouldUpdateVersion) {
        item.result_text = `更新版本成功，案例ID：${res.quiz_id}`
        updateCount += 1
      } else {
        item.result_text = `导入成功，案例ID：${res.quiz_id}`
      }
      successCount += 1
    } catch (error: any) {
      const status = error?.response?.status
      const detail = error?.response?.data?.detail
      const detailText = typeof detail === 'string' ? detail : '导入失败'
      if (status === 409) {
        item.status = 'duplicate'
        item.result_text = detailText
        const duplicateTarget = parseDuplicateTarget(detailText)
        if (duplicateTarget) {
          item.duplicate_quiz_id = duplicateTarget.id
          item.duplicate_quiz_title = duplicateTarget.title
          if (!item.update_quiz_id) item.update_quiz_id = duplicateTarget.id
        }
        if (!item.duplicate_action) item.duplicate_action = 'skip'
        duplicateCount += 1
        failedItems.push({
          file_name: item.file_name,
          title: item.title,
          chat_type: item.chat_type,
          message_count: item.message_count,
          status: 'duplicate',
          result_text: detailText,
        })
      } else {
        item.status = 'error'
        item.result_text = detailText
        failCount += 1
        failedItems.push({
          file_name: item.file_name,
          title: item.title,
          chat_type: item.chat_type,
          message_count: item.message_count,
          status: 'error',
          result_text: detailText,
        })
      }
    }
  }

  if (importTaskId > 0) {
    try {
      await finishImportTask(importTaskId, {
        success: successCount,
        duplicate: duplicateCount,
        failed: failCount,
        updated: updateCount,
        detail: {
          failed_items: failedItems,
          queue_total: batchQueue.value.length,
          candidate_total: candidates.length,
        },
      })
    } catch {
      // ignore import task finish errors
    }
  }

  batchSubmitting.value = false
  persistLastImportSummary({
    executed: candidates.length,
    success: successCount,
    duplicate: duplicateCount,
    failed: failCount,
    updated: updateCount,
    finished_at: new Date().toISOString(),
  })
  notificationStore.push({
    type: failCount > 0 ? 'warning' : 'success',
    module: 'import',
    title: '批量导入完成',
    message: `执行${candidates.length}，成功${successCount}，重复${duplicateCount}，失败${failCount}`,
    path: '/admin/quizzes/import',
  })
  ElMessage.success(
    `批量完成：执行${candidates.length}，成功${successCount}（其中更新${updateCount}），重复${duplicateCount}，失败${failCount}`,
  )
  if (activeMainTab.value === 'records') {
    loadImportTasks()
  }
}

const exportFailedBatchItems = () => {
  if (!exportFailedPerm.value.allowed) {
    ElMessage.warning(exportFailedPerm.value.reason)
    return
  }
  const issueItems = batchQueue.value.filter((item) => item.status === 'error' || item.status === 'duplicate')
  if (!issueItems.length) {
    ElMessage.warning('当前没有异常项可导出')
    return
  }
  const exportedAt = new Date().toLocaleString('zh-CN', { hour12: false })
  const operatorName = userStore.user?.real_name || userStore.user?.username || '未知操作人'
  const rows = [
    ['文件名', '聊天类型', '消息数', '失败原因', '建议动作', '导出时间', '当前操作人'],
    ...issueItems.map((item) => [
      item.file_name,
      item.chat_type === 'active' ? '主动聊天' : '被动聊天',
      String(item.message_count),
      (item.result_text || '未知错误').replace(/\r?\n/g, ' '),
      item.status === 'duplicate' ? '重复可改标题后重试，或确认后跳过' : '请检查HTML格式、归属参数与权限后重试',
      exportedAt,
      operatorName,
    ]),
  ]
  const csvContent = rows
    .map((line) =>
      line
        .map((cell) => `"${String(cell).replace(/"/g, '""')}"`)
        .join(','),
    )
    .join('\n')
  const blob = new Blob([`\ufeff${csvContent}`], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `批量导入失败清单_${new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')}.csv`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
  ElMessage.success(`已导出异常项清单（${issueItems.length}条）`)
}

const openQueuePreview = (item: BatchQueueItem) => {
  queuePreviewItem.value = item
  queuePreviewFilter.value = 'all'
  queuePreviewPager.page = 1
  queuePreviewVisible.value = true
}

const isLikelyMediaLink = (value?: string | null) => {
  const text = (value || '').trim().toLowerCase()
  if (!text) return false
  if (text.startsWith('http://') || text.startsWith('https://') || text.startsWith('/')) return true
  if (text.includes('/uploads/')) return true
  return (
    text.includes('.png') ||
    text.includes('.jpg') ||
    text.includes('.jpeg') ||
    text.includes('.gif') ||
    text.includes('.webp') ||
    text.includes('.bmp') ||
    text.includes('.mp3') ||
    text.includes('.wav') ||
    text.includes('.amr') ||
    text.includes('.aac') ||
    text.includes('.m4a') ||
    text.includes('.ogg') ||
    text.includes('.opus')
  )
}

const queuePreviewMediaStats = computed(() => {
  const messages = queuePreviewItem.value?.preview_messages || []
  let imagePlaceholder = 0
  let audioPlaceholder = 0
  let validMediaLinks = 0
  messages.forEach((item) => {
    if (item.content_type === 'image') {
      if (isLikelyMediaLink(item.content)) validMediaLinks += 1
      else imagePlaceholder += 1
    }
    if (item.content_type === 'audio') {
      if (isLikelyMediaLink(item.content)) validMediaLinks += 1
      else audioPlaceholder += 1
    }
  })
  return { imagePlaceholder, audioPlaceholder, validMediaLinks }
})

const filteredQueuePreviewMessages = computed(() => {
  const messages = queuePreviewItem.value?.preview_messages || []
  if (queuePreviewFilter.value === 'all') return messages
  return messages.filter((item) => {
    if (queuePreviewFilter.value === 'valid_link') {
      return (item.content_type === 'image' || item.content_type === 'audio') && isLikelyMediaLink(item.content)
    }
    if (queuePreviewFilter.value === 'image_placeholder') {
      return item.content_type === 'image' && !isLikelyMediaLink(item.content)
    }
    if (queuePreviewFilter.value === 'audio_placeholder') {
      return item.content_type === 'audio' && !isLikelyMediaLink(item.content)
    }
    return true
  })
})

const pagedQueuePreviewMessages = computed(() => {
  const list = filteredQueuePreviewMessages.value
  const start = (queuePreviewPager.page - 1) * queuePreviewPager.page_size
  return list.slice(start, start + queuePreviewPager.page_size)
})

const setQueuePreviewFilter = (next: 'all' | 'image_placeholder' | 'audio_placeholder' | 'valid_link') => {
  queuePreviewFilter.value = next
  queuePreviewPager.page = 1
}

const validateReparseScope = () => {
  if (form.scope === 'hospital' && !form.hospital_id) return '请先选择所属医院'
  if (form.scope === 'department' && !form.department_id) return '请先选择所属科室'
  if (form.scope === 'common' && !isSuperAdmin.value) return '仅超级管理员可重解析通用案例库'
  return ''
}

const reparseDisabledReason = computed(() => {
  if (!reparsePerm.value.allowed) return reparsePerm.value.reason
  const err = validateReparseScope()
  if (err) return err
  if (reparseEstimateLoading.value) return '正在计算预估命中，请稍候'
  if (!reparseEstimate.value) return ''
  if (reparseEstimate.value.matched > 0) return ''
  if (reparseOnlyLegacyOrEmpty.value) return '当前范围无旧规则数据（空 content_hash / 疑似旧规则案例）'
  return '当前范围无可重解析案例'
})

const isReparseActionDisabled = computed(() => {
  if (reparseLoading.value) return true
  return Boolean(reparseDisabledReason.value)
})

const loadReparseEstimate = async () => {
  const err = validateReparseScope()
  if (err) {
    reparseEstimate.value = null
    return
  }
  reparseEstimateLoading.value = true
  try {
    reparseEstimate.value = await estimateBatchReparseQuizzes({
      scope: form.scope,
      hospital_id: form.scope === 'hospital' ? form.hospital_id : undefined,
      department_id: form.scope === 'department' ? form.department_id : undefined,
      limit: reparseLimit.value || 500,
      only_legacy_or_empty_hash: reparseOnlyLegacyOrEmpty.value,
    })
  } catch {
    reparseEstimate.value = null
  } finally {
    reparseEstimateLoading.value = false
  }
}

const triggerLoadReparseEstimate = createDebouncedFn(() => {
  loadReparseEstimate()
}, 320)

const onBatchReparseUpgrade = async () => {
  if (!reparsePerm.value.allowed) {
    ElMessage.warning(reparsePerm.value.reason)
    return
  }
  if (reparseLoading.value) return
  const err = validateReparseScope()
  if (err) {
    ElMessage.warning(err)
    return
  }
  try {
    await confirmDangerousAction(
      `确认按当前范围执行批量重解析升级吗？范围：${importTargetText.value}，最多处理 ${reparseLimit.value} 条案例。${
        reparseOnlyLegacyOrEmpty.value ? '当前模式：仅重解析 content_hash 为空或疑似旧规则案例。' : '当前模式：处理当前范围内全部命中案例。'
      }`,
      '批量重解析升级确认',
    )
  } catch (error: any) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(error?.message || '确认失败')
    return
  }
  reparseLoading.value = true
  try {
    const data = await batchReparseQuizzes({
      scope: form.scope,
      hospital_id: form.scope === 'hospital' ? form.hospital_id : undefined,
      department_id: form.scope === 'department' ? form.department_id : undefined,
      limit: reparseLimit.value || 500,
      only_legacy_or_empty_hash: reparseOnlyLegacyOrEmpty.value,
    })
    reparseResult.value = data
    ElMessage.success(`批量重解析完成：更新${data.updated}，跳过${data.skipped}，失败${data.failed}`)
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || '批量重解析失败')
  } finally {
    reparseLoading.value = false
  }
}

const openImportWorkbench = () => {
  importWorkbenchVisible.value = true
}

const loadLastImportSummary = () => {
  try {
    const raw = window.localStorage.getItem(LAST_IMPORT_SUMMARY_STORAGE_KEY)
    if (!raw) {
      lastImportSummary.value = null
      return
    }
    const parsed = JSON.parse(raw) as LastImportSummary
    if (!parsed || typeof parsed.executed !== 'number' || typeof parsed.finished_at !== 'string') {
      lastImportSummary.value = null
      return
    }
    lastImportSummary.value = parsed
  } catch {
    lastImportSummary.value = null
  }
}

const persistLastImportSummary = (summary: LastImportSummary) => {
  lastImportSummary.value = summary
  try {
    window.localStorage.setItem(LAST_IMPORT_SUMMARY_STORAGE_KEY, JSON.stringify(summary))
  } catch {
    // ignore localStorage errors
  }
}

const lastImportSummaryTimeText = computed(() => {
  if (!lastImportSummary.value?.finished_at) return '--'
  const d = new Date(lastImportSummary.value.finished_at)
  if (Number.isNaN(d.getTime())) return '--'
  return d.toLocaleString('zh-CN', { hour12: false })
})

const loadImportTasks = async () => {
  importTaskLoading.value = true
  try {
    const data = await getImportTaskList({
      page: importTaskPager.page,
      page_size: importTaskPager.page_size,
      scope: importTaskPager.scope || undefined,
      status: importTaskPager.status || undefined,
    })
    importTaskRows.value = data.items
    importTaskPager.total = data.total
  } catch {
    importTaskRows.value = []
    importTaskPager.total = 0
  } finally {
    importTaskLoading.value = false
  }
}

const openImportTaskDetail = async (taskId: number) => {
  importTaskDetailVisible.value = true
  importTaskDetailLoading.value = true
  importTaskDetail.value = null
  try {
    importTaskDetail.value = await getImportTaskDetail(taskId)
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || '获取任务详情失败')
    importTaskDetailVisible.value = false
  } finally {
    importTaskDetailLoading.value = false
  }
}

const saveBlob = (blob: Blob, filename: string) => {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

const exportImportTaskFailedItems = async (taskId: number) => {
  if (!exportFailedPerm.value.allowed) {
    ElMessage.warning(exportFailedPerm.value.reason)
    return
  }
  try {
    const blob = await exportImportTaskFailedCsv(taskId)
    const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')
    saveBlob(blob, `导入任务失败清单_${taskId}_${stamp}.csv`)
    ElMessage.success('失败项 CSV 导出成功')
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || '失败项 CSV 导出失败')
  }
}

const handleMainTabChange = (name: string | number) => {
  if (name === 'records') loadImportTasks()
}

const updateViewport = () => {
  isMobile.value = window.innerWidth < 992
}

onMounted(() => {
  isSuperAdmin.value = userStore.user?.role === 'super_admin'
  const hid = userStore.user?.hospital_id || undefined
  if (!isSuperAdmin.value) {
    form.scope = userStore.user?.department_id ? 'department' : 'hospital'
    form.hospital_id = hid
    form.department_id = userStore.user?.department_id || undefined
  }
  updateViewport()
  loadLastImportSummary()
  window.addEventListener('resize', updateViewport)
  Promise.all([loadHospitals(), loadDepartments()]).then(() => {
    loadQuizOptions()
    loadMetaOptions()
    loadReparseEstimate()
    loadImportTasks()
  })
})

onBeforeUnmount(() => {
  triggerLoadQuizOptions.cancel()
  triggerLoadMetaOptions.cancel()
  triggerLoadReparseEstimate.cancel()
  if (batchParseToastTimer.value) {
    window.clearTimeout(batchParseToastTimer.value)
    batchParseToastTimer.value = null
  }
  window.removeEventListener('resize', updateViewport)
})

watch(
  () => [form.scope, form.hospital_id, form.department_id],
  () => {
    triggerLoadQuizOptions()
    triggerLoadMetaOptions()
  },
)

watch(
  () => [form.scope, form.hospital_id, form.department_id, reparseLimit.value, reparseOnlyLegacyOrEmpty.value],
  () => {
    triggerLoadReparseEstimate()
  },
)
</script>

<template>
  <el-card shadow="never">
    <template #header>
      <div class="admin-card-header">
        <strong class="admin-card-title">导入案例</strong>
        <div class="admin-card-header-actions">
          <el-button @click="$router.push('/admin/quizzes/taxonomy')">分类标签中心</el-button>
          <el-button type="primary" @click="openImportWorkbench">导入文件 / 批量导入</el-button>
        </div>
      </div>
    </template>

    <el-tabs v-model="activeMainTab" class="import-main-tabs" @tab-change="handleMainTabChange">
      <el-tab-pane label="导入工作台" name="workbench">
        <div class="section">
          <el-alert type="info" :closable="false" show-icon>
            <template #title>建议使用“导入工作台”完成参数配置、拖拽上传和队列导入，体验与全站弹窗交互保持一致。</template>
          </el-alert>
          <div class="import-entry">
            <el-button type="primary" size="large" @click="openImportWorkbench">打开导入工作台</el-button>
            <el-tag type="info">当前队列 {{ batchSummary.total }} 条</el-tag>
            <el-tag v-if="batchSummary.pending > 0">待处理 {{ batchSummary.pending }}</el-tag>
            <template v-if="lastImportSummary">
              <el-tag type="success">最近导入成功 {{ lastImportSummary.success }}</el-tag>
              <el-tag type="warning">重复 {{ lastImportSummary.duplicate }}</el-tag>
              <el-tag type="danger">失败 {{ lastImportSummary.failed }}</el-tag>
              <el-tag type="info">执行 {{ lastImportSummary.executed }}（更新 {{ lastImportSummary.updated }}）</el-tag>
              <span class="last-summary-time">最近完成：{{ lastImportSummaryTimeText }}</span>
            </template>
          </div>
        </div>

        <div class="section">
          <el-divider content-position="left">一键批量重解析升级（旧题媒体占位补全）</el-divider>
          <div class="reparse-ops">
            <el-input-number v-model="reparseLimit" :min="1" :max="2000" :step="100" controls-position="right" />
            <div class="retry-switch">
              <span class="retry-label">仅重解析空 hash/疑似旧规则</span>
              <el-switch v-model="reparseOnlyLegacyOrEmpty" />
            </div>
            <el-tooltip
              :disabled="!reparseDisabledReason"
              :content="reparseDisabledReason"
              placement="top"
              effect="dark"
            >
              <span class="reparse-action-wrap">
                <el-button
                  type="primary"
                  plain
                  :loading="reparseLoading"
                  :disabled="isReparseActionDisabled"
                  @click="onBatchReparseUpgrade"
                >
                  一键批量重解析升级
                </el-button>
              </span>
            </el-tooltip>
          </div>
          <div class="reparse-estimate-tip">
            <el-tag v-if="reparseEstimateLoading" type="info" effect="light">预估命中计算中...</el-tag>
            <el-tag v-else-if="reparseEstimate" type="success" effect="light">
              预估命中 {{ reparseEstimate.matched }} 条（上限 {{ reparseEstimate.limit }}）
            </el-tag>
            <el-tag v-else type="warning" effect="light">当前条件不可估算，请先完善范围条件</el-tag>
          </div>
          <div v-if="reparseDisabledReason" class="reparse-disabled-reason">
            {{ reparseDisabledReason }}
          </div>
          <el-alert
            v-if="reparseResult"
            type="success"
            :closable="false"
            show-icon
            class="reparse-result"
            :title="`匹配 ${reparseResult.matched} 条，已处理 ${reparseResult.processed} 条，更新 ${reparseResult.updated} 条，跳过 ${reparseResult.skipped} 条，失败 ${reparseResult.failed} 条`"
          />
          <el-table
            v-if="reparseResult && reparseResult.detail.length"
            :data="reparseResult.detail"
            border
            stripe
            size="small"
            style="margin-top: 8px"
          >
            <el-table-column prop="quiz_id" label="案例ID" width="90" />
            <el-table-column prop="title" label="案例标题" min-width="240" />
            <el-table-column prop="status" label="状态" width="120" />
            <el-table-column prop="reason" label="说明" min-width="220" />
          </el-table>
        </div>
      </el-tab-pane>
      <el-tab-pane label="导入记录" name="records">
        <div class="section">
          <div class="import-task-filters">
            <el-select v-model="importTaskPager.scope" clearable placeholder="导入范围" class="admin-control-w-md" @change="loadImportTasks">
              <el-option label="通用案例库" value="common" />
              <el-option label="医院案例库" value="hospital" />
              <el-option label="科室案例库" value="department" />
            </el-select>
            <el-select v-model="importTaskPager.status" clearable placeholder="任务状态" class="admin-control-w-md" @change="loadImportTasks">
              <el-option label="执行中" value="running" />
              <el-option label="已完成" value="completed" />
              <el-option label="部分失败" value="partial_fail" />
            </el-select>
            <el-button @click="loadImportTasks">刷新记录</el-button>
          </div>
          <el-table v-loading="importTaskLoading" :data="importTaskRows" border stripe style="margin-top: 10px">
            <el-table-column prop="id" label="任务ID" width="110" />
            <el-table-column label="操作人" min-width="120">
              <template #default="{ row }">{{ row.operator_name || `用户#${row.operator_id}` }}</template>
            </el-table-column>
            <el-table-column prop="scope" label="范围" width="110" />
            <el-table-column label="归属" min-width="220">
              <template #default="{ row }">
                {{ row.hospital_name || '-' }} / {{ row.department_name || '-' }}
              </template>
            </el-table-column>
            <el-table-column label="结果" min-width="220">
              <template #default="{ row }">
                执行 {{ row.total }}，成功 {{ row.success }}，重复 {{ row.duplicate }}，失败 {{ row.failed }}，更新 {{ row.updated }}
              </template>
            </el-table-column>
            <el-table-column label="状态" width="110">
              <template #default="{ row }">
                <el-tag :type="row.status === 'completed' ? 'success' : row.status === 'partial_fail' ? 'warning' : 'info'">
                  {{ row.status === 'running' ? '执行中' : row.status === 'partial_fail' ? '部分失败' : '已完成' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="started_at" label="开始时间" min-width="170" />
            <el-table-column prop="finished_at" label="结束时间" min-width="170" />
            <el-table-column label="操作" width="220" fixed="right">
              <template #default="{ row }">
                <el-button link type="primary" @click="openImportTaskDetail(row.id)">详情</el-button>
                <el-tooltip :disabled="exportFailedPerm.allowed" :content="exportFailedPerm.reason" placement="top">
                  <span>
                    <el-button
                      link
                      type="warning"
                      :disabled="!exportFailedPerm.allowed"
                      @click="exportImportTaskFailedItems(row.id)"
                    >
                      失败项CSV
                    </el-button>
                  </span>
                </el-tooltip>
              </template>
            </el-table-column>
          </el-table>
          <div class="pager">
            <el-pagination
              v-model:current-page="importTaskPager.page"
              v-model:page-size="importTaskPager.page_size"
              :total="importTaskPager.total"
              :page-sizes="[10, 20, 50]"
              layout="total, sizes, prev, pager, next, jumper"
              @current-change="loadImportTasks"
              @size-change="
                () => {
                  importTaskPager.page = 1
                  loadImportTasks()
                }
              "
            />
          </div>
        </div>
      </el-tab-pane>
    </el-tabs>
  </el-card>

  <el-dialog
    v-model="importWorkbenchVisible"
    title="导入工作台"
    :width="importWorkbenchDialogWidth"
    :fullscreen="isMobile"
    :close-on-click-modal="false"
    :destroy-on-close="false"
    top="4vh"
    class="import-workbench-dialog"
  >
    <div class="workbench-scroll">
      <el-steps v-if="!isMobile" :active="batchQueue.length ? 3 : 1" finish-status="success" simple>
        <el-step title="设置导入参数" />
        <el-step title="上传文件（支持拖拽）" />
        <el-step title="确认队列导入" />
      </el-steps>

      <div class="section">
        <el-form label-width="90px">
          <el-form-item label="案例库范围" required>
            <el-radio-group v-model="form.scope" :disabled="!isSuperAdmin">
              <el-radio value="department">科室专属</el-radio>
              <el-radio value="hospital">医院专属</el-radio>
              <el-radio value="common">通用案例库</el-radio>
            </el-radio-group>
          </el-form-item>
          <el-form-item v-if="form.scope === 'hospital' || form.scope === 'department'" label="所属医院" required>
            <el-select
              v-model="form.hospital_id"
              :disabled="!isSuperAdmin"
              clearable
              placeholder="请选择医院"
              class="admin-control-w-full"
              @change="
                () => {
                  if (form.scope === 'department') {
                    const options = departmentOptionsByHospital(form.hospital_id)
                    if (!options.some((d) => d.id === form.department_id)) {
                      form.department_id = options[0]?.id
                    }
                  }
                }
              "
            >
              <el-option v-for="h in hospitals" :key="h.id" :label="h.name" :value="h.id" />
            </el-select>
          </el-form-item>
          <el-form-item v-if="form.scope === 'department'" label="所属科室" required>
            <el-select v-model="form.department_id" clearable placeholder="请选择科室" class="admin-control-w-full">
              <el-option
                v-for="d in departmentOptionsByHospital(form.hospital_id)"
                :key="d.id"
                :label="d.name"
                :value="d.id"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="默认聊天类型" required>
            <el-radio-group v-model="form.chat_type">
              <el-radio value="active">主动聊天</el-radio>
              <el-radio value="passive">被动聊天</el-radio>
            </el-radio-group>
          </el-form-item>
          <el-form-item label="分类">
            <el-select
              v-model="form.category"
              clearable
              filterable
              allow-create
              default-first-option
              placeholder="可选择或新建分类"
              class="admin-control-w-full"
            >
              <el-option v-for="item in categoryOptions" :key="item.name" :label="`${item.name} (${item.count})`" :value="item.name" />
            </el-select>
          </el-form-item>
          <el-form-item label="难度">
            <el-rate v-model="form.difficulty" :max="5" />
          </el-form-item>
          <el-form-item label="标签">
            <el-select
              v-model="importTagsModel"
              clearable
              filterable
              multiple
              allow-create
              default-first-option
              collapse-tags
              collapse-tags-tooltip
              placeholder="可多选/新建标签"
              class="admin-control-w-full"
            >
              <el-option v-for="item in tagOptions" :key="item.name" :label="`${item.name} (${item.count})`" :value="item.name" />
            </el-select>
          </el-form-item>
          <el-form-item label="备注">
            <el-input v-model="form.description" type="textarea" :rows="3" />
          </el-form-item>
        </el-form>
        <el-alert type="info" :closable="false" show-icon style="margin-top: 10px">
          <template #title>导入目标：{{ importTargetText }}</template>
        </el-alert>
      </div>

      <div class="section upload-zone">
        <div class="upload-drop-wrapper">
          <el-upload
            drag
            multiple
            accept=".html"
            :disabled="!isUploadReady || batchUploading"
            :auto-upload="false"
            :show-file-list="false"
            :on-change="onFileSelect"
          >
            <el-icon class="upload-icon"><UploadFilled /></el-icon>
            <div class="upload-text">将 HTML 文件拖拽到此处，或<em>点击选择文件</em></div>
            <div class="upload-tip">支持单个或多个 .html 文件，解析后自动加入队列</div>
          </el-upload>
          <div v-if="!isUploadReady" class="upload-overlay">
            <el-icon class="upload-overlay-icon"><WarningFilled /></el-icon>
            <div class="upload-overlay-title">{{ uploadOverlayTitle }}</div>
            <div class="upload-overlay-hint">{{ uploadOverlayHint }}</div>
          </div>
        </div>
        <div v-if="!isUploadReady" class="upload-disabled-tip">{{ uploadBlockReason }}</div>
      </div>

      <div class="section">
        <el-divider content-position="left">待导入队列</el-divider>
        <div class="batch-actions">
          <el-tag type="info">总计 {{ batchSummary.total }}</el-tag>
          <el-tag type="success">成功 {{ batchSummary.success }}</el-tag>
          <el-tag type="warning">重复 {{ batchSummary.duplicate }}</el-tag>
          <el-tag type="danger">失败 {{ batchSummary.failed }}</el-tag>
          <el-tag v-if="batchSummary.pending > 0">待处理 {{ batchSummary.pending }}</el-tag>
          <el-button
            size="small"
            plain
            :disabled="!batchQueue.length || batchSubmitting"
            @click="applyBatchChatType('active')"
          >
            批量设为主动
          </el-button>
          <el-button
            size="small"
            plain
            :disabled="!batchQueue.length || batchSubmitting"
            @click="applyBatchChatType('passive')"
          >
            批量设为被动
          </el-button>
          <div class="retry-switch">
            <span class="retry-label">仅重试待导入项</span>
            <el-switch v-model="batchRetryPendingOnly" />
          </div>
          <el-tooltip :disabled="exportFailedPerm.allowed" :content="exportFailedPerm.reason" placement="top">
            <span>
              <el-button
                type="warning"
                plain
                :disabled="!exportFailedPerm.allowed || batchSummary.failed + batchSummary.duplicate === 0 || batchSubmitting"
                @click="exportFailedBatchItems"
              >
                导出异常清单
              </el-button>
            </span>
          </el-tooltip>
          <el-button :disabled="!batchQueue.length || batchSubmitting" @click="resetBatchQueue">清空队列</el-button>
          <span v-if="!batchSubmitPerm.allowed" class="upload-disabled-tip">{{ batchSubmitPerm.reason }}</span>
          <el-button
            type="primary"
            :disabled="!batchSubmitPerm.allowed || !batchQueue.length || batchSubmitting"
            :loading="batchSubmitting"
            @click="submitBatchImport"
          >
            批量确认导入
          </el-button>
        </div>

        <el-table v-if="batchQueue.length" :data="batchQueue" border stripe style="margin-top: 10px">
          <el-table-column prop="file_name" label="文件名" min-width="220" />
          <el-table-column label="患者/咨询师" min-width="180">
            <template #default="{ row }">
              {{ row.patient_name || '未知患者' }} / {{ row.counselor_name || '未知咨询师' }}
            </template>
          </el-table-column>
          <el-table-column prop="message_count" label="消息数" width="90" />
          <el-table-column label="聊天类型" width="160">
            <template #default="{ row }">
              <el-select v-model="row.chat_type" size="small" style="width: 120px">
                <el-option label="主动聊天" value="active" />
                <el-option label="被动聊天" value="passive" />
              </el-select>
            </template>
          </el-table-column>
          <el-table-column label="标题" min-width="220">
            <template #default="{ row }">
              <el-input v-model="row.title" size="small" />
            </template>
          </el-table-column>
          <el-table-column label="状态" width="120">
            <template #default="{ row }">
              <el-tag
                size="small"
                :type="
                  row.status === 'success'
                    ? 'success'
                    : row.status === 'duplicate'
                      ? 'warning'
                      : row.status === 'error'
                        ? 'danger'
                        : row.status === 'importing'
                          ? 'info'
                          : ''
                "
              >
                {{
                  row.status === 'success'
                    ? '成功'
                    : row.status === 'duplicate'
                      ? '重复'
                      : row.status === 'error'
                        ? '失败'
                        : row.status === 'importing'
                          ? '导入中'
                          : '待导入'
                }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="结果" min-width="260">
            <template #default="{ row }">{{ row.result_text || '-' }}</template>
          </el-table-column>
          <el-table-column label="重复处理" min-width="280">
            <template #default="{ row }">
              <template v-if="row.status === 'duplicate'">
                <div class="dup-handle">
                  <el-select
                    v-model="row.duplicate_action"
                    size="small"
                    style="width: 110px"
                    @change="onDuplicateActionSelectChange(row, $event)"
                  >
                    <el-option label="跳过" value="skip" />
                    <el-option label="更新版本" value="update" />
                  </el-select>
                  <el-input
                    v-if="row.duplicate_action === 'update' && row.duplicate_quiz_id"
                    :model-value="`${row.duplicate_quiz_id} - ${row.duplicate_quiz_title || '重复命中案例'}`"
                    size="small"
                    disabled
                    style="width: 160px"
                  />
                  <el-select
                    v-else-if="row.duplicate_action === 'update'"
                    v-model="row.update_quiz_id"
                    filterable
                    clearable
                    size="small"
                    placeholder="选择更新目标案例"
                    style="width: 160px"
                  >
                    <el-option
                      v-for="q in getUpdateTargetOptions(row)"
                      :key="q.id"
                      :label="`${q.id} - ${q.title}`"
                      :value="q.id"
                    />
                  </el-select>
                </div>
              </template>
              <span v-else>-</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="130">
            <template #default="{ row }">
              <el-button link type="primary" @click="openQueuePreview(row)">预览</el-button>
              <el-button link type="danger" @click="removeBatchItem(row.uid)">移除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>
    <template #footer>
      <el-button @click="importWorkbenchVisible = false">关闭工作台</el-button>
      <el-button
        type="primary"
        :disabled="!batchSubmitPerm.allowed || !batchQueue.length || batchSubmitting"
        :loading="batchSubmitting"
        @click="submitBatchImport"
      >
        提交导入
      </el-button>
    </template>
  </el-dialog>

  <el-dialog v-model="queuePreviewVisible" :title="queuePreviewItem?.file_name || '预览消息'" width="900px">
    <template v-if="queuePreviewItem">
      <div class="media-stats">
        <el-tag class="media-filter-tag" :class="{ active: queuePreviewFilter === 'all' }" @click="setQueuePreviewFilter('all')">
          全部消息 {{ queuePreviewItem.preview_messages.length }} 条
        </el-tag>
        <el-tag
          class="media-filter-tag"
          :class="{ active: queuePreviewFilter === 'image_placeholder' }"
          type="warning"
          @click="setQueuePreviewFilter('image_placeholder')"
        >
          图片占位 {{ queuePreviewMediaStats.imagePlaceholder }} 条
        </el-tag>
        <el-tag
          class="media-filter-tag"
          :class="{ active: queuePreviewFilter === 'audio_placeholder' }"
          type="info"
          @click="setQueuePreviewFilter('audio_placeholder')"
        >
          语音占位 {{ queuePreviewMediaStats.audioPlaceholder }} 条
        </el-tag>
        <el-tag
          class="media-filter-tag"
          :class="{ active: queuePreviewFilter === 'valid_link' }"
          type="success"
          @click="setQueuePreviewFilter('valid_link')"
        >
          有效媒体链接 {{ queuePreviewMediaStats.validMediaLinks }} 条
        </el-tag>
      </div>
      <el-table :data="pagedQueuePreviewMessages" border stripe style="margin-top: 10px" max-height="420">
        <el-table-column prop="sequence" label="#" width="60" />
        <el-table-column label="角色" width="100">
          <template #default="{ row }">
            <el-tag :type="row.role === 'patient' ? 'info' : 'success'">
              {{ row.role === 'patient' ? '患者' : '咨询师' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="sender_name" label="发送者" width="140" />
        <el-table-column prop="content_type" label="类型" width="90" />
        <el-table-column prop="content" label="内容" min-width="280" />
        <el-table-column prop="original_time" label="时间" width="180" />
      </el-table>
      <div class="pager">
        <el-pagination
          v-model:current-page="queuePreviewPager.page"
          v-model:page-size="queuePreviewPager.page_size"
          :page-sizes="[10, 20, 50, 100]"
          layout="total, sizes, prev, pager, next, jumper"
          :total="filteredQueuePreviewMessages.length"
          @size-change="queuePreviewPager.page = 1"
        />
      </div>
    </template>
  </el-dialog>

  <el-dialog v-model="importTaskDetailVisible" title="导入任务详情" width="760px">
    <div v-loading="importTaskDetailLoading">
      <template v-if="importTaskDetail">
        <el-descriptions :column="2" border>
          <el-descriptions-item label="任务ID">{{ importTaskDetail.id }}</el-descriptions-item>
          <el-descriptions-item label="操作人">
            {{ importTaskDetail.operator_name || `用户#${importTaskDetail.operator_id}` }}
          </el-descriptions-item>
          <el-descriptions-item label="导入范围">{{ importTaskDetail.scope }}</el-descriptions-item>
          <el-descriptions-item label="任务状态">{{ importTaskDetail.status }}</el-descriptions-item>
          <el-descriptions-item label="医院">{{ importTaskDetail.hospital_name || '-' }}</el-descriptions-item>
          <el-descriptions-item label="科室">{{ importTaskDetail.department_name || '-' }}</el-descriptions-item>
          <el-descriptions-item label="开始时间">{{ importTaskDetail.started_at }}</el-descriptions-item>
          <el-descriptions-item label="结束时间">{{ importTaskDetail.finished_at || '-' }}</el-descriptions-item>
        </el-descriptions>
        <el-alert
          type="info"
          :closable="false"
          style="margin-top: 12px"
          :title="`执行 ${importTaskDetail.total}，成功 ${importTaskDetail.success}，重复 ${importTaskDetail.duplicate}，失败 ${importTaskDetail.failed}，更新 ${importTaskDetail.updated}`"
        />
        <div class="task-detail-failed-list" v-if="importTaskFailedItems.length">
          <el-divider content-position="left">失败明细</el-divider>
          <el-table :data="importTaskFailedItems" border stripe size="small" max-height="260">
            <el-table-column prop="file_name" label="文件名" min-width="180" />
            <el-table-column prop="title" label="标题" min-width="180" />
            <el-table-column prop="status" label="状态" width="90" />
            <el-table-column prop="result_text" label="说明" min-width="220" />
          </el-table>
        </div>
      </template>
    </div>
    <template #footer>
      <el-button @click="importTaskDetailVisible = false">关闭</el-button>
      <el-button
        type="warning"
        :disabled="!exportFailedPerm.allowed || !importTaskDetail"
        @click="importTaskDetail && exportImportTaskFailedItems(importTaskDetail.id)"
      >
        导出失败项 CSV
      </el-button>
    </template>
  </el-dialog>

  <el-dialog
    v-model="checklistConfirmVisible"
    title="本次导入前检查清单"
    width="620px"
    :close-on-click-modal="false"
    :close-on-press-escape="false"
  >
    <div class="checklist-content">{{ checklistConfirmText }}</div>
    <el-alert
      v-if="checklistRequireAcknowledge"
      type="warning"
      :closable="false"
      show-icon
      style="margin-top: 12px"
      title="检测到主动/被动分布异常集中，请确认是否误用批量设置。"
    />
    <el-checkbox
      v-if="checklistRequireAcknowledge"
      v-model="checklistConfirmAcknowledge"
      style="margin-top: 10px"
    >
      我已确认分布异常，继续提交
    </el-checkbox>
    <template #footer>
      <el-button @click="closeChecklistConfirm(false)">取消</el-button>
      <el-button
        type="primary"
        :disabled="checklistRequireAcknowledge && !checklistConfirmAcknowledge"
        @click="closeChecklistConfirm(true)"
      >
        确认提交
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.section {
  margin-top: var(--space-5);
}

.import-entry {
  margin-top: var(--space-3);
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
}

.last-summary-time {
  font-size: var(--font-size-xs);
  color: var(--el-text-color-secondary);
}

.workbench-scroll {
  max-height: min(78vh, 900px);
  overflow-y: auto;
  padding-right: 2px;
}

.upload-zone :deep(.el-upload) {
  width: 100%;
}

.upload-zone :deep(.el-upload-dragger) {
  width: 100%;
  padding: 32px var(--space-5);
  border: 2px dashed var(--ui-border-soft);
  border-radius: var(--radius-md);
  background: color-mix(in srgb, var(--ui-surface-1) 60%, transparent 40%);
  transition: border-color 0.25s, background 0.25s;
}

.upload-zone :deep(.el-upload-dragger:hover) {
  border-color: var(--brand-accent);
  background: color-mix(in srgb, var(--brand-accent) 6%, var(--ui-surface-1) 94%);
}

.upload-zone :deep(.el-upload-dragger.is-dragover) {
  border-color: var(--brand-accent);
  background: color-mix(in srgb, var(--brand-accent) 12%, var(--ui-surface-1) 88%);
}

.upload-drop-wrapper {
  position: relative;
}

.upload-overlay {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-md);
  background: color-mix(in srgb, var(--ui-surface-1) 86%, #fff 14%);
  border: 1px dashed color-mix(in srgb, var(--el-color-warning) 48%, var(--ui-border-soft) 52%);
  backdrop-filter: blur(1.5px);
  z-index: 2;
  pointer-events: all;
}

.upload-overlay-icon {
  font-size: 26px;
  color: var(--el-color-warning);
}

.upload-overlay-title {
  margin-top: var(--space-2);
  font-size: var(--font-size-body);
  color: var(--el-color-warning-dark-2);
  font-weight: 600;
}

.upload-overlay-hint {
  margin-top: var(--space-1);
  font-size: var(--font-size-xs);
  color: var(--el-text-color-secondary);
}

.upload-icon {
  font-size: 44px;
  color: var(--el-text-color-secondary);
}

.upload-text {
  margin-top: var(--space-2);
  font-size: var(--font-size-h6);
  color: var(--el-text-color-primary);
}

.upload-text em {
  color: var(--brand-accent);
  font-style: normal;
}

.upload-tip {
  margin-top: 6px;
  font-size: var(--font-size-xs);
  color: var(--el-text-color-secondary);
}

.upload-disabled-tip {
  margin-top: var(--space-2);
  color: var(--el-color-warning);
  font-size: var(--font-size-xs);
}

.batch-actions {
  margin-top: var(--space-3);
  display: flex;
  gap: var(--space-2);
  justify-content: flex-end;
  align-items: center;
  flex-wrap: wrap;
}

.retry-switch {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.retry-label {
  font-size: var(--font-size-xs);
  color: var(--el-text-color-secondary);
}

.dup-handle {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.media-stats {
  margin-top: 10px;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.media-filter-tag {
  cursor: pointer;
  user-select: none;
}

.media-filter-tag.active {
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--el-color-primary) 52%, transparent 48%);
}

.pager {
  margin-top: 10px;
  display: flex;
  justify-content: flex-end;
}

.reparse-ops {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}

.reparse-result {
  margin-top: 10px;
}

.reparse-estimate-tip {
  margin-top: var(--space-2);
  display: flex;
  align-items: center;
}

.reparse-disabled-reason {
  margin-top: 6px;
  color: var(--el-color-warning);
  font-size: var(--font-size-xs);
}

.reparse-action-wrap {
  display: inline-flex;
}

.reparse-action-wrap :deep(.el-button.is-disabled) {
  cursor: not-allowed;
}

.checklist-content {
  white-space: pre-wrap;
  line-height: 1.72;
  color: var(--el-text-color-primary);
}

.import-main-tabs {
  margin-top: var(--space-2);
}

.import-task-filters {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
}

.task-detail-failed-list {
  margin-top: var(--space-3);
}

@media (max-width: 992px) {
  .workbench-scroll {
    max-height: none;
    overflow-y: visible;
    padding-right: 0;
  }
  .batch-actions {
    justify-content: flex-start;
  }
  .import-task-filters {
    align-items: stretch;
  }
}
</style>
