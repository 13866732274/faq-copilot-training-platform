<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  deleteQuizCategories,
  deleteQuizTags,
  getQuizMetaOptions,
  mergeQuizCategories,
  mergeQuizTags,
  renameQuizCategory,
  renameQuizTag,
  type QuizMetaOperateFilters,
} from '../../api/quiz'
import { getHospitals, type HospitalItem } from '../../api/hospital'
import { getDepartments, type DepartmentItem } from '../../api/department'
import { useUserStore } from '../../stores/user'

type NameCount = { name: string; count: number }

const userStore = useUserStore()
const loading = ref(false)
const hospitals = ref<HospitalItem[]>([])
const departments = ref<DepartmentItem[]>([])
const categories = ref<NameCount[]>([])
const tags = ref<NameCount[]>([])
const selectedCategories = ref<NameCount[]>([])
const selectedTags = ref<NameCount[]>([])
const isSuperAdmin = ref(false)
const filters = reactive({
  scope: '' as '' | 'common' | 'hospital' | 'department',
  hospital_id: undefined as number | undefined,
  department_id: undefined as number | undefined,
  chat_type: '' as '' | 'active' | 'passive',
})

const departmentOptionsByHospital = computed(() => {
  if (!filters.hospital_id) return departments.value
  return departments.value.filter((d) => d.hospital_id === filters.hospital_id)
})

const buildPayloadFilters = (): QuizMetaOperateFilters => ({
  scope: filters.scope || undefined,
  hospital_id: filters.hospital_id,
  department_id: filters.department_id,
  chat_type: filters.chat_type || undefined,
})

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

const loadOptions = async () => {
  loading.value = true
  try {
    const data = await getQuizMetaOptions(buildPayloadFilters())
    categories.value = data.categories || []
    tags.value = data.tags || []
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || '获取分类标签统计失败')
  } finally {
    loading.value = false
  }
}

const onHospitalChange = () => {
  if (filters.scope === 'department') {
    filters.department_id = undefined
  }
}

const renameCategory = async () => {
  if (selectedCategories.value.length !== 1) return ElMessage.warning('请先选择 1 个分类')
  const picked = selectedCategories.value[0]
  if (!picked) return ElMessage.warning('请先选择 1 个分类')
  const oldName = picked.name
  try {
    const { value } = await ElMessageBox.prompt(`将分类「${oldName}」重命名为：`, '重命名分类', {
      inputPlaceholder: '新分类名',
      confirmButtonText: '确认',
      cancelButtonText: '取消',
    })
    const newName = (value || '').trim()
    if (!newName) return ElMessage.warning('新分类不能为空')
    const result = await renameQuizCategory({ ...buildPayloadFilters(), old_name: oldName, new_name: newName })
    ElMessage.success(`重命名完成：命中 ${result.matched}，更新 ${result.updated}`)
    await loadOptions()
  } catch (error: any) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(error?.response?.data?.detail || error?.message || '重命名分类失败')
  }
}

const mergeCategories = async () => {
  if (selectedCategories.value.length < 2) return ElMessage.warning('请至少选择 2 个分类')
  const sourceNames = selectedCategories.value.map((item) => item.name)
  try {
    const { value } = await ElMessageBox.prompt(
      `将 ${sourceNames.length} 个分类合并到目标分类（输入目标名）：`,
      '合并分类',
      {
        inputPlaceholder: '目标分类名',
        confirmButtonText: '确认',
        cancelButtonText: '取消',
      },
    )
    const target = (value || '').trim()
    if (!target) return ElMessage.warning('目标分类不能为空')
    const result = await mergeQuizCategories({ ...buildPayloadFilters(), source_names: sourceNames, target_name: target })
    ElMessage.success(`合并完成：命中 ${result.matched}，更新 ${result.updated}`)
    await loadOptions()
  } catch (error: any) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(error?.response?.data?.detail || error?.message || '合并分类失败')
  }
}

