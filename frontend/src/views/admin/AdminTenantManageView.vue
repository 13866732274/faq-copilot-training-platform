<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRouter } from 'vue-router'
import {
  createTenant,
  getTenantModules,
  getTenants,
  updateTenant,
  updateTenantModule,
  type TenantItem,
  type TenantModuleItem,
} from '../../api/tenant'
import { startImpersonationApi, stopImpersonationApi } from '../../api/auth'
import { useUserStore } from '../../stores/user'
import { setAuth } from '../../utils/auth'
import { refreshPermissionPoints } from '../../utils/permissionPoints'

const router = useRouter()
const userStore = useUserStore()
const loading = ref(false)
const submitting = ref(false)
const switchingTenant = ref(false)
const rows = ref<TenantItem[]>([])
const moduleRows = ref<TenantModuleItem[]>([])
const moduleDialogVisible = ref(false)
const moduleLoading = ref(false)
const moduleSubmitting = ref(false)
const moduleTenantId = ref(0)
const moduleTenantName = ref('')

const createForm = reactive({
  code: '',
  name: '',
})

const editDialogVisible = ref(false)
const editForm = reactive({
  id: 0,
  name: '',
  is_active: true,
})

const load = async () => {
  loading.value = true
  try {
    const data = await getTenants()
    rows.value = data.items || []
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || '获取租户列表失败')
  } finally {
    loading.value = false
  }
}

const submitCreate = async () => {
  if (!createForm.code.trim() || !createForm.name.trim()) {
    ElMessage.warning('请先填写租户编码和租户名称')
    return
  }
  submitting.value = true
  try {
    await createTenant({ code: createForm.code.trim(), name: createForm.name.trim() })
    ElMessage.success('租户创建成功')
    createForm.code = ''
    createForm.name = ''
    await load()
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || '租户创建失败')
  } finally {
    submitting.value = false
  }
}

const openEdit = (row: TenantItem) => {
  editForm.id = row.id
  editForm.name = row.name
  editForm.is_active = Boolean(row.is_active)
  editDialogVisible.value = true
}

const goTenantSettings = (row: TenantItem) => {
  router.push(`/admin/system/settings?tenant_id=${row.id}`)
}

const isImpersonating = () => Boolean(userStore.user?.is_impersonating)

const startTenantImpersonation = async (row: TenantItem) => {
  if (!row.is_active) {
    ElMessage.warning('目标租户已停用，不能代入')
    return
  }
  try {
    const reason = await ElMessageBox.prompt('请输入代入原因（将写入审计日志）', '开启租户代入', {
      confirmButtonText: '确认代入',
      cancelButtonText: '取消',
      inputPlaceholder: '例如：排查租户案例库权限问题',
    })
    switchingTenant.value = true
    const data = await startImpersonationApi({
      tenant_id: row.id,
      reason: (reason.value || '').trim() || '运维排障',
      duration_minutes: 30,
    })
    setAuth(data.access_token, data.user)
    userStore.token = data.access_token
    userStore.user = data.user
    try {
      await refreshPermissionPoints()
    } catch {
      // ignore permission preload failure
    }
    ElMessage.success(`已进入租户代入：${row.name}`)
    await router.replace('/admin/dashboard')
  } catch (error: any) {
    if (error === 'cancel') return
    ElMessage.error(error?.response?.data?.detail || '开启租户代入失败')
  } finally {
    switchingTenant.value = false
  }
}

const stopTenantImpersonation = async () => {
  switchingTenant.value = true
  try {
    const data = await stopImpersonationApi()
    setAuth(data.access_token, data.user)
    userStore.token = data.access_token
    userStore.user = data.user
    try {
      await refreshPermissionPoints()
    } catch {
      // ignore permission preload failure
    }
    ElMessage.success('已退出租户代入，恢复超级管理员身份')
    await router.replace('/admin/system/tenants')
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || '退出租户代入失败')
  } finally {
    switchingTenant.value = false
  }
}

const submitEdit = async () => {
  if (!editForm.id) return
  if (!editForm.name.trim()) {
    ElMessage.warning('租户名称不能为空')
    return
  }
  submitting.value = true
  try {
    await updateTenant(editForm.id, {
      name: editForm.name.trim(),
      is_active: editForm.is_active,
    })
    ElMessage.success('租户更新成功')
    editDialogVisible.value = false
    await load()
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || '租户更新失败')
  } finally {
    submitting.value = false
  }
}

const openModuleDialog = async (row: TenantItem) => {
  moduleTenantId.value = row.id
  moduleTenantName.value = row.name
  moduleDialogVisible.value = true
  moduleLoading.value = true
  try {
    const data = await getTenantModules(row.id)
    moduleRows.value = data.items || []
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || '获取模块配置失败')
  } finally {
    moduleLoading.value = false
  }
}

const onModuleSwitchChange = async (item: TenantModuleItem, value: string | number | boolean) => {
  if (!moduleTenantId.value) return
  moduleSubmitting.value = true
  try {
    const enabled = Boolean(value)
    const data = await updateTenantModule(moduleTenantId.value, {
      module_id: item.module_id,
      is_enabled: enabled,
    })
    moduleRows.value = data.items || []
    ElMessage.success(`${item.name} 已${enabled ? '启用' : '停用'}`)
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || '模块开关更新失败')
    // 回滚显示状态（下一次打开也会重新拉取）
    item.is_enabled = !item.is_enabled
  } finally {
    moduleSubmitting.value = false
  }
}

