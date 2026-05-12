<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { changePasswordApi, getLoginHistoryApi, updateProfileApi } from '../../api/auth'
import { useUserStore } from '../../stores/user'
import { setAuth } from '../../utils/auth'

const userStore = useUserStore()
const loading = ref(false)
const submitLoading = ref(false)
const pwdLoading = ref(false)
const historyLoading = ref(false)
const activeTab = ref<'profile' | 'password' | 'history'>('profile')

const profileForm = reactive({
  real_name: '',
  avatar: '',
})

const passwordForm = reactive({
  current_password: '',
  new_password: '',
  confirm_password: '',
})

const loginHistory = ref<Array<{ id: number; status: 'success' | 'fail'; ip?: string | null; reason?: string | null; created_at: string }>>(
  [],
)

const displayName = computed(() => profileForm.real_name || userStore.user?.real_name || userStore.user?.username || '未命名用户')
const avatarFallback = computed(() => {
  const name = displayName.value.trim()
  return name ? name.slice(0, 1).toUpperCase() : 'U'
})

const loadInitial = async () => {
  loading.value = true
  try {
    const user = userStore.user
    profileForm.real_name = user?.real_name || ''
    profileForm.avatar = user?.avatar || ''
    await loadLoginHistory()
  } finally {
    loading.value = false
  }
}

const loadLoginHistory = async () => {
  historyLoading.value = true
  try {
    loginHistory.value = await getLoginHistoryApi({ limit: 10 })
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || '获取登录记录失败')
  } finally {
    historyLoading.value = false
  }
}

const submitProfile = async () => {
  submitLoading.value = true
  try {
    const data = await updateProfileApi({
      real_name: profileForm.real_name,
      avatar: profileForm.avatar,
    })
    if (userStore.token && userStore.user) {
      const nextUser = { ...userStore.user, real_name: data.real_name, avatar: data.avatar || null }
      setAuth(userStore.token, nextUser)
      userStore.user = nextUser
    }
    ElMessage.success('个人资料已更新')
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || '更新资料失败')
  } finally {
    submitLoading.value = false
  }
}

const submitPassword = async () => {
  if (!passwordForm.current_password || !passwordForm.new_password) {
    ElMessage.warning('请完整填写密码信息')
    return
  }
  if (passwordForm.new_password !== passwordForm.confirm_password) {
    ElMessage.warning('两次输入的新密码不一致')
    return
  }
  pwdLoading.value = true
  try {
    await changePasswordApi({
      current_password: passwordForm.current_password,
      new_password: passwordForm.new_password,
    })
    passwordForm.current_password = ''
    passwordForm.new_password = ''
    passwordForm.confirm_password = ''
    ElMessage.success('密码修改成功')
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || '密码修改失败')
  } finally {
    pwdLoading.value = false
  }
}

onMounted(loadInitial)
</script>

