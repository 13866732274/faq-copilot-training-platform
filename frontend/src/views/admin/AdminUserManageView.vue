<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useRoute } from 'vue-router'
import { getSystemSettings, updateSystemSettings } from '../../api/system'
import {
  bulkImportStudents,
  bulkSetUserMenuPermissions,
  bulkSetUserStatus,
  createUser,
  getUsers,
  updateUser,
  type UserItem,
} from '../../api/users'
import { getHospitals, type HospitalItem } from '../../api/hospital'
import { getDepartments, type DepartmentItem } from '../../api/department'
import { useUserStore } from '../../stores/user'
import AdminTableSkeleton from '../../components/admin/AdminTableSkeleton.vue'
import {
  DRAWER_DESKTOP_SIZE,
  UI_TEXT,
  confirmDangerousAction,
  createDebouncedFn,
  getDrawerSize,
} from '../../composables/useUiStandards'
import {
  CONFIGURABLE_MENUS,
  CONFIGURABLE_MENU_KEYS,
  MENU_PERMISSION_TEMPLATES,
} from '../../constants/menus'

const userStore = useUserStore()
const route = useRoute()
const isSuperAdmin = ref(false)
const loading = ref(false)
const submitting = ref(false)
const rows = ref<UserItem[]>([])
const hospitals = ref<HospitalItem[]>([])
const departments = ref<DepartmentItem[]>([])
const selectedIds = ref<number[]>([])
const isMobile = ref(false)

const pager = reactive({
  page: 1,
  page_size: 20,
  total: 0,
  keyword: '',
  role: '',
  hospital_id: undefined as number | undefined,
  department_id: undefined as number | undefined,
})

const createDrawerVisible = ref(false)
const editDrawerVisible = ref(false)
const importDrawerVisible = ref(false)
const bulkMenuDrawerVisible = ref(false)
const DIALOG_FAQ_TEMPLATE_KEY = 'dialog-faq'
const createMenuTemplate = ref(DIALOG_FAQ_TEMPLATE_KEY)
const editMenuTemplate = ref(DIALOG_FAQ_TEMPLATE_KEY)
const bulkMenuTemplate = ref(DIALOG_FAQ_TEMPLATE_KEY)
const CUSTOM_TEMPLATE_KEY = 'custom'
const adminTemplateLockEnabled = ref(true)

const createForm = reactive({
  username: '',
  password: '',
  real_name: '',
  role: 'student',
  hospital_id: undefined as number | undefined,
  department_id: undefined as number | undefined,
  department_ids: [] as number[],
  menu_permissions: [] as string[],
  is_all_hospitals: false,
})

const editForm = reactive({
  id: 0,
  real_name: '',
  role: 'student',
  password: '',
  hospital_id: undefined as number | undefined,
  department_id: undefined as number | undefined,
  department_ids: [] as number[],
  menu_permissions: [] as string[],
  is_all_hospitals: false,
})

const importForm = reactive({
  role: 'student' as 'student' | 'admin',
  hospital_id: undefined as number | undefined,
  department_id: undefined as number | undefined,
  default_password: '123456',
  text: '',
})
const importResult = ref<{
  total: number
  created: number
  skipped: number
  errors: string[]
  failed_items?: Array<{ line_no: number; username: string; real_name: string; reason: string }>
} | null>(null)
const latestBatchSummary = ref<{
  action: string
  total: number
  success: number
  skipped: number
  failed: number
  time: string
} | null>(null)

const bulkMenuForm = reactive({
  menu_permissions: [...CONFIGURABLE_MENU_KEYS] as string[],
})

const roleText = (role: string) => {
  if (role === 'super_admin') return '超级管理员'
  if (role === 'admin') return '管理员'
  return '咨询员'
}

const statusText = (active: boolean) => (active ? '启用' : '禁用')

const generateRandomPassword = (length = 10) => {
  const chars = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789!@#$%^&*'
  return Array.from({ length }, () => chars[Math.floor(Math.random() * chars.length)]).join('')
}

const copyText = async (text: string) => {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch {
    // ignore
  }
  return false
}

const setLatestBatchSummary = (payload: {
  action: string
  total: number
  success: number
  skipped: number
  failed: number
}) => {
  latestBatchSummary.value = {
    ...payload,
    time: new Date().toLocaleString('zh-CN', { hour12: false }),
  }
}

const resolveScope = (row: UserItem) => {
  if (row.role === 'super_admin' || row.is_all_hospitals) return '全部医院'
  if (row.role === 'admin' && row.department_ids?.length) {
    const names = row.department_ids
      .map((id) => {
        const d = departments.value.find((x) => x.id === id)
        if (!d) return ''
        const h = hospitals.value.find((x) => x.id === d.hospital_id)
        return `${h?.name || '未知医院'} / ${d.name}`
      })
      .filter(Boolean)
    if (names.length) return names.join('；')
  }
  return `${row.hospital_name || '-'} / ${row.department_name || '-'}`
}

const departmentOptionsByHospital = (hospitalId?: number) => {
  if (!hospitalId) return departments.value
  return departments.value.filter((d) => d.hospital_id === hospitalId)
}

const departmentLabel = (d: DepartmentItem) => {
  const h = hospitals.value.find((x) => x.id === d.hospital_id)?.name || '未命名医院'
  return `${h} / ${d.name}`
}

const menuPermissionTemplates = MENU_PERMISSION_TEMPLATES
const dialogFaqTemplate = menuPermissionTemplates.find((tpl) => tpl.key === DIALOG_FAQ_TEMPLATE_KEY)
const settingsState = reactive({
  site_name: '',
  site_subtitle: '',
  logo_url: null as string | null,
  brand_accent: '#07c160',
  enable_ai_scoring: false,
  enable_export_center: true,
  enable_audit_enhanced: true,
  admin_menu_template_lock: true,
  faq_task_timeout_minutes: 15 as 5 | 15 | 30,
})

const sameMenuSet = (source: string[], target: string[]) => {
  if (source.length !== target.length) return false
  const sourceSet = new Set(source)
  return target.every((item) => sourceSet.has(item))
}