const moduleTagType = (item: TenantModuleItem) => {
  if (item.is_enabled) return 'success'
  return item.is_default ? 'warning' : 'info'
}

onMounted(load)
</script>

<template>
  <el-card shadow="never">
    <template #header>
      <div class="admin-card-header">
        <strong class="admin-card-title">租户管理（S1 收口版）</strong>
      </div>
    </template>

    <el-alert
      type="info"
      :closable="false"
      show-icon
      style="margin-bottom: var(--space-3)"
      title="当前版本已支持租户主数据维护、停用租户强制生效、会话批量失效（session version）与多业务域租户隔离。"
    />
    <el-alert
      v-if="isImpersonating()"
      type="warning"
      :closable="false"
      show-icon
      style="margin-bottom: var(--space-3)"
    >
      <template #title>
        当前处于租户代入模式（{{ userStore.user?.impersonation_tenant_name || '-' }}），请仅用于排障操作。
        <el-button link type="warning" :loading="switchingTenant" @click="stopTenantImpersonation">退出代入</el-button>
      </template>
    </el-alert>

    <div class="tenant-create">
      <el-input v-model="createForm.code" placeholder="租户编码（英文/数字）" class="admin-control-w-sm" />
      <el-input v-model="createForm.name" placeholder="租户名称" class="admin-control-w-lg" />
      <el-button type="primary" :loading="submitting" @click="submitCreate">创建租户</el-button>
    </div>

    <el-table v-loading="loading" :data="rows" border stripe class="admin-list-table">
      <el-table-column prop="id" label="ID" width="80" />
      <el-table-column prop="code" label="编码" min-width="160" />
      <el-table-column prop="name" label="名称" min-width="220" />
      <el-table-column label="状态" width="120">
        <template #default="{ row }">
          <el-tag :type="row.is_active ? 'success' : 'info'">{{ row.is_active ? '启用' : '停用' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="session_version" label="会话版本" width="110" />
      <el-table-column prop="updated_at" label="更新时间" min-width="180" />
      <el-table-column label="操作" width="380">
        <template #default="{ row }">
          <el-button link type="primary" @click="openModuleDialog(row)">模块配置</el-button>
          <el-button link type="success" @click="goTenantSettings(row)">功能设置</el-button>
          <el-button
            link
            type="warning"
            :disabled="switchingTenant || (isImpersonating() && userStore.user?.impersonation_tenant_id === row.id)"
            @click="startTenantImpersonation(row)"
          >
            安全代入
          </el-button>
          <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
        </template>
      </el-table-column>
    </el-table>
  </el-card>

  <el-dialog v-model="editDialogVisible" title="编辑租户" width="460px">
    <el-form label-width="90px">
      <el-form-item label="租户名称">
        <el-input v-model="editForm.name" />
      </el-form-item>
      <el-form-item label="是否启用">
        <el-switch v-model="editForm.is_active" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="editDialogVisible = false">取消</el-button>
      <el-button type="primary" :loading="submitting" @click="submitEdit">保存</el-button>
    </template>
  </el-dialog>

  <el-dialog
    v-model="moduleDialogVisible"
    :title="`模块配置 - ${moduleTenantName || '-'}`"
    width="900px"
    destroy-on-close
  >
    <el-alert
      type="info"
      :closable="false"
      show-icon
      style="margin-bottom: var(--space-3)"
      title="停用模块后，该租户下对应菜单与接口将立即不可用。若存在依赖关系，系统会拒绝冲突操作。"
    />
    <el-table v-loading="moduleLoading" :data="moduleRows" border stripe class="admin-list-table">
      <el-table-column prop="module_id" label="模块ID" min-width="130" />
      <el-table-column prop="name" label="模块名称" min-width="160" />
      <el-table-column label="状态" width="120">
        <template #default="{ row }">
          <el-tag :type="moduleTagType(row)">
            {{ row.is_enabled ? '已启用' : row.is_default ? '默认启用(已覆盖为关)' : '未启用' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="依赖" min-width="160">
        <template #default="{ row }">
          <span v-if="!row.dependencies?.length" class="muted">无</span>
          <el-space v-else wrap>
            <el-tag v-for="dep in row.dependencies" :key="dep" size="small" type="info">{{ dep }}</el-tag>
          </el-space>
        </template>
      </el-table-column>
      <el-table-column label="被依赖" min-width="160">
        <template #default="{ row }">
          <span v-if="!row.depended_by?.length" class="muted">无</span>
          <el-space v-else wrap>
            <el-tag v-for="dep in row.depended_by" :key="dep" size="small">{{ dep }}</el-tag>
          </el-space>
        </template>
      </el-table-column>
      <el-table-column label="开关" width="120">
        <template #default="{ row }">
          <el-switch
            :model-value="row.is_enabled"
            :loading="moduleSubmitting"
            @change="(v: boolean) => onModuleSwitchChange(row, v)"
          />
        </template>
      </el-table-column>
    </el-table>
  </el-dialog>
</template>

<style scoped>
.tenant-create {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-3);
  flex-wrap: wrap;
}

.muted {
  color: var(--el-text-color-placeholder);
}
</style>
