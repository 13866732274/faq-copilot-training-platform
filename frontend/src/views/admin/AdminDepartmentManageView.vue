<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useRoute } from 'vue-router'
import {
  assignUsersToDepartment,
  createDepartment,
  getDepartments,
  toggleDepartment,
  updateDepartment,
  type DepartmentItem,
} from '../../api/department'
import { getHospitals, type HospitalItem } from '../../api/hospital'
import { getUsers, type UserItem } from '../../api/users'
import { useUserStore } from '../../stores/user'
import {
  DRAWER_DESKTOP_SIZE,
  UI_TEXT,
  confirmDangerousAction,
  createDebouncedFn,
  getDrawerSize,
} from '../../composables/useUiStandards'
import AdminTableSkeleton from '../../components/admin/AdminTableSkeleton.vue'

const route = useRoute()
const userStore = useUserStore()
const isSuperAdmin = ref(userStore.user?.role === 'super_admin')
const loading = ref(false)
const rows = ref<DepartmentItem[]>([])
const hospitals = ref<HospitalItem[]>([])
const isMobile = ref(false)
const createDrawerVisible = ref(false)
const editDrawerVisible = ref(false)
const assignDrawerVisible = ref(false)
const createForm = reactive({
  hospital_id: undefined as number | undefined,
  name: '',
})
const editForm = reactive({
  id: 0,
  hospital_id: undefined as number | undefined,
  name: '',
  is_active: true,
})
const filterHospitalId = ref<number | undefined>(undefined)
const assignDepartment = ref<DepartmentItem | null>(null)
const assignMode = ref<'append' | 'replace'>('append')
const assignUserIds = ref<number[]>([])
const userOptions = ref<UserItem[]>([])
const assignRole = ref<'all' | 'student' | 'admin'>('all')
const assignLoading = ref(false)
const hideAssignedUsers = ref(true)

const assignCandidates = computed(() => {
  const departmentId = assignDepartment.value?.id
  let filtered = assignRole.value === 'all' ? userOptions.value : userOptions.value.filter((u) => u.role === assignRole.value)
  if (hideAssignedUsers.value && departmentId) {
    filtered = filtered.filter((u) => !u.department_ids?.includes(departmentId))
  }
  // 运营优先选择“未在本科室”的人，因此默认前置；同组内再按姓名排序
  return [...filtered].sort((a, b) => {
    const aIn = departmentId ? Boolean(a.department_ids?.includes(departmentId)) : false
    const bIn = departmentId ? Boolean(b.department_ids?.includes(departmentId)) : false
    if (aIn !== bIn) return aIn ? 1 : -1
    const aName = (a.real_name || a.username || '').trim()
    const bName = (b.real_name || b.username || '').trim()
    return aName.localeCompare(bName, 'zh-Hans-CN')
  })
})

const assignGuideText = computed(() => {
  if (!assignDepartment.value) return ''
  return `当前科室：${assignDepartment.value.name}。请按“分配方式 → 角色筛选 → 选择用户”的顺序操作。`
})

const assignAvailableCount = computed(() => assignCandidates.value.length)
const assignSelectedCount = computed(() => assignUserIds.value.length)
const currentAssignedUserIds = computed(() => {
  const departmentId = assignDepartment.value?.id
  if (!departmentId) return []
  return userOptions.value.filter((u) => u.department_ids?.includes(departmentId)).map((u) => u.id)
})
const currentAssignedCount = computed(() => currentAssignedUserIds.value.length)
const selectedAlreadyInCount = computed(() => {
  const assigned = new Set(currentAssignedUserIds.value)
  return assignUserIds.value.filter((id) => assigned.has(id)).length
})
const selectedNewCount = computed(() => Math.max(0, assignUserIds.value.length - selectedAlreadyInCount.value))
const replaceRemoveCount = computed(() => Math.max(0, currentAssignedCount.value - selectedAlreadyInCount.value))
const replaceAfterCount = computed(() => assignUserIds.value.length)
const appendAfterCount = computed(() => currentAssignedCount.value + selectedNewCount.value)
const assignPreviewText = computed(() => {
  if (assignMode.value === 'replace') {
    return `替换后本科室预计保留/设置 ${replaceAfterCount.value} 人，其中新增 ${selectedNewCount.value} 人，移除 ${replaceRemoveCount.value} 人。`
  }
  return `追加后本科室预计共 ${appendAfterCount.value} 人，本次新增 ${selectedNewCount.value} 人，已在本科室 ${selectedAlreadyInCount.value} 人不变。`
})

