<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { getHospitals, type HospitalItem } from '../../api/hospital'
import { getDepartments, type DepartmentItem } from '../../api/department'
import { exportPracticesCsv, exportQuizzesCsv, exportUsersCsv } from '../../api/system'
import { useUserStore } from '../../stores/user'
import { evaluatePermissionPoint } from '../../utils/permissionPoints'

const userStore = useUserStore()
const loading = ref(false)
const exporting = ref<'users' | 'practices' | 'quizzes' | ''>('')
const hospitals = ref<HospitalItem[]>([])
const departments = ref<DepartmentItem[]>([])

const form = reactive({
  hospital_id: undefined as number | undefined,
  department_id: undefined as number | undefined,
  role: '',
  practice_status: '',
  quiz_scope: '',
  date_range: [] as string[],
})

const isSuperAdmin = computed(() => userStore.user?.role === 'super_admin')
const usersExportPerm = computed(() => evaluatePermissionPoint('system.export.users'))
const practicesExportPerm = computed(() => evaluatePermissionPoint('system.export.practices'))
const quizzesExportPerm = computed(() => evaluatePermissionPoint('system.export.quizzes'))

const departmentOptions = computed(() => {
  if (!form.hospital_id) return departments.value
  return departments.value.filter((d) => d.hospital_id === form.hospital_id)
})

const baseParams = computed(() => ({
  hospital_id: form.hospital_id,
  department_id: form.department_id,
  start_date: form.date_range?.[0],
  end_date: form.date_range?.[1],
}))

const resetFilters = () => {
  form.hospital_id = undefined
  form.department_id = undefined
  form.role = ''
  form.practice_status = ''
  form.quiz_scope = ''
  form.date_range = []
}

const ensureDeptValid = () => {
  if (!form.department_id) return
  if (!departmentOptions.value.some((d) => d.id === form.department_id)) {
    form.department_id = undefined
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

const nowText = () => new Date().toISOString().slice(0, 19).replace(/[-:T]/g, '')

const doExportUsers = async () => {
  if (!usersExportPerm.value.allowed) {
    ElMessage.warning(usersExportPerm.value.reason)
    return
  }
  exporting.value = 'users'
  try {
    const blob = await exportUsersCsv({
      ...baseParams.value,
      role: form.role || undefined,
    })
    saveBlob(blob, `users-export-${nowText()}.csv`)
    ElMessage.success('用户数据导出成功')
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || '用户数据导出失败')
  } finally {
    exporting.value = ''
  }
}

const doExportPractices = async () => {
  if (!practicesExportPerm.value.allowed) {
    ElMessage.warning(practicesExportPerm.value.reason)
    return
  }
  exporting.value = 'practices'
  try {
    const blob = await exportPracticesCsv({
      ...baseParams.value,
      status: form.practice_status || undefined,
    })
    saveBlob(blob, `practices-export-${nowText()}.csv`)
    ElMessage.success('练习数据导出成功')
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || '练习数据导出失败')
  } finally {
    exporting.value = ''
  }
}

const doExportQuizzes = async () => {
  if (!quizzesExportPerm.value.allowed) {
    ElMessage.warning(quizzesExportPerm.value.reason)
    return
  }
  exporting.value = 'quizzes'
  try {
    const blob = await exportQuizzesCsv({
      ...baseParams.value,
      scope: form.quiz_scope || undefined,
    })
    saveBlob(blob, `quizzes-export-${nowText()}.csv`)
    ElMessage.success('案例库数据导出成功')
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || '案例库数据导出失败')
  } finally {
    exporting.value = ''
  }
}

const loadMeta = async () => {
  loading.value = true
  try {
    const [hList, dList] = await Promise.all([
      getHospitals({ active_only: true }),
      getDepartments({ active_only: true }),
    ])
    hospitals.value = hList
    departments.value = dList
  } catch {
    hospitals.value = []
    departments.value = []
  } finally {
    loading.value = false
  }
}

watch(
  () => form.hospital_id,
  () => ensureDeptValid(),
)

onMounted(() => {
  if (!isSuperAdmin.value) {
    form.hospital_id = userStore.user?.hospital_id || undefined
    form.department_id = userStore.user?.department_id || undefined
  }
  loadMeta()
})
</script>