const detectTemplateKey = (menuKeys: string[]) => {
  const normalized = Array.from(new Set(menuKeys)).sort()
  const matched = menuPermissionTemplates.find((tpl) => sameMenuSet(normalized, [...tpl.menuKeys].sort()))
  return matched?.key || CUSTOM_TEMPLATE_KEY
}

const applyCreateTemplate = (templateKey: string) => {
  if (templateKey === CUSTOM_TEMPLATE_KEY) return
  const template = menuPermissionTemplates.find((tpl) => tpl.key === templateKey)
  if (!template) return
  createForm.menu_permissions = [...template.menuKeys]
}

const applyEditTemplate = (templateKey: string) => {
  if (templateKey === CUSTOM_TEMPLATE_KEY) return
  const template = menuPermissionTemplates.find((tpl) => tpl.key === templateKey)
  if (!template) return
  editForm.menu_permissions = [...template.menuKeys]
}

const onCreateTemplateChange = (value: string) => {
  if (adminTemplateLockEnabled.value && createForm.role === 'admin') {
    createMenuTemplate.value = dialogFaqTemplate ? DIALOG_FAQ_TEMPLATE_KEY : createMenuTemplate.value
    applyCreateTemplate(createMenuTemplate.value)
    return
  }
  applyCreateTemplate(value)
}

const onEditTemplateChange = (value: string) => {
  applyEditTemplate(value)
}

const applyBulkTemplate = (templateKey: string) => {
  if (templateKey === CUSTOM_TEMPLATE_KEY) return
  const template = menuPermissionTemplates.find((tpl) => tpl.key === templateKey)
  if (!template) return
  bulkMenuForm.menu_permissions = [...template.menuKeys]
}

const onBulkTemplateChange = (value: string) => {
  applyBulkTemplate(value)
}

const isCreateMenuAll = computed(
  () => createForm.menu_permissions.length === CONFIGURABLE_MENU_KEYS.length,
)
const isEditMenuAll = computed(
  () => editForm.menu_permissions.length === CONFIGURABLE_MENU_KEYS.length,
)
const isBulkMenuAll = computed(
  () => bulkMenuForm.menu_permissions.length === CONFIGURABLE_MENU_KEYS.length,
)
const canEditTargetMenuPermissions = computed(() => editForm.id !== (userStore.user?.id || 0))

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

const load = async () => {
  loading.value = true
  try {
    const data = await getUsers({
      page: pager.page,
      page_size: pager.page_size,
      keyword: pager.keyword || undefined,
      role: pager.role || undefined,
      hospital_id: pager.hospital_id,
      department_id: pager.department_id,
    })
    rows.value = data.items
    pager.total = data.total
    selectedIds.value = []
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || '获取用户失败')
  } finally {
    loading.value = false
  }
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

const onPagerHospitalChange = () => {
  pager.department_id = undefined
}

const onSelectionChange = (val: UserItem[]) => {
  selectedIds.value = val.map((i) => i.id)
}

const toggleMobileSelection = (id: number, checked: boolean) => {
  if (checked) {
    if (!selectedIds.value.includes(id)) selectedIds.value = [...selectedIds.value, id]
    return
  }
  selectedIds.value = selectedIds.value.filter((item) => item !== id)
}

const resetCreateForm = () => {
  createForm.username = ''
  createForm.password = ''
  createForm.real_name = ''
  createForm.role = 'student'
  createForm.hospital_id = isSuperAdmin.value ? undefined : userStore.user?.hospital_id || undefined
  createForm.department_id = isSuperAdmin.value ? undefined : userStore.user?.department_id || undefined
  createForm.department_ids = []
  createForm.menu_permissions = [...(dialogFaqTemplate?.menuKeys || CONFIGURABLE_MENU_KEYS)]
  createMenuTemplate.value = dialogFaqTemplate ? DIALOG_FAQ_TEMPLATE_KEY : 'all-management'
  createForm.is_all_hospitals = false
}

const openCreateDrawer = () => {
  resetCreateForm()
  createDrawerVisible.value = true
}

const openEditDrawer = (row: UserItem) => {
  editForm.id = row.id
  editForm.real_name = row.real_name
  editForm.role = row.role
  editForm.password = ''
  editForm.hospital_id = row.hospital_id || undefined
  editForm.department_id = row.department_id || undefined
  editForm.department_ids = [...(row.department_ids || (row.department_id ? [row.department_id] : []))]
  editForm.menu_permissions = [...(row.menu_permissions?.length ? row.menu_permissions : CONFIGURABLE_MENU_KEYS)]
  editMenuTemplate.value = detectTemplateKey(editForm.menu_permissions)
  editForm.is_all_hospitals = Boolean(row.is_all_hospitals)
  editDrawerVisible.value = true
}

const onCreateMenuSelectAll = (checked: boolean) => {
  if (adminTemplateLockEnabled.value && createForm.role === 'admin') return
  createForm.menu_permissions = checked ? [...CONFIGURABLE_MENU_KEYS] : []
  createMenuTemplate.value = detectTemplateKey(createForm.menu_permissions)
}

const onEditMenuSelectAll = (checked: boolean) => {
  editForm.menu_permissions = checked ? [...CONFIGURABLE_MENU_KEYS] : []
  editMenuTemplate.value = detectTemplateKey(editForm.menu_permissions)
}

const onBulkMenuSelectAll = (checked: boolean) => {
  bulkMenuForm.menu_permissions = checked ? [...CONFIGURABLE_MENU_KEYS] : []
  bulkMenuTemplate.value = detectTemplateKey(bulkMenuForm.menu_permissions)
}

const onCreateMenuPermissionsChange = () => {
  if (adminTemplateLockEnabled.value && createForm.role === 'admin') {
    createForm.menu_permissions = [...(dialogFaqTemplate?.menuKeys || createForm.menu_permissions)]
    createMenuTemplate.value = dialogFaqTemplate ? DIALOG_FAQ_TEMPLATE_KEY : createMenuTemplate.value
    return
  }
  createMenuTemplate.value = detectTemplateKey(createForm.menu_permissions)
}