const deleteCategories = async () => {
  if (!selectedCategories.value.length) return ElMessage.warning('请先选择要删除的分类')
  const names = selectedCategories.value.map((item) => item.name)
  try {
    await ElMessageBox.confirm(
      `确认删除分类：${names.join('、')}？\n删除后将清空关联案例的分类字段。`,
      '删除分类',
      { confirmButtonText: '确认删除', cancelButtonText: '取消', type: 'warning' },
    )
    const result = await deleteQuizCategories({ ...buildPayloadFilters(), names })
    ElMessage.success(`删除完成：命中 ${result.matched}，更新 ${result.updated}`)
    await loadOptions()
  } catch (error: any) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(error?.response?.data?.detail || error?.message || '删除分类失败')
  }
}

const renameTag = async () => {
  if (selectedTags.value.length !== 1) return ElMessage.warning('请先选择 1 个标签')
  const picked = selectedTags.value[0]
  if (!picked) return ElMessage.warning('请先选择 1 个标签')
  const oldName = picked.name
  try {
    const { value } = await ElMessageBox.prompt(`将标签「${oldName}」重命名为：`, '重命名标签', {
      inputPlaceholder: '新标签名',
      confirmButtonText: '确认',
      cancelButtonText: '取消',
    })
    const newName = (value || '').trim()
    if (!newName) return ElMessage.warning('新标签不能为空')
    const result = await renameQuizTag({ ...buildPayloadFilters(), old_name: oldName, new_name: newName })
    ElMessage.success(`重命名完成：命中 ${result.matched}，更新 ${result.updated}`)
    await loadOptions()
  } catch (error: any) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(error?.response?.data?.detail || error?.message || '重命名标签失败')
  }
}

const mergeTags = async () => {
  if (selectedTags.value.length < 2) return ElMessage.warning('请至少选择 2 个标签')
  const sourceNames = selectedTags.value.map((item) => item.name)
  try {
    const { value } = await ElMessageBox.prompt(`将 ${sourceNames.length} 个标签合并到目标标签：`, '合并标签', {
      inputPlaceholder: '目标标签名',
      confirmButtonText: '确认',
      cancelButtonText: '取消',
    })
    const target = (value || '').trim()
    if (!target) return ElMessage.warning('目标标签不能为空')
    const result = await mergeQuizTags({ ...buildPayloadFilters(), source_names: sourceNames, target_name: target })
    ElMessage.success(`合并完成：命中 ${result.matched}，更新 ${result.updated}`)
    await loadOptions()
  } catch (error: any) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(error?.response?.data?.detail || error?.message || '合并标签失败')
  }
}

const deleteTags = async () => {
  if (!selectedTags.value.length) return ElMessage.warning('请先选择要删除的标签')
  const names = selectedTags.value.map((item) => item.name)
  try {
    await ElMessageBox.confirm(
      `确认删除标签：${names.join('、')}？\n删除后将从所有命中案例中移除这些标签。`,
      '删除标签',
      { confirmButtonText: '确认删除', cancelButtonText: '取消', type: 'warning' },
    )
    const result = await deleteQuizTags({ ...buildPayloadFilters(), names })
    ElMessage.success(`删除完成：命中 ${result.matched}，更新 ${result.updated}`)
    await loadOptions()
  } catch (error: any) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(error?.response?.data?.detail || error?.message || '删除标签失败')
  }
}

const onCategorySelectionChange = (val: NameCount[]) => {
  selectedCategories.value = val
}

const onTagSelectionChange = (val: NameCount[]) => {
  selectedTags.value = val
}

onMounted(async () => {
  isSuperAdmin.value = userStore.user?.role === 'super_admin'
  if (!isSuperAdmin.value) {
    filters.hospital_id = userStore.user?.hospital_id || undefined
    filters.department_id = userStore.user?.department_id || undefined
    filters.scope = userStore.user?.department_id ? 'department' : 'hospital'
  }
  await Promise.all([loadHospitals(), loadDepartments()])
  await loadOptions()
})