<template>
  <el-card shadow="never" v-loading="loading">
    <template #header>
      <div class="admin-card-header">
        <strong class="admin-card-title">数据导出中心</strong>
        <div class="admin-card-header-actions">
          <el-button @click="resetFilters">重置筛选</el-button>
        </div>
      </div>
    </template>

    <div class="filter-grid">
      <el-select v-model="form.hospital_id" :disabled="!isSuperAdmin" clearable placeholder="所属医院">
        <el-option v-for="h in hospitals" :key="h.id" :label="h.name" :value="h.id" />
      </el-select>
      <el-select v-model="form.department_id" clearable placeholder="所属科室">
        <el-option v-for="d in departmentOptions" :key="d.id" :label="d.name" :value="d.id" />
      </el-select>
      <el-date-picker
        v-model="form.date_range"
        type="daterange"
        value-format="YYYY-MM-DD"
        start-placeholder="开始日期"
        end-placeholder="结束日期"
        unlink-panels
      />
      <el-select v-model="form.role" clearable placeholder="用户角色（用户导出）">
        <el-option label="超级管理员" value="super_admin" />
        <el-option label="管理员" value="admin" />
        <el-option label="咨询员" value="student" />
      </el-select>
      <el-select v-model="form.practice_status" clearable placeholder="练习状态（练习导出）">
        <el-option label="进行中" value="in_progress" />
        <el-option label="已完成" value="completed" />
      </el-select>
      <el-select v-model="form.quiz_scope" clearable placeholder="案例库范围（案例库导出）">
        <el-option label="通用" value="common" />
        <el-option label="医院" value="hospital" />
        <el-option label="科室" value="department" />
      </el-select>
    </div>

    <div class="export-grid">
      <el-card shadow="never" class="export-card">
        <div class="export-title">用户数据导出</div>
        <div class="export-desc">导出用户账号、角色、状态与组织归属信息（CSV）。</div>
        <el-tooltip :disabled="usersExportPerm.allowed" :content="usersExportPerm.reason" placement="top">
          <span>
            <el-button
              type="primary"
              :loading="exporting === 'users'"
              :disabled="!usersExportPerm.allowed"
              @click="doExportUsers"
            >
              导出用户数据
            </el-button>
          </span>
        </el-tooltip>
      </el-card>

      <el-card shadow="never" class="export-card">
        <div class="export-title">练习数据导出</div>
        <div class="export-desc">导出训练记录、状态、案例、咨询员与时间线信息（CSV）。</div>
        <el-tooltip :disabled="practicesExportPerm.allowed" :content="practicesExportPerm.reason" placement="top">
          <span>
            <el-button
              type="primary"
              :loading="exporting === 'practices'"
              :disabled="!practicesExportPerm.allowed"
              @click="doExportPractices"
            >
              导出练习数据
            </el-button>
          </span>
        </el-tooltip>
      </el-card>

      <el-card shadow="never" class="export-card">
        <div class="export-title">案例库数据导出</div>
        <div class="export-desc">导出案例基础信息、范围、类型、难度与归属（CSV）。</div>
        <el-tooltip :disabled="quizzesExportPerm.allowed" :content="quizzesExportPerm.reason" placement="top">
          <span>
            <el-button
              type="primary"
              :loading="exporting === 'quizzes'"
              :disabled="!quizzesExportPerm.allowed"
              @click="doExportQuizzes"
            >
              导出案例库数据
            </el-button>
          </span>
        </el-tooltip>
      </el-card>
    </div>
  </el-card>
</template>

<style scoped>
.filter-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--space-3);
}

.export-grid {
  margin-top: var(--space-4);
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--space-3);
}

.export-card {
  display: grid;
  gap: var(--space-3);
}

.export-title {
  font-size: var(--font-size-h6);
  font-weight: 700;
}

.export-desc {
  color: var(--el-text-color-secondary);
  font-size: var(--font-size-sm);
  line-height: var(--line-height-base);
}

@media (max-width: 992px) {
  .filter-grid,
  .export-grid {
    grid-template-columns: 1fr;
  }
}
</style>