const onEditMenuPermissionsChange = () => {
  editMenuTemplate.value = detectTemplateKey(editForm.menu_permissions)
}

const onBulkMenuPermissionsChange = () => {
  bulkMenuTemplate.value = detectTemplateKey(bulkMenuForm.menu_permissions)
}

const normalizeMenuPermissions = (role: string, menuPermissions: string[]) => {
  if (role !== 'admin') return null
  const deduped = Array.from(
    new Set(menuPermissions.filter((item) => CONFIGURABLE_MENU_KEYS.includes(item))),
  )
  if (!deduped.length || deduped.length === CONFIGURABLE_MENU_KEYS.length) return null
  return deduped
}

const resolveCreateMenuPermissions = () => {
  if (createForm.role === 'admin' && adminTemplateLockEnabled.value && dialogFaqTemplate) {
    return [...dialogFaqTemplate.menuKeys]
  }
  return createForm.menu_permissions
}

const onCreateHospitalChange = (hospitalId?: number) => {
  const list = departmentOptionsByHospital(hospitalId)
  if (!list.some((i) => i.id === createForm.department_id)) createForm.department_id = undefined
  createForm.department_ids = createForm.department_ids.filter((id) => list.some((i) => i.id === id))
}

const onEditHospitalChange = (hospitalId?: number) => {
  const list = departmentOptionsByHospital(hospitalId)
  if (!list.some((i) => i.id === editForm.department_id)) editForm.department_id = undefined
  editForm.department_ids = editForm.department_ids.filter((id) => list.some((i) => i.id === id))
}

const validateUserForm = (form: typeof createForm | typeof editForm) => {
  if (!form.real_name.trim()) return '请输入姓名'
  if (form.role === 'student') {
    if (!form.hospital_id) return '咨询员必须选择医院'
    if (!form.department_id) return '咨询员必须选择科室'
  }
  if (form.role === 'admin' && !form.is_all_hospitals && !form.department_ids.length && !form.department_id) {
    return '管理员至少选择一个负责科室，或开启全院权限'
  }
  return ''
}

const submitCreate = async () => {
  if (!createForm.username.trim() || !createForm.password.trim()) {
    ElMessage.warning('请输入用户名和密码')
    return
  }
  const err = validateUserForm(createForm)
  if (err) {
    ElMessage.warning(err)
    return
  }
  submitting.value = true
  try {
    await createUser({
      username: createForm.username.trim(),
      password: createForm.password,
      real_name: createForm.real_name.trim(),
      role: createForm.role,
      hospital_id: createForm.hospital_id,
      department_id: createForm.department_id,
      department_ids: createForm.role === 'admin' ? Array.from(new Set(createForm.department_ids)) : [],
      menu_permissions: normalizeMenuPermissions(createForm.role, resolveCreateMenuPermissions()),
      hospital_ids: [],
      is_all_hospitals: createForm.role === 'admin' ? createForm.is_all_hospitals : false,
    })
    ElMessage.success('新增用户成功')
    createDrawerVisible.value = false
    await load()
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || '新增失败')
  } finally {
    submitting.value = false
  }
}

const submitEdit = async () => {
  const err = validateUserForm(editForm)
  if (err) {
    ElMessage.warning(err)
    return
  }
  submitting.value = true
  try {
    await updateUser(editForm.id, {
      real_name: editForm.real_name.trim(),
      role: editForm.role,
      password: editForm.password || undefined,
      hospital_id: editForm.hospital_id,
      department_id: editForm.department_id,
      department_ids: editForm.role === 'admin' ? Array.from(new Set(editForm.department_ids)) : [],
      menu_permissions:
        isSuperAdmin.value && canEditTargetMenuPermissions.value
          ? normalizeMenuPermissions(editForm.role, editForm.menu_permissions)
          : undefined,
      hospital_ids: [],
      is_all_hospitals: editForm.role === 'admin' ? editForm.is_all_hospitals : false,
    })
    ElMessage.success('更新用户成功')
    editDrawerVisible.value = false
    await load()
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || '更新失败')
  } finally {
    submitting.value = false
  }
}

const resetPassword = async (row: UserItem) => {
  const newPassword = generateRandomPassword()
  try {
    await confirmDangerousAction(
      `确认将用户 ${row.username} 的密码重置为随机密码吗？\n新密码：${newPassword}\n请在确认后通知用户尽快修改密码。`,
      '重置密码确认',
    )
    await updateUser(row.id, { password: newPassword })
    const copied = await copyText(newPassword)
    ElMessage.success(
      `已将 ${row.username} 的密码重置为随机密码：${newPassword}${copied ? '（已复制到剪贴板）' : ''}`,
    )
  } catch (error: any) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(error?.response?.data?.detail || '重置失败')
  }
}

const setUsersActive = async (userIds: number[], active: boolean) => {
  if (!userIds.length) {
    ElMessage.warning('请先选择用户')
    return
  }
  const title = active ? '批量启用' : '批量禁用'
  const message = active
    ? `确认启用选中的 ${userIds.length} 个账号吗？`
    : `确认禁用选中的 ${userIds.length} 个账号吗？（禁用后该账号将无法登录）`
  try {
    await confirmDangerousAction(message, title)
    const res = await bulkSetUserStatus({ user_ids: userIds, is_active: active })
    setLatestBatchSummary({
      action: title,
      total: res.total,
      success: res.updated,
      skipped: res.skipped,
      failed: 0,
    })
    ElMessage.success(`${title}完成：处理${res.total}，成功${res.updated}，跳过${res.skipped}`)
    await load()
  } catch (error: any) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(error?.response?.data?.detail || `${title}失败`)
  }
}

const removeSingle = (row: UserItem) => setUsersActive([row.id], false)
const enableSingle = (row: UserItem) => setUsersActive([row.id], true)

const openBulkMenuDrawer = () => {
  if (!selectedIds.value.length) {
    ElMessage.warning('请先选择用户')
    return
  }
  bulkMenuForm.menu_permissions = [...(dialogFaqTemplate?.menuKeys || CONFIGURABLE_MENU_KEYS)]
  bulkMenuTemplate.value = dialogFaqTemplate ? DIALOG_FAQ_TEMPLATE_KEY : 'all-management'
  bulkMenuDrawerVisible.value = true
}