watch(
  () => [filters.scope, filters.hospital_id, filters.department_id, filters.chat_type],
  () => {
    loadOptions()
  },
)
</script>

<template>
  <el-card shadow="never">
    <template #header>
      <div class="admin-card-header">
        <strong class="admin-card-title">分类/标签管理中心</strong>
        <div class="admin-card-header-actions">
          <el-button @click="$router.push('/admin/quizzes')">返回案例管理</el-button>
        </div>
      </div>
    </template>

    <el-alert type="info" :closable="false" show-icon>
      <template #title>
        这里的重命名/合并/删除是整站关联更新：会直接同步修改命中案例的分类与标签字段。
      </template>
    </el-alert>

    <div class="filters">
      <el-select v-model="filters.scope" clearable placeholder="范围" class="admin-control-w-sm">
        <el-option label="通用案例库" value="common" />
        <el-option label="医院专属" value="hospital" />
        <el-option label="科室专属" value="department" />
      </el-select>
      <el-select
        v-model="filters.hospital_id"
        :disabled="!isSuperAdmin"
        clearable
        placeholder="所属医院"
        class="admin-control-w-md"
        @change="onHospitalChange"
      >
        <el-option v-for="h in hospitals" :key="h.id" :label="h.name" :value="h.id" />
      </el-select>
      <el-select v-model="filters.department_id" :disabled="!isSuperAdmin" clearable placeholder="所属科室" class="admin-control-w-md">
        <el-option v-for="d in departmentOptionsByHospital" :key="d.id" :label="d.name" :value="d.id" />
      </el-select>
      <el-select v-model="filters.chat_type" clearable placeholder="聊天类型" class="admin-control-w-sm">
        <el-option label="主动聊天" value="active" />
        <el-option label="被动聊天" value="passive" />
      </el-select>
      <el-button @click="loadOptions">刷新</el-button>
    </div>

    <el-row :gutter="12" style="margin-top: 12px">
      <el-col :span="12">
        <el-card shadow="never" v-loading="loading">
          <template #header>
            <div class="admin-card-header">
              <strong class="admin-card-title">分类（{{ categories.length }}）</strong>
              <div class="admin-card-header-actions">
                <el-button size="small" :disabled="selectedCategories.length !== 1" @click="renameCategory">重命名</el-button>
                <el-button size="small" :disabled="selectedCategories.length < 2" @click="mergeCategories">合并</el-button>
                <el-button size="small" type="danger" :disabled="!selectedCategories.length" @click="deleteCategories">删除</el-button>
              </div>
            </div>
          </template>
          <el-table :data="categories" border stripe max-height="520" @selection-change="onCategorySelectionChange">
            <el-table-column type="selection" width="50" />
            <el-table-column prop="name" label="分类名" min-width="180" />
            <el-table-column prop="count" label="关联案例数" width="120" />
          </el-table>
        </el-card>
      </el-col>

      <el-col :span="12">
        <el-card shadow="never" v-loading="loading">
          <template #header>
            <div class="admin-card-header">
              <strong class="admin-card-title">标签（{{ tags.length }}）</strong>
              <div class="admin-card-header-actions">
                <el-button size="small" :disabled="selectedTags.length !== 1" @click="renameTag">重命名</el-button>
                <el-button size="small" :disabled="selectedTags.length < 2" @click="mergeTags">合并</el-button>
                <el-button size="small" type="danger" :disabled="!selectedTags.length" @click="deleteTags">删除</el-button>
              </div>
            </div>
          </template>
          <el-table :data="tags" border stripe max-height="520" @selection-change="onTagSelectionChange">
            <el-table-column type="selection" width="50" />
            <el-table-column prop="name" label="标签名" min-width="180" />
            <el-table-column prop="count" label="关联案例数" width="120" />
          </el-table>
        </el-card>
      </el-col>
    </el-row>
  </el-card>
</template>

<style scoped>
.filters {
  margin-top: 12px;
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}
</style>