<template>
  <div class="profile-page" v-loading="loading">
    <el-card shadow="never" class="profile-hero">
      <div class="profile-hero-inner">
        <el-avatar :src="profileForm.avatar || undefined" :size="64" class="profile-avatar">
          {{ avatarFallback }}
        </el-avatar>
        <div class="profile-summary">
          <strong class="profile-name">{{ displayName }}</strong>
          <div class="profile-meta">
            <el-tag effect="dark" type="success">账号：{{ userStore.user?.username || '-' }}</el-tag>
            <el-tag effect="plain">角色：{{ userStore.user?.role || '-' }}</el-tag>
          </div>
          <div class="profile-tip">建议定期更新密码并关注登录设备记录，保障账号安全。</div>
        </div>
      </div>
    </el-card>

    <el-card shadow="never" class="profile-main">
      <template #header>
        <div class="profile-tabs">
          <button
            type="button"
            class="profile-tab-item"
            :class="{ active: activeTab === 'profile' }"
            @click="activeTab = 'profile'"
          >
            个人资料
          </button>
          <button
            type="button"
            class="profile-tab-item"
            :class="{ active: activeTab === 'password' }"
            @click="activeTab = 'password'"
          >
            修改密码
          </button>
          <button
            type="button"
            class="profile-tab-item"
            :class="{ active: activeTab === 'history' }"
            @click="activeTab = 'history'"
          >
            登录设备记录
          </button>
        </div>
      </template>

      <div v-if="activeTab === 'profile'" class="tab-panel">
        <el-form label-width="96px" class="profile-form">
          <el-form-item label="用户名">
            <el-input :model-value="userStore.user?.username || '-'" disabled />
          </el-form-item>
          <el-form-item label="姓名">
            <el-input v-model="profileForm.real_name" maxlength="50" show-word-limit />
          </el-form-item>
          <el-form-item label="头像地址">
            <el-input v-model="profileForm.avatar" placeholder="可填写头像 URL（可选）" />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" :loading="submitLoading" @click="submitProfile">保存资料</el-button>
          </el-form-item>
        </el-form>
      </div>

      <div v-else-if="activeTab === 'password'" class="tab-panel">
        <el-form label-width="110px" class="profile-form">
          <el-form-item label="当前密码">
            <el-input v-model="passwordForm.current_password" type="password" show-password />
          </el-form-item>
          <el-form-item label="新密码">
            <el-input v-model="passwordForm.new_password" type="password" show-password />
          </el-form-item>
          <el-form-item label="确认新密码">
            <el-input v-model="passwordForm.confirm_password" type="password" show-password />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" :loading="pwdLoading" @click="submitPassword">更新密码</el-button>
          </el-form-item>
        </el-form>
      </div>

      <div v-else class="tab-panel">
        <el-table :data="loginHistory" border stripe v-loading="historyLoading">
          <el-table-column prop="created_at" label="时间" width="180" />
          <el-table-column label="状态" width="100">
            <template #default="{ row }">
              <el-tag :type="row.status === 'success' ? 'success' : 'danger'">
                {{ row.status === 'success' ? '成功' : '失败' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="ip" label="IP" min-width="150" />
          <el-table-column prop="reason" label="失败原因" min-width="180" />
        </el-table>
      </div>
    </el-card>
  </div>
</template>

<style scoped>
.profile-page {
  display: grid;
  gap: 12px;
}

.profile-hero {
  border: 1px solid var(--ui-border-soft);
  background:
    radial-gradient(circle at 2% 18%, color-mix(in srgb, var(--el-color-primary-light-8) 72%, transparent 28%) 0%, transparent 35%),
    linear-gradient(120deg, color-mix(in srgb, var(--ui-surface-1) 90%, transparent 10%) 0%, var(--ui-surface-2) 100%);
}

.profile-hero-inner {
  display: flex;
  align-items: center;
  gap: 14px;
}

.profile-avatar {
  border: 2px solid color-mix(in srgb, var(--el-color-primary) 38%, transparent 62%);
  box-shadow: 0 10px 24px color-mix(in srgb, var(--el-color-primary) 24%, transparent 76%);
}

.profile-summary {
  min-width: 0;
}

.profile-name {
  font-size: 20px;
  font-weight: 800;
  line-height: 1.1;
}

.profile-meta {
  margin-top: 8px;
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.profile-tip {
  margin-top: 8px;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}

.profile-main {
  border: 1px solid var(--ui-border-soft);
}

.profile-tabs {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px;
  border-radius: 12px;
  border: 1px solid var(--ui-border-soft);
  background: color-mix(in srgb, var(--ui-surface-1) 88%, transparent 12%);
}

.profile-tab-item {
  border: none;
  outline: none;
  cursor: pointer;
  height: 34px;
  padding: 0 14px;
  border-radius: 9px;
  background: transparent;
  color: var(--el-text-color-regular);
  font-size: 14px;
  font-weight: 700;
  transition: all 0.24s ease;
}

.profile-tab-item:hover {
  color: var(--el-color-primary);
  background: color-mix(in srgb, var(--el-color-primary-light-9) 70%, transparent 30%);
}

.profile-tab-item.active {
  color: var(--el-color-primary);
  background: var(--ui-surface-1);
  box-shadow:
    inset 0 0 0 1px color-mix(in srgb, var(--el-color-primary) 24%, transparent 76%),
    0 8px 20px color-mix(in srgb, var(--el-color-primary) 16%, transparent 84%);
}

.tab-panel {
  animation: profilePanelIn 240ms ease;
}

.profile-form {
  max-width: 560px;
}

@keyframes profilePanelIn {
  from {
    opacity: 0;
    transform: translateY(4px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@media (max-width: 768px) {
  .profile-hero-inner {
    align-items: flex-start;
  }

  .profile-tabs {
    width: 100%;
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .profile-tab-item {
    width: 100%;
    padding: 0 8px;
    font-size: 13px;
  }
}
</style>