const hospitalNameMap = computed(() => {
  const map: Record<number, string> = {}
  for (const h of hospitals.value) map[h.id] = h.name
  return map
})

const loadHospitals = async () => {
  try {
    hospitals.value = await getHospitals({ active_only: true })
  } catch {
    hospitals.value = []
  }
}

const load = async () => {
  loading.value = true
  try {
    rows.value = await getDepartments({
      hospital_id: filterHospitalId.value,
    })
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || '获取科室列表失败')
  } finally {
    loading.value = false
  }
}

const onCreate = async () => {
  if (!createForm.hospital_id) {
    ElMessage.warning('请选择所属医院')
    return
  }
  if (!createForm.name.trim()) {
    ElMessage.warning('请填写科室名称')
    return
  }
  try {
    await createDepartment({ hospital_id: createForm.hospital_id, name: createForm.name.trim() })
    ElMessage.success('科室创建成功，已自动生成内部编码')
    createDrawerVisible.value = false
    createForm.name = ''
    await load()
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || '创建科室失败')
  }
}

const openEdit = (row: DepartmentItem) => {
  editForm.id = row.id
  editForm.hospital_id = row.hospital_id
  editForm.name = row.name
  editForm.is_active = row.is_active
  editDrawerVisible.value = true
}

const onEditSubmit = async () => {
  try {
    await updateDepartment(editForm.id, {
      name: editForm.name.trim(),
      is_active: editForm.is_active,
    })
    ElMessage.success('科室信息更新成功')
    editDrawerVisible.value = false
    await load()
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || '更新科室失败')
  }
}

const onToggle = async (row: DepartmentItem) => {
  try {
    await confirmDangerousAction(
      `确认${row.is_active ? '停用' : '启用'}科室“${row.name}”吗？`,
      `${row.is_active ? '停用' : '启用'}科室确认`,
    )
    await toggleDepartment(row.id)
    ElMessage.success('状态已切换')
    await load()
  } catch (error: any) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(error?.response?.data?.detail || '切换状态失败')
  }
}

const loadAssignableUsers = async (hospitalId: number) => {
  const pageSize = 200
  let page = 1
  let total = 0
  const merged: UserItem[] = []
  do {
    const res = await getUsers({
      page,
      page_size: pageSize,
      hospital_id: hospitalId,
    })
    total = res.total || 0
    merged.push(...res.items)
    page += 1
  } while (merged.length < total && page <= 20)
  return merged
}

const openAssign = async (row: DepartmentItem) => {
  assignDepartment.value = row
  assignMode.value = 'append'
  assignRole.value = 'all'
  hideAssignedUsers.value = true
  assignUserIds.value = []
  assignDrawerVisible.value = true
  assignLoading.value = true
  try {
    const items = await loadAssignableUsers(row.hospital_id)
    userOptions.value = items.filter((u) => u.role === 'admin' || u.role === 'student')
  } catch {
    userOptions.value = []
  } finally {
    assignLoading.value = false
  }
}

const onSelectAllCandidates = () => {
  assignUserIds.value = assignCandidates.value.map((u) => u.id)
}

const onClearSelectedUsers = () => {
  assignUserIds.value = []
}