const applyDialogFaqTemplateQuick = async () => {
  if (!selectedIds.value.length) {
    ElMessage.warning('请先选择用户')
    return
  }
  if (!dialogFaqTemplate) {
    ElMessage.error('未找到“对话+FAQ”模板，请刷新后重试')
    return
  }
  try {
    await confirmDangerousAction(
      `确认将选中 ${selectedIds.value.length} 个用户一键设置为“对话+FAQ”权限模板吗？`,
      '一键套用模板确认',
    )
    submitting.value = true
    const res = await bulkSetUserMenuPermissions({
      user_ids: selectedIds.value,
      menu_permissions: [...dialogFaqTemplate.menuKeys],
    })
    const reasonText = Object.entries(res.skipped_reason_ids || {})
      .filter(([, ids]) => Array.isArray(ids) && ids.length > 0)
      .map(([reason, ids]) => `${reason}${ids.length}人`)
      .join('；')
    const suffix = reasonText ? `（跳过原因：${reasonText}）` : ''
    setLatestBatchSummary({
      action: '一键套用 对话+FAQ 模板',
      total: res.total,
      success: res.updated,
      skipped: res.skipped,
      failed: 0,
    })
    ElMessage.success(`模板套用完成：处理${res.total}，成功${res.updated}，跳过${res.skipped}${suffix}`)
    await load()
  } catch (error: any) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(error?.response?.data?.detail || '一键套用模板失败')
  } finally {
    submitting.value = false
  }
}

const loadTemplateLockFromSystem = async () => {
  try {
    const data = await getSystemSettings()
    settingsState.site_name = data.site_name
    settingsState.site_subtitle = data.site_subtitle
    settingsState.logo_url = data.logo_url || null
    settingsState.brand_accent = data.brand_accent
    settingsState.enable_ai_scoring = data.enable_ai_scoring
    settingsState.enable_export_center = data.enable_export_center
    settingsState.enable_audit_enhanced = data.enable_audit_enhanced
    settingsState.admin_menu_template_lock = data.admin_menu_template_lock
    settingsState.faq_task_timeout_minutes = data.faq_task_timeout_minutes
    adminTemplateLockEnabled.value = data.admin_menu_template_lock
  } catch {
    // keep local default
  }
}

const submitBulkMenuPermissions = async () => {
  if (!selectedIds.value.length) {
    ElMessage.warning('请先选择用户')
    return
  }
  const menuPermissions = normalizeMenuPermissions('admin', bulkMenuForm.menu_permissions)
  try {
    await confirmDangerousAction(
      `确认批量设置选中 ${selectedIds.value.length} 个用户的菜单权限吗？`,
      '批量菜单权限确认',
    )
    submitting.value = true
    const res = await bulkSetUserMenuPermissions({
      user_ids: selectedIds.value,
      menu_permissions: menuPermissions,
    })
    const reasonText = Object.entries(res.skipped_reason_ids || {})
      .filter(([, ids]) => Array.isArray(ids) && ids.length > 0)
      .map(([reason, ids]) => `${reason}${ids.length}人`)
      .join('；')
    const suffix = reasonText ? `（跳过原因：${reasonText}）` : ''
    setLatestBatchSummary({
      action: '批量菜单权限',
      total: res.total,
      success: res.updated,
      skipped: res.skipped,
      failed: 0,
    })
    ElMessage.success(`批量菜单权限完成：处理${res.total}，成功${res.updated}，跳过${res.skipped}${suffix}`)
    bulkMenuDrawerVisible.value = false
    await load()
  } catch (error: any) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(error?.response?.data?.detail || '批量菜单权限失败')
  } finally {
    submitting.value = false
  }
}

const openImportDrawer = () => {
  importForm.role = 'student'
  importForm.default_password = '123456'
  importForm.text = ''
  importForm.hospital_id = isSuperAdmin.value ? undefined : userStore.user?.hospital_id || undefined
  importForm.department_id = isSuperAdmin.value ? undefined : userStore.user?.department_id || undefined
  importResult.value = null
  importDrawerVisible.value = true
}

const onImportHospitalChange = (hospitalId?: number) => {
  const list = departmentOptionsByHospital(hospitalId)
  if (!list.some((i) => i.id === importForm.department_id)) importForm.department_id = undefined
}

const submitBulkImport = async () => {
  const lines = importForm.text
    .split('\n')
    .map((s) => s.trim())
    .filter(Boolean)
  if (!lines.length) {
    ElMessage.warning('请先输入导入内容')
    return
  }
  if (!importForm.hospital_id || !importForm.department_id) {
    ElMessage.warning('请先选择所属医院和所属科室')
    return
  }
  const items = lines
    .map((line) => {
      const parts = line.split(/[,\t，]/).map((s) => s.trim())
      if (parts.length < 2) return null
      return { username: parts[0], real_name: parts[1] }
    })
    .filter((i): i is { username: string; real_name: string } => Boolean(i))
  if (!items.length) {
    ElMessage.warning('格式不正确，请按“用户名,姓名”每行一条')
    return
  }
  try {
    await confirmDangerousAction(
      `确认批量导入 ${items.length} 个${importForm.role === 'admin' ? '管理员' : '咨询员'}账号吗？`,
      '批量导入确认',
    )
  } catch (error: any) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(error?.message || '批量导入确认失败')
    return
  }
  submitting.value = true
  try {
    const res = await bulkImportStudents({
      role: importForm.role,
      hospital_id: importForm.hospital_id,
      department_id: importForm.department_id,
      default_password: importForm.default_password,
      items,
    })
    importResult.value = res
    setLatestBatchSummary({
      action: '批量导入账号',
      total: res.total,
      success: res.created,
      skipped: res.skipped,
      failed: res.failed_items?.length || 0,
    })
    ElMessage.success(`导入完成：总计${res.total}，成功${res.created}，跳过${res.skipped}`)
    await load()
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || '批量导入失败')
  } finally {
    submitting.value = false
  }
}

