<script setup lang="ts">
import { onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  createHospital,
  getHospitals,
  toggleHospital,
  updateHospital,
  type HospitalItem,
} from '../../api/hospital'
import { getDepartments } from '../../api/department'
import { useUserStore } from '../../stores/user'
import { useRouter } from 'vue-router'
import { DRAWER_DESKTOP_SIZE, UI_TEXT, confirmDangerousAction, getDrawerSize } from '../../composables/useUiStandards'
import AdminTableSkeleton from '../../components/admin/AdminTableSkeleton.vue'

const router = useRouter()
const userStore = useUserStore()
const isSuperAdmin = ref(userStore.user?.role === 'super_admin')
const loading = ref(false)
const rows = ref<HospitalItem[]>([])
const departmentCountMap = ref<Record<number, number>>({})
const isMobile = ref(false)
const createDrawerVisible = ref(false)
const editDrawerVisible = ref(false)
const createForm = reactive({ name: '', short_name: '' })
const editForm = reactive({ id: 0, name: '', short_name: '', is_active: true })

const toHospitalAlias = (row: HospitalItem) => {
  const value = row.short_name?.trim()
  if (value) return value
  return row.name.replace(/耳鼻咽喉科$/, '')
}

const load = async () => {
  loading.value = true
  try {
    rows.value = await getHospitals()
    const departments = await getDepartments()
    const map: Record<number, number> = {}
    for (const item of departments) {
      map[item.hospital_id] = (map[item.hospital_id] || 0) + 1
    }
    departmentCountMap.value = map
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || '获取医院列表失败')
  } finally {
    loading.value = false
  }
}

const onCreate = async () => {
  if (!createForm.name.trim()) {
    ElMessage.warning('请填写医院名称')
    return
  }
  try {
    await createHospital({
      name: createForm.name.trim(),
      short_name: createForm.short_name.trim() || undefined,
    })
    ElMessage.success('医院创建成功，已自动生成内部编码')
    createDrawerVisible.value = false
    createForm.name = ''
    createForm.short_name = ''
    await load()
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || '创建医院失败')
  }
}

const openEdit = (row: HospitalItem) => {
  editForm.id = row.id
  editForm.name = row.name
  editForm.short_name = row.short_name || ''
  editForm.is_active = row.is_active
  editDrawerVisible.value = true
}

const onEditSubmit = async () => {
  try {
    await updateHospital(editForm.id, {
      name: editForm.name.trim(),
      short_name: editForm.short_name.trim() || undefined,
      is_active: editForm.is_active,
    })
    ElMessage.success('医院信息更新成功')
    editDrawerVisible.value = false
    await load()
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || '更新医院失败')
  }
}

const onToggle = async (row: HospitalItem) => {
  try {
    await confirmDangerousAction(
      `确认${row.is_active ? '停用' : '启用'}医院“${row.name}”吗？`,
      `${row.is_active ? '停用' : '启用'}医院确认`,
    )
    await toggleHospital(row.id)
    ElMessage.success('状态已切换')
    await load()
  } catch (error: any) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(error?.response?.data?.detail || '切换状态失败')
  }
}

const openDepartmentPage = (hospitalId?: number) => {
  if (!hospitalId) {
    router.push('/admin/departments')
    return
  }
  router.push(`/admin/departments?hospital_id=${hospitalId}`)
}

const openCreate = () => {
  createForm.name = ''
  createForm.short_name = ''
  createDrawerVisible.value = true
}

const updateViewport = () => {
  isMobile.value = window.innerWidth < 992
}

onMounted(() => {
  updateViewport()
  window.addEventListener('resize', updateViewport)
  isSuperAdmin.value = userStore.user?.role === 'super_admin'
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
        <strong class="admin-card-title">医院管理</strong>
      </div>
    </template>

    <el-alert
      v-if="!isSuperAdmin"
      type="info"
      :closable="false"
      show-icon
      style="margin-bottom: 12px"
      title="当前为医院管理员视角，仅可查看本院信息。"
    />

    <div v-if="isSuperAdmin && !isMobile" class="create-row">
      <el-button type="primary" @click="openCreate">新增医院</el-button>
    </div>

    <AdminTableSkeleton v-if="loading" :is-mobile="isMobile" :rows="8" :mobile-rows="4" />
    <el-table v-else-if="!isMobile" class="admin-list-table" :data="rows" border stripe>
      <el-table-column prop="id" label="编号" width="80" />
      <el-table-column label="医院简称" width="180">
        <template #default="{ row }">{{ toHospitalAlias(row) }}</template>
      </el-table-column>
      <el-table-column prop="name" label="医院名称" min-width="240" />
      <el-table-column label="状态" width="120">
        <template #default="{ row }">
          <el-tag :type="row.is_active ? 'success' : 'danger'">
            {{ row.is_active ? '启用' : '停用' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="created_at" label="创建时间" width="180" />
      <el-table-column label="科室数" width="100">
        <template #default="{ row }">{{ departmentCountMap[row.id] || 0 }}</template>
      </el-table-column>
      <el-table-column v-if="isSuperAdmin" label="操作" width="260">
        <template #default="{ row }">
          <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
          <el-button link type="success" @click="openDepartmentPage(row.id)">管理科室</el-button>
          <el-button link type="warning" @click="onToggle(row)">
            {{ row.is_active ? '停用' : '启用' }}
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <div v-else class="admin-mobile-list">
      <el-empty v-if="!rows.length" class="admin-empty" description="暂无医院数据" />
      <template v-else>
        <el-card v-for="row in rows" :key="row.id" class="admin-mobile-item" shadow="never">
          <div class="admin-mobile-title-row">
            <strong>{{ row.name }}</strong>
            <el-tag size="small" :type="row.is_active ? 'success' : 'danger'">
              {{ row.is_active ? '启用' : '停用' }}
            </el-tag>
          </div>
          <div class="admin-mobile-meta">医院简称：{{ toHospitalAlias(row) }}</div>
          <div class="admin-mobile-meta">科室数：{{ departmentCountMap[row.id] || 0 }}</div>
          <div class="admin-mobile-meta">创建：{{ row.created_at }}</div>
          <div v-if="isSuperAdmin" class="admin-mobile-actions">
            <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
            <el-button link type="success" @click="openDepartmentPage(row.id)">管理科室</el-button>
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
          <strong>新增医院</strong>
          <el-button link type="primary" @click="createDrawerVisible = false">{{ UI_TEXT.close }}</el-button>
        </div>
        <el-form label-width="90px">
          <el-form-item label="医院名称">
            <el-input v-model="createForm.name" placeholder="请输入医院名称" />
          </el-form-item>
          <el-form-item label="医院简称">
            <el-input v-model="createForm.short_name" placeholder="可选，不填则自动生成" />
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
          <strong>编辑医院</strong>
          <el-button link type="primary" @click="editDrawerVisible = false">{{ UI_TEXT.close }}</el-button>
        </div>
        <el-form label-width="90px">
          <el-form-item label="医院名称">
            <el-input v-model="editForm.name" />
          </el-form-item>
          <el-form-item label="医院简称">
            <el-input v-model="editForm.short_name" placeholder="可独立修改医院简称" />
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

  </el-card>
</template>

<style scoped>
.create-row {
  margin-bottom: var(--space-3);
  display: flex;
  gap: var(--space-2);
  flex-wrap: wrap;
}
</style>