const onAssignSubmit = async () => {
  if (!assignDepartment.value) return
  if (!assignUserIds.value.length) {
    ElMessage.warning('请先选择要分配的用户')
    return
  }
  try {
    const tip =
      assignMode.value === 'replace'
        ? `确认以“替换”方式分配吗？${assignPreviewText.value}`
        : `确认向科室“${assignDepartment.value.name}”追加分配吗？${assignPreviewText.value}`
    await confirmDangerousAction(tip, '分配用户确认')
    await assignUsersToDepartment(assignDepartment.value.id, {
      user_ids: assignUserIds.value,
      mode: assignMode.value,
    })
    ElMessage.success('用户分配成功')
    assignDrawerVisible.value = false
  } catch (error: any) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(error?.response?.data?.detail || '分配失败')
  }
}

const openCreate = () => {
  if (isSuperAdmin.value && filterHospitalId.value) {
    createForm.hospital_id = filterHospitalId.value
  }
  createForm.name = ''
  createDrawerVisible.value = true
}

const onFilter = () => {
  triggerFilter.cancel()
  load()
}

const triggerFilter = createDebouncedFn(() => {
  load()
}, 260)

const updateViewport = () => {
  isMobile.value = window.innerWidth < 992
}

onMounted(() => {
  updateViewport()
  window.addEventListener('resize', updateViewport)
  isSuperAdmin.value = userStore.user?.role === 'super_admin'
  const fromQuery = Number(route.query.hospital_id || 0)
  if (fromQuery) filterHospitalId.value = fromQuery
  if (!isSuperAdmin.value) {
    filterHospitalId.value = userStore.user?.hospital_id || filterHospitalId.value
    createForm.hospital_id = userStore.user?.hospital_id || undefined
  } else if (filterHospitalId.value) {
    createForm.hospital_id = filterHospitalId.value
  }
  loadHospitals().then(load)
})

onBeforeUnmount(() => {
  triggerFilter.cancel()
  window.removeEventListener('resize', updateViewport)
})

watch(filterHospitalId, () => {
  triggerFilter()
})
</script>