const exportImportFailedItems = () => {
  const failedItems = importResult.value?.failed_items || []
  if (!failedItems.length) {
    ElMessage.warning('当前没有失败明细可导出')
    return
  }
  const rows = [
    ['行号', '用户名', '姓名', '失败原因', '建议动作'],
    ...failedItems.map((item) => [
      String(item.line_no),
      item.username || '-',
      item.real_name || '-',
      (item.reason || '未知原因').replace(/\r?\n/g, ' '),
      '请修正后重新导入',
    ]),
  ]
  const csvContent = rows
    .map((line) => line.map((cell) => `"${String(cell).replace(/"/g, '""')}"`).join(','))
    .join('\n')
  const blob = new Blob([`\ufeff${csvContent}`], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `用户批量导入失败清单_${new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')}.csv`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
  ElMessage.success(`已导出失败清单（${failedItems.length}条）`)
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
  Promise.all([loadHospitals(), loadDepartments(), loadTemplateLockFromSystem()]).then(load)
})

watch(adminTemplateLockEnabled, (enabled) => {
  if (settingsState.admin_menu_template_lock === enabled) return
  settingsState.admin_menu_template_lock = enabled
  if (isSuperAdmin.value) {
    updateSystemSettings({
      site_name: settingsState.site_name,
      site_subtitle: settingsState.site_subtitle,
      logo_url: settingsState.logo_url,
      brand_accent: settingsState.brand_accent,
      enable_ai_scoring: settingsState.enable_ai_scoring,
      enable_export_center: settingsState.enable_export_center,
      enable_audit_enhanced: settingsState.enable_audit_enhanced,
      admin_menu_template_lock: settingsState.admin_menu_template_lock,
      faq_task_timeout_minutes: settingsState.faq_task_timeout_minutes,
    }).catch(() => {
      ElMessage.error('模板锁定开关同步系统设置失败，已回退')
      adminTemplateLockEnabled.value = !enabled
      settingsState.admin_menu_template_lock = !enabled
    })
  }
  if (!enabled) return
  if (createForm.role === 'admin' && dialogFaqTemplate) {
    createForm.menu_permissions = [...dialogFaqTemplate.menuKeys]
    createMenuTemplate.value = DIALOG_FAQ_TEMPLATE_KEY
  }
})

watch(
  () => createForm.role,
  (role) => {
    if (role === 'admin' && adminTemplateLockEnabled.value && dialogFaqTemplate) {
      createForm.menu_permissions = [...dialogFaqTemplate.menuKeys]
      createMenuTemplate.value = DIALOG_FAQ_TEMPLATE_KEY
    }
  },
)

onBeforeUnmount(() => {
  triggerFilterSearch.cancel()
  window.removeEventListener('resize', updateViewport)
})