<template>
  <el-card shadow="never">
    <template #header>
      <div class="admin-card-header">
        <strong class="admin-card-title">科室管理</strong>
      </div>
    </template>

    <el-alert
      v-if="!isSuperAdmin"
      type="info"
      :closable="false"
      show-icon
      style="margin-bottom: 12px"
      title="当前为医院管理员视角，仅可查看本院科室。"
    />

    <div class="toolbar admin-toolbar department-toolbar">
      <el-select
        v-model="filterHospitalId"
        class="admin-control-w-2xl"
        :disabled="!isSuperAdmin"
        clearable
        placeholder="按医院筛选"
      >
        <el-option v-for="h in hospitals" :key="h.id" :label="h.name" :value="h.id" />
      </el-select>
      <div class="toolbar-actions">
        <el-button @click="onFilter">刷新</el-button>
        <el-button v-if="isSuperAdmin" type="primary" @click="openCreate">新增科室</el-button>
      </div>
    </div>

    <AdminTableSkeleton v-if="loading" :is-mobile="isMobile" :rows="8" :mobile-rows="4" />
    <el-table v-else-if="!isMobile" class="admin-list-table" :data="rows" border stripe>
      <el-table-column prop="id" label="编号" width="80" />
      <el-table-column label="所属医院" min-width="180">
        <template #default="{ row }">{{ row.hospital_name || hospitalNameMap[row.hospital_id] || '-' }}</template>
      </el-table-column>
      <el-table-column prop="name" label="科室名称" min-width="180" />
      <el-table-column label="状态" width="120">
        <template #default="{ row }">
          <el-tag :type="row.is_active ? 'success' : 'danger'">
            {{ row.is_active ? '启用' : '停用' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="created_at" label="创建时间" width="180" />
      <el-table-column v-if="isSuperAdmin" label="操作" width="250">
        <template #default="{ row }">
          <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
          <el-button link type="success" @click="openAssign(row)">分配用户</el-button>
          <el-button link type="warning" @click="onToggle(row)">
            {{ row.is_active ? '停用' : '启用' }}
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <div v-else class="admin-mobile-list">
      <el-empty v-if="!rows.length" class="admin-empty" description="暂无科室数据" />
      <template v-else>
        <el-card v-for="row in rows" :key="row.id" class="admin-mobile-item" shadow="never">
          <div class="admin-mobile-title-row">
            <strong>{{ row.name }}</strong>
            <el-tag size="small" :type="row.is_active ? 'success' : 'danger'">
              {{ row.is_active ? '启用' : '停用' }}
            </el-tag>
          </div>
          <div class="admin-mobile-meta">所属医院：{{ row.hospital_name || hospitalNameMap[row.hospital_id] || '-' }}</div>
          <div class="admin-mobile-meta">创建：{{ row.created_at }}</div>
          <div v-if="isSuperAdmin" class="admin-mobile-actions">
            <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
            <el-button link type="success" @click="openAssign(row)">分配用户</el-button>
            <el-button link type="warning" @click="onToggle(row)">
              {{ row.is_active ? '停用' : '启用' }}
            </el-button>
          </div>
        </el-card>
      </template>
    </div>

    <el-drawer
      v-model="createDrawerVisible"
      class="admin-smooth-drawer"
      :size="getDrawerSize(isMobile, DRAWER_DESKTOP_SIZE.compact)"
      direction="rtl"
      :with-header="false"
    >
      <div class="drawer-body admin-drawer-body">
        <div class="drawer-title admin-drawer-header">
          <strong>新增科室</strong>
          <el-button link type="primary" @click="createDrawerVisible = false">{{ UI_TEXT.close }}</el-button>
        </div>
        <el-form label-width="90px">
          <el-form-item label="所属医院">
            <el-select v-model="createForm.hospital_id" clearable placeholder="所属医院" style="width: 100%">
              <el-option v-for="h in hospitals" :key="h.id" :label="h.name" :value="h.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="科室名称">
            <el-input v-model="createForm.name" />
          </el-form-item>
        </el-form>
        <div class="drawer-footer admin-drawer-footer">
          <el-button @click="createDrawerVisible = false">{{ UI_TEXT.cancel }}</el-button>
          <el-button type="primary" @click="onCreate">{{ UI_TEXT.save }}</el-button>
        </div>
      </div>
    </el-drawer>

    <el-drawer
      v-model="editDrawerVisible"
      class="admin-smooth-drawer"
      :size="getDrawerSize(isMobile, DRAWER_DESKTOP_SIZE.compact)"
      direction="rtl"
      :with-header="false"
    >
      <div class="drawer-body admin-drawer-body">
        <div class="drawer-title admin-drawer-header">
          <strong>编辑科室</strong>
          <el-button link type="primary" @click="editDrawerVisible = false">{{ UI_TEXT.close }}</el-button>
        </div>
        <el-form label-width="90px">
          <el-form-item label="所属医院">
            <el-input :model-value="hospitalNameMap[editForm.hospital_id || 0] || '-'" disabled />
          </el-form-item>
          <el-form-item label="科室名称">
            <el-input v-model="editForm.name" />
          </el-form-item>
          <el-form-item label="状态">
            <el-switch v-model="editForm.is_active" />
          </el-form-item>
        </el-form>
        <div class="drawer-footer admin-drawer-footer">
          <el-button @click="editDrawerVisible = false">{{ UI_TEXT.cancel }}</el-button>
          <el-button type="primary" @click="onEditSubmit">{{ UI_TEXT.save }}</el-button>
        </div>
      </div>
    </el-drawer>

    <el-drawer
      v-model="assignDrawerVisible"
      class="admin-smooth-drawer"
      :size="getDrawerSize(isMobile, DRAWER_DESKTOP_SIZE.assign)"
      direction="rtl"
      :with-header="false"
    >
      <div class="drawer-body admin-drawer-body">
        <div class="drawer-title admin-drawer-header">
          <strong>分配用户 - {{ assignDepartment?.name || '' }}</strong>
          <el-button link type="primary" @click="assignDrawerVisible = false">{{ UI_TEXT.close }}</el-button>
        </div>
        <el-alert
          :closable="false"
          type="info"
          show-icon
          style="margin-bottom: 10px"
          :title="assignGuideText"
        />
        <el-form label-width="90px">
          <el-form-item label="分配方式">
            <el-radio-group v-model="assignMode">
              <el-radio-button label="append">追加</el-radio-button>
              <el-radio-button label="replace">替换</el-radio-button>
            </el-radio-group>
          </el-form-item>
          <el-form-item label="角色筛选">
            <el-radio-group v-model="assignRole">
              <el-radio-button label="all">全部</el-radio-button>
              <el-radio-button label="student">仅咨询员</el-radio-button>
              <el-radio-button label="admin">仅管理员</el-radio-button>
            </el-radio-group>
          </el-form-item>
          <el-form-item label="显示策略">
            <el-switch v-model="hideAssignedUsers" active-text="隐藏已在本科室用户" inactive-text="显示全部用户" />
          </el-form-item>
          <el-form-item label="候选统计">
            <div class="assign-summary">
              <span>当前已分配 {{ currentAssignedCount }} 人</span>
              <span>可选 {{ assignAvailableCount }} 人</span>
              <span>已选 {{ assignSelectedCount }} 人</span>
              <el-button text type="primary" :disabled="!assignAvailableCount" @click="onSelectAllCandidates">
                全选当前结果
              </el-button>
              <el-button text :disabled="!assignSelectedCount" @click="onClearSelectedUsers">清空已选</el-button>
            </div>
          </el-form-item>
          <el-form-item label="变更预览">
            <el-alert
              :closable="false"
              :type="assignMode === 'replace' ? 'warning' : 'success'"
              show-icon
              :title="assignPreviewText"
            />
          </el-form-item>
          <el-form-item label="选择用户">
            <el-select
              v-model="assignUserIds"
              multiple
              clearable
              filterable
              :loading="assignLoading"
              :disabled="assignLoading"
              no-data-text="暂无可选用户（请先确认该医院下已有咨询员/管理员）"
              placeholder="可搜索：姓名 / 用户名"
              style="width: 100%"
            >
              <el-option
                v-for="u in assignCandidates"
                :key="u.id"
                :label="`${u.real_name}（${u.username}） - ${u.role === 'student' ? '咨询员' : '管理员'}${u.department_ids?.includes(assignDepartment?.id || -1) ? '（已在本科室）' : ''}`"
                :value="u.id"
              />
            </el-select>
          </el-form-item>
        </el-form>
        <div class="drawer-footer admin-drawer-footer">
          <el-button @click="assignDrawerVisible = false">{{ UI_TEXT.cancel }}</el-button>
          <el-button type="primary" @click="onAssignSubmit">确定分配</el-button>
        </div>
      </div>
    </el-drawer>
  </el-card>
</template>

<style scoped>
.toolbar {
  margin-bottom: 10px;
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.department-toolbar {
  align-items: center;
  justify-content: space-between;
  flex-wrap: nowrap;
}

.toolbar-actions {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.assign-summary {
  width: 100%;
  display: flex;
  gap: var(--space-3);
  align-items: center;
  flex-wrap: wrap;
  color: var(--el-text-color-secondary);
  font-size: var(--font-size-sm);
}

@media (max-width: 768px) {
  .department-toolbar {
    flex-wrap: wrap;
    align-items: stretch;
  }

  .department-toolbar :deep(.el-select) {
    width: 100% !important;
  }

  .toolbar-actions {
    width: 100%;
    justify-content: flex-start;
  }
}

</style>