watch(
  [() => pager.keyword, () => pager.role, () => pager.hospital_id, () => pager.department_id],
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
        <strong class="admin-card-title">用户管理</strong>
      </div>
    </template>

    <div class="admin-toolbar user-toolbar">
      <div class="user-toolbar-filters">
        <el-input v-model="pager.keyword" class="admin-control-w-xl" placeholder="搜索姓名/用户名" clearable />
        <el-select v-model="pager.role" class="admin-control-w-xs" clearable placeholder="角色">
          <el-option label="咨询员" value="student" />
          <el-option label="管理员" value="admin" />
          <el-option label="超级管理员" value="super_admin" />
        </el-select>
        <el-select
          v-model="pager.hospital_id"
          :disabled="!isSuperAdmin"
          clearable
          placeholder="所属医院"
          class="admin-control-w-lg"
          @change="onPagerHospitalChange"
        >
          <el-option v-for="h in hospitals" :key="h.id" :label="h.name" :value="h.id" />
        </el-select>
        <el-select
          v-model="pager.department_id"
          :disabled="!isSuperAdmin"
          clearable
          placeholder="所属科室"
          class="admin-control-w-lg"
        >
          <el-option
            v-for="d in departmentOptionsByHospital(pager.hospital_id)"
            :key="d.id"
            :label="d.name"
            :value="d.id"
          />
        </el-select>
        <el-button type="primary" @click="onSearch">查询</el-button>
      </div>
      <div class="user-toolbar-actions">
        <el-button @click="openCreateDrawer">新增用户</el-button>
        <el-button @click="openImportDrawer">批量新增导入</el-button>
        <el-tooltip
          v-if="isSuperAdmin"
          content="开启后：新增管理员默认套用“对话+FAQ”模板，且创建页不可改菜单权限"
          placement="top"
        >
          <el-switch
            v-model="adminTemplateLockEnabled"
            inline-prompt
            active-text="模板锁定"
            inactive-text="模板可改"
          />
        </el-tooltip>
        <el-button
          v-if="isSuperAdmin"
          type="success"
          :disabled="!selectedIds.length"
          :loading="submitting"
          @click="applyDialogFaqTemplateQuick"
        >
          一键套用：对话+FAQ
        </el-button>
        <el-button
          v-if="isSuperAdmin"
          type="warning"
          plain
          :disabled="!selectedIds.length"
          @click="openBulkMenuDrawer"
        >
          批量菜单权限
        </el-button>
        <el-button type="danger" plain :disabled="!selectedIds.length" @click="setUsersActive(selectedIds, false)">
          批量禁用
        </el-button>
        <el-button type="success" plain :disabled="!selectedIds.length" @click="setUsersActive(selectedIds, true)">
          批量启用
        </el-button>
      </div>
    </div>
    <div v-if="latestBatchSummary" class="batch-summary-bar">
      <el-tag type="info">操作 {{ latestBatchSummary.action }}</el-tag>
      <el-tag type="info">总计 {{ latestBatchSummary.total }}</el-tag>
      <el-tag type="success">成功 {{ latestBatchSummary.success }}</el-tag>
      <el-tag type="warning">跳过 {{ latestBatchSummary.skipped }}</el-tag>
      <el-tag v-if="latestBatchSummary.failed > 0" type="danger">失败 {{ latestBatchSummary.failed }}</el-tag>
      <el-tag>时间 {{ latestBatchSummary.time }}</el-tag>
    </div>

    <AdminTableSkeleton v-if="!isMobile && loading" :is-mobile="false" :rows="8" />
    <el-table v-else-if="!isMobile" class="admin-list-table" :data="rows" border stripe @selection-change="onSelectionChange">
      <el-table-column type="selection" width="44" />
      <el-table-column prop="id" label="编号" width="70" />
      <el-table-column prop="username" label="用户名" width="130" />
      <el-table-column prop="real_name" label="姓名" width="120" />
      <el-table-column label="角色" width="120">
        <template #default="{ row }">{{ roleText(row.role) }}</template>
      </el-table-column>
      <el-table-column label="所属医院/科室" min-width="260">
        <template #default="{ row }">{{ resolveScope(row) }}</template>
      </el-table-column>
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag size="small" class="status-tag" :type="row.is_active ? 'success' : 'danger'">
            {{ statusText(row.is_active) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="260">
        <template #default="{ row }">
          <el-button link type="primary" @click="openEditDrawer(row)">修改</el-button>
          <el-button link type="warning" @click="resetPassword(row)">重置密码</el-button>
          <el-button v-if="row.is_active" link type="danger" @click="removeSingle(row)">禁用</el-button>
          <el-button v-else link type="success" @click="enableSingle(row)">启用</el-button>
        </template>
      </el-table-column>
    </el-table>

    <div v-else class="mobile-list">
      <AdminTableSkeleton v-if="loading" :is-mobile="true" :mobile-rows="4" />
      <el-empty v-else-if="!rows.length" class="admin-empty" description="暂无用户数据" />
      <template v-else>
        <el-card v-for="row in rows" :key="row.id" class="mobile-item" shadow="never">
          <div class="mobile-head">
            <el-checkbox
              :model-value="selectedIds.includes(row.id)"
              @change="(v:boolean)=>toggleMobileSelection(row.id, v)"
            />
            <strong>{{ row.real_name }}</strong>
            <el-tag size="small" class="status-tag" :type="row.is_active ? 'success' : 'danger'">
              {{ statusText(row.is_active) }}
            </el-tag>
          </div>
          <div class="meta">用户名：{{ row.username }}</div>
          <div class="meta">角色：{{ roleText(row.role) }}</div>
          <div class="meta">范围：{{ resolveScope(row) }}</div>
          <div class="mobile-actions">
            <el-button link type="primary" @click="openEditDrawer(row)">修改</el-button>
            <el-button link type="warning" @click="resetPassword(row)">重置密码</el-button>
            <el-button v-if="row.is_active" link type="danger" @click="removeSingle(row)">禁用</el-button>
            <el-button v-else link type="success" @click="enableSingle(row)">启用</el-button>
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
      v-model="createDrawerVisible"
      class="admin-smooth-drawer"
      :size="getDrawerSize(isMobile, DRAWER_DESKTOP_SIZE.form)"
      direction="rtl"
      :with-header="false"
    >
      <div class="drawer-body admin-drawer-body">
        <div class="drawer-title admin-drawer-header">
          <strong>新增用户</strong>
          <el-button link type="primary" @click="createDrawerVisible = false">{{ UI_TEXT.close }}</el-button>
        </div>
        <el-form label-width="90px">
          <el-form-item label="用户名"><el-input v-model="createForm.username" /></el-form-item>
          <el-form-item label="密码"><el-input v-model="createForm.password" type="password" show-password /></el-form-item>
          <el-form-item label="姓名"><el-input v-model="createForm.real_name" /></el-form-item>
          <el-form-item label="角色">
            <el-select v-model="createForm.role" style="width: 100%">
              <el-option label="咨询员" value="student" />
              <el-option label="管理员" value="admin" />
              <el-option v-if="isSuperAdmin" label="超级管理员" value="super_admin" />
            </el-select>
          </el-form-item>
          <el-form-item label="所属医院">
            <el-select
              v-model="createForm.hospital_id"
              :disabled="!isSuperAdmin || (createForm.role === 'admin' && createForm.is_all_hospitals)"
              clearable
              style="width: 100%"
              @change="onCreateHospitalChange"
            >
              <el-option v-for="h in hospitals" :key="h.id" :label="h.name" :value="h.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="所属科室">
            <el-select
              v-model="createForm.department_id"
              :disabled="!isSuperAdmin || (createForm.role === 'admin' && createForm.is_all_hospitals)"
              clearable
              style="width: 100%"
            >
              <el-option v-for="d in departmentOptionsByHospital(createForm.hospital_id)" :key="d.id" :label="d.name" :value="d.id" />
            </el-select>
          </el-form-item>
          <el-form-item v-if="createForm.role === 'admin'" label="负责科室">
            <el-select
              v-model="createForm.department_ids"
              multiple
              collapse-tags
              clearable
              :disabled="!isSuperAdmin || createForm.is_all_hospitals"
              style="width: 100%"
            >
              <el-option
                v-for="d in departmentOptionsByHospital(createForm.hospital_id)"
                :key="d.id"
                :label="departmentLabel(d)"
                :value="d.id"
              />
            </el-select>
          </el-form-item>
          <el-form-item v-if="createForm.role === 'admin'" label="全院权限">
            <el-switch v-model="createForm.is_all_hospitals" :disabled="!isSuperAdmin" />
          </el-form-item>
          <el-form-item v-if="createForm.role === 'admin' && isSuperAdmin" label="菜单权限">
            <div style="width: 100%">
              <el-select
                v-model="createMenuTemplate"
                :disabled="adminTemplateLockEnabled"
                placeholder="选择菜单模板"
                style="width: 100%; margin-bottom: 8px"
                @change="onCreateTemplateChange"
              >
                <el-option
                  v-for="template in menuPermissionTemplates"
                  :key="template.key"
                  :label="template.label"
                  :value="template.key"
                />
                <el-option label="自定义" :value="CUSTOM_TEMPLATE_KEY" />
              </el-select>
              <el-checkbox :model-value="isCreateMenuAll" :disabled="adminTemplateLockEnabled" @change="onCreateMenuSelectAll">全选菜单</el-checkbox>
              <el-checkbox-group
                v-model="createForm.menu_permissions"
                :disabled="adminTemplateLockEnabled"
                style="margin-top: 8px"
                @change="onCreateMenuPermissionsChange"
              >
                <el-checkbox v-for="menu in CONFIGURABLE_MENUS" :key="menu.key" :value="menu.key">
                  {{ menu.label }}
                </el-checkbox>
              </el-checkbox-group>
              <div class="menu-permission-tip">
                {{ adminTemplateLockEnabled ? '已锁定“对话+FAQ”模板（可在上方“模板锁定”开关关闭后修改）。' : '未勾选或全勾选表示拥有全部菜单权限。' }}
              </div>
            </div>
          </el-form-item>
        </el-form>
        <div class="drawer-footer admin-drawer-footer">
          <el-button @click="createDrawerVisible = false">{{ UI_TEXT.cancel }}</el-button>
          <el-button type="primary" :loading="submitting" @click="submitCreate">{{ UI_TEXT.save }}</el-button>
        </div>
      </div>
    </el-drawer>

    <el-drawer
      v-model="editDrawerVisible"
      class="admin-smooth-drawer"
      :size="getDrawerSize(isMobile, DRAWER_DESKTOP_SIZE.form)"
      direction="rtl"
      :with-header="false"
    >
      <div class="drawer-body admin-drawer-body">
        <div class="drawer-title admin-drawer-header">
          <strong>修改用户</strong>
          <el-button link type="primary" @click="editDrawerVisible = false">{{ UI_TEXT.close }}</el-button>
        </div>
        <el-form label-width="90px">
          <el-form-item label="姓名"><el-input v-model="editForm.real_name" /></el-form-item>
          <el-form-item label="角色">
            <el-select v-model="editForm.role" style="width: 100%">
              <el-option label="咨询员" value="student" />
              <el-option label="管理员" value="admin" />
              <el-option v-if="isSuperAdmin" label="超级管理员" value="super_admin" />
            </el-select>
          </el-form-item>
          <el-form-item label="所属医院">
            <el-select
              v-model="editForm.hospital_id"
              :disabled="!isSuperAdmin || (editForm.role === 'admin' && editForm.is_all_hospitals)"
              clearable
              style="width: 100%"
              @change="onEditHospitalChange"
            >
              <el-option v-for="h in hospitals" :key="h.id" :label="h.name" :value="h.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="所属科室">
            <el-select
              v-model="editForm.department_id"
              :disabled="!isSuperAdmin || (editForm.role === 'admin' && editForm.is_all_hospitals)"
              clearable
              style="width: 100%"
            >
              <el-option v-for="d in departmentOptionsByHospital(editForm.hospital_id)" :key="d.id" :label="d.name" :value="d.id" />
            </el-select>
          </el-form-item>
          <el-form-item v-if="editForm.role === 'admin'" label="负责科室">
            <el-select
              v-model="editForm.department_ids"
              multiple
              collapse-tags
              clearable
              :disabled="!isSuperAdmin || editForm.is_all_hospitals"
              style="width: 100%"
            >
              <el-option
                v-for="d in departmentOptionsByHospital(editForm.hospital_id)"
                :key="d.id"
                :label="departmentLabel(d)"
                :value="d.id"
              />
            </el-select>
          </el-form-item>
          <el-form-item v-if="editForm.role === 'admin'" label="全院权限">
            <el-switch v-model="editForm.is_all_hospitals" :disabled="!isSuperAdmin" />
          </el-form-item>
          <el-form-item v-if="editForm.role === 'admin' && isSuperAdmin" label="菜单权限">
            <div style="width: 100%">
              <el-select
                v-model="editMenuTemplate"
                :disabled="!canEditTargetMenuPermissions"
                placeholder="选择菜单模板"
                style="width: 100%; margin-bottom: 8px"
                @change="onEditTemplateChange"
              >
                <el-option
                  v-for="template in menuPermissionTemplates"
                  :key="template.key"
                  :label="template.label"
                  :value="template.key"
                />
                <el-option label="自定义" :value="CUSTOM_TEMPLATE_KEY" />
              </el-select>
              <el-checkbox
                :model-value="isEditMenuAll"
                :disabled="!canEditTargetMenuPermissions"
                @change="onEditMenuSelectAll"
              >
                全选菜单
              </el-checkbox>
              <el-checkbox-group
                v-model="editForm.menu_permissions"
                :disabled="!canEditTargetMenuPermissions"
                style="margin-top: 8px"
                @change="onEditMenuPermissionsChange"
              >
                <el-checkbox v-for="menu in CONFIGURABLE_MENUS" :key="menu.key" :value="menu.key">
                  {{ menu.label }}
                </el-checkbox>
              </el-checkbox-group>
              <div class="menu-permission-tip">
                {{ canEditTargetMenuPermissions ? '未勾选或全勾选表示拥有全部菜单权限。' : '不支持修改自己的菜单权限。' }}
              </div>
            </div>
          </el-form-item>
          <el-form-item label="新密码">
            <el-input v-model="editForm.password" type="password" placeholder="不改请留空" show-password />
          </el-form-item>
        </el-form>
        <div class="drawer-footer admin-drawer-footer">
          <el-button @click="editDrawerVisible = false">{{ UI_TEXT.cancel }}</el-button>
          <el-button type="primary" :loading="submitting" @click="submitEdit">{{ UI_TEXT.save }}</el-button>
        </div>
      </div>
    </el-drawer>

    <el-drawer
      v-model="bulkMenuDrawerVisible"
      class="admin-smooth-drawer"
      :size="getDrawerSize(isMobile, DRAWER_DESKTOP_SIZE.form)"
      direction="rtl"
      :with-header="false"
    >
      <div class="drawer-body admin-drawer-body">
        <div class="drawer-title admin-drawer-header">
          <strong>批量菜单权限</strong>
          <el-button link type="primary" @click="bulkMenuDrawerVisible = false">{{ UI_TEXT.close }}</el-button>
        </div>
        <el-form label-width="90px">
          <el-form-item label="已选用户">
            <el-tag type="info">{{ selectedIds.length }} 人</el-tag>
          </el-form-item>
          <el-form-item label="菜单模板">
            <el-select
              v-model="bulkMenuTemplate"
              placeholder="选择菜单模板"
              style="width: 100%"
              @change="onBulkTemplateChange"
            >
              <el-option
                v-for="template in menuPermissionTemplates"
                :key="template.key"
                :label="template.label"
                :value="template.key"
              />
              <el-option label="自定义" :value="CUSTOM_TEMPLATE_KEY" />
            </el-select>
          </el-form-item>
          <el-form-item label="菜单权限">
            <div style="width: 100%">
              <el-checkbox :model-value="isBulkMenuAll" @change="onBulkMenuSelectAll">全选菜单</el-checkbox>
              <el-checkbox-group
                v-model="bulkMenuForm.menu_permissions"
                style="margin-top: 8px"
                @change="onBulkMenuPermissionsChange"
              >
                <el-checkbox v-for="menu in CONFIGURABLE_MENUS" :key="menu.key" :value="menu.key">
                  {{ menu.label }}
                </el-checkbox>
              </el-checkbox-group>
              <div class="menu-permission-tip">未勾选或全勾选表示拥有全部菜单权限。</div>
            </div>
          </el-form-item>
        </el-form>
        <div class="drawer-footer admin-drawer-footer">
          <el-button @click="bulkMenuDrawerVisible = false">{{ UI_TEXT.cancel }}</el-button>
          <el-button type="primary" :loading="submitting" @click="submitBulkMenuPermissions">
            {{ UI_TEXT.save }}
          </el-button>
        </div>
      </div>
    </el-drawer>

    <el-drawer
      v-model="importDrawerVisible"
      class="admin-smooth-drawer"
      :size="getDrawerSize(isMobile, DRAWER_DESKTOP_SIZE.assign)"
      direction="rtl"
      :with-header="false"
    >
      <div class="drawer-body admin-drawer-body">
        <div class="drawer-title admin-drawer-header">
          <strong>批量新增导入</strong>
          <el-button link type="primary" @click="importDrawerVisible = false">{{ UI_TEXT.close }}</el-button>
        </div>
        <el-form label-width="95px">
          <el-form-item label="角色">
            <el-select v-model="importForm.role" style="width: 100%">
              <el-option label="咨询员" value="student" />
              <el-option v-if="isSuperAdmin" label="管理员" value="admin" />
            </el-select>
          </el-form-item>
          <el-form-item label="所属医院">
            <el-select
              v-model="importForm.hospital_id"
              :disabled="!isSuperAdmin"
              clearable
              style="width: 100%"
              @change="onImportHospitalChange"
            >
              <el-option v-for="h in hospitals" :key="h.id" :label="h.name" :value="h.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="所属科室">
            <el-select v-model="importForm.department_id" :disabled="!isSuperAdmin" clearable style="width: 100%">
              <el-option v-for="d in departmentOptionsByHospital(importForm.hospital_id)" :key="d.id" :label="d.name" :value="d.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="默认密码"><el-input v-model="importForm.default_password" /></el-form-item>
          <el-form-item label="导入内容">
            <el-input
              v-model="importForm.text"
              type="textarea"
              :rows="8"
              placeholder="每行一条：用户名,姓名&#10;例如：student02,张三"
            />
          </el-form-item>
        </el-form>
        <div v-if="importResult" class="import-result">
          <el-tag type="info">总计 {{ importResult.total }}</el-tag>
          <el-tag type="success">成功 {{ importResult.created }}</el-tag>
          <el-tag type="warning">跳过 {{ importResult.skipped }}</el-tag>
          <el-button
            type="warning"
            plain
            :disabled="!importResult.failed_items?.length"
            @click="exportImportFailedItems"
          >
            导出失败清单
          </el-button>
        </div>
        <el-alert
          v-if="importResult?.errors?.length"
          type="warning"
          :closable="false"
          show-icon
          style="margin-top: 10px"
        >
          <template #title>
            导入提示：{{ importResult.errors.slice(0, 3).join('；') }}{{ importResult.errors.length > 3 ? '……' : '' }}
          </template>
        </el-alert>
        <div class="drawer-footer admin-drawer-footer">
          <el-button @click="importDrawerVisible = false">{{ UI_TEXT.cancel }}</el-button>
          <el-button type="primary" :loading="submitting" @click="submitBulkImport">执行导入</el-button>
        </div>
      </div>
    </el-drawer>
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

.mobile-head {
  display: flex;
  align-items: center;
  gap: 8px;
}

.meta {
  margin-top: 6px;
  font-size: var(--font-size-sm);
  color: var(--el-text-color-secondary);
}

.mobile-actions {
  margin-top: 8px;
  display: flex;
  gap: 8px;
  justify-content: flex-end;
}

.menu-permission-tip {
  margin-top: 6px;
  color: var(--el-text-color-secondary);
  font-size: var(--font-size-xs);
}

.import-result {
  margin-top: 8px;
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}

.batch-summary-bar {
  margin-bottom: var(--space-3);
  display: flex;
  gap: var(--space-2);
  align-items: center;
  flex-wrap: wrap;
}

.user-toolbar {
  align-items: center;
  justify-content: space-between;
  flex-wrap: nowrap;
}

.user-toolbar-filters {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: nowrap;
  min-width: 0;
  overflow-x: auto;
  padding-bottom: 2px;
}

.user-toolbar-actions {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
  flex-wrap: nowrap;
  overflow-x: auto;
  padding-bottom: 2px;
}

@media (max-width: 768px) {
  .user-toolbar {
    flex-wrap: wrap;
    align-items: stretch;
  }

  .user-toolbar-filters {
    width: 100%;
    flex-wrap: wrap;
    overflow-x: visible;
  }

  .user-toolbar-filters :deep(.el-select),
  .user-toolbar-filters :deep(.el-input) {
    width: 100% !important;
  }

  .user-toolbar-actions {
    width: 100%;
    flex-wrap: wrap;
    overflow-x: visible;
    justify-content: flex-start;
  }
}
</style>
