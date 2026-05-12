<script setup lang="ts">
import { onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'
import { useUserStore } from '../../stores/user'
import { getPublicSystemSettings } from '../../api/system'
import { clearLastRoute, getLastRoute } from '../../utils/auth'
import { applyRuntimeBrandAccent } from '../../utils/systemTheme'
import { applyPageTitle } from '../../utils/pageTitle'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()
const loading = ref(false)
const initialLoading = ref(true)
const loginSiteName = ref('咨询话术模拟训练系统')
const loginSiteSubtitle = ref('模拟真实沟通流程，专注规范化回复训练')
const loginLogoUrl = ref('')
const showTenantInput = ref(false)
const defaultTenantCode = ref('')

const form = reactive({
  username: '',
  password: '',
  tenant_code: '',
})

const submit = async () => {
  loading.value = true
  try {
    const loginPayload: { username: string; password: string; tenant_code?: string } = {
      username: form.username,
      password: form.password,
    }
    const tenantCode = (form.tenant_code || defaultTenantCode.value || '').trim()
    if (tenantCode) {
      loginPayload.tenant_code = tenantCode
    }
    await userStore.login(loginPayload)
    ElMessage.success('登录成功')
    const queryRedirect = typeof route.query.redirect === 'string' ? route.query.redirect : ''
    const lastRoute = getLastRoute()
    const role = userStore.user?.role
    const defaultRoute = role === 'student' ? '/practice/faq-copilot' : '/admin/dashboard'
    const redirect = queryRedirect || lastRoute || defaultRoute
    clearLastRoute()
    router.replace(redirect)
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || error?.message || '登录失败')
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  try {
    const data = await getPublicSystemSettings()
    loginSiteName.value = data.site_name || loginSiteName.value
    loginSiteSubtitle.value = data.site_subtitle || loginSiteSubtitle.value
    loginLogoUrl.value = data.logo_url || ''
    applyRuntimeBrandAccent(data.brand_accent)
    if (data.default_tenant_code) {
      defaultTenantCode.value = data.default_tenant_code
    }
    showTenantInput.value = !!data.show_tenant_input
  } catch {
    // ignore
  } finally {
    initialLoading.value = false
  }
})

watch(
  () => loginSiteName.value,
  (siteName) => {
    applyPageTitle(siteName, '登录')
  },
  { immediate: true },
)
</script>

<template>
  <div class="login-page">
    <div class="bg-grid" />
    <div class="bg-glow bg-glow-left" />
    <div class="bg-glow bg-glow-right" />
    <el-card v-loading="initialLoading" class="login-card" shadow="hover">
      <div class="title-row">
        <img v-if="loginLogoUrl" :src="loginLogoUrl" class="title-logo" alt="logo" />
        <el-tag size="small" effect="dark" class="title-tag">安全登录</el-tag>
      </div>
      <h2 class="title">{{ loginSiteName }}</h2>
      <p class="subtitle">{{ loginSiteSubtitle }}</p>
      <el-form class="login-form" label-position="top" @submit.prevent="submit">
        <el-form-item v-if="showTenantInput" label="租户编码">
          <el-input
            v-model="form.tenant_code"
            class="wechat-input"
            placeholder="请输入租户编码（由管理员提供）"
            autocomplete="organization"
          />
        </el-form-item>
        <el-form-item label="用户名">
          <el-input v-model="form.username" class="wechat-input" autocomplete="username" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input
            v-model="form.password"
            class="wechat-input"
            type="password"
            show-password
            autocomplete="current-password"
          />
        </el-form-item>
        <el-button
          class="wechat-btn"
          type="primary"
          style="width: 100%"
          :loading="loading"
          :disabled="initialLoading"
          @click="submit"
        >
          登录
        </el-button>
      </el-form>
      <p class="hint">请使用管理员创建的有效账号登录（若账号被禁用将无法登录）</p>
    </el-card>
  </div>
</template>

<style scoped>
.login-page {
  min-height: 100vh;
  padding: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--el-bg-color-page);
  color: var(--el-text-color-primary);
  position: relative;
  overflow: hidden;
}

.bg-grid {
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(to right, color-mix(in srgb, var(--el-text-color-placeholder) 16%, transparent 84%) 1px, transparent 1px),
    linear-gradient(to bottom, color-mix(in srgb, var(--el-text-color-placeholder) 16%, transparent 84%) 1px, transparent 1px);
  background-size: 28px 28px;
  mask-image: radial-gradient(circle at center, black 36%, transparent 86%);
  opacity: 0.4;
  pointer-events: none;
  z-index: 0;
}

.login-card {
  width: min(420px, 100%);
  border: 1px solid var(--el-border-color-light);
  background: var(--el-bg-color);
  border-radius: 16px;
  position: relative;
  z-index: 2;
  backdrop-filter: blur(3px);
  box-shadow: 0 14px 36px rgb(0 0 0 / 11%);
  transition: transform 0.2s ease, box-shadow 0.22s ease;
}

.login-card:hover {
  transform: translateY(-1px);
  box-shadow: 0 18px 42px rgb(0 0 0 / 14%);
}

.title-row {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: 10px;
}

.title-logo {
  width: 22px;
  height: 22px;
  border-radius: 6px;
  object-fit: cover;
}

.title-tag {
  border: none;
  border-radius: 999px;
  background: linear-gradient(135deg, var(--el-color-primary) 0%, var(--el-color-success) 100%);
}

.title {
  margin: 0 0 8px;
  text-align: center;
  color: var(--el-text-color-primary);
  letter-spacing: 0.3px;
}

.subtitle {
  margin: 0 0 18px;
  text-align: center;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}

.hint {
  margin: 12px 0 0;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}

.bg-glow {
  position: absolute;
  width: 320px;
  height: 320px;
  border-radius: 50%;
  filter: blur(56px);
  opacity: 0.22;
  pointer-events: none;
  z-index: 1;
}

.bg-glow-left {
  left: -120px;
  top: -80px;
  background: color-mix(in srgb, var(--el-color-success) 86%, #ffffff 14%);
}

.bg-glow-right {
  right: -120px;
  bottom: -100px;
  background: color-mix(in srgb, var(--el-color-primary) 84%, #ffffff 16%);
}

:deep(.wechat-input .el-input__wrapper) {
  border-radius: 10px;
  transition: box-shadow 0.2s ease;
}

:deep(.wechat-input .el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 1px var(--brand-accent) inset;
}

.wechat-btn {
  border-radius: 10px;
  height: 40px;
  border-color: var(--brand-accent);
  background: var(--brand-accent);
  transition: transform 0.16s ease, filter 0.16s ease, box-shadow 0.16s ease;
}

.wechat-btn:hover {
  border-color: var(--brand-accent-hover);
  background: var(--brand-accent-hover);
  filter: brightness(1.02);
  box-shadow: 0 8px 20px -12px var(--brand-accent);
}

.wechat-btn:active {
  transform: translateY(1px);
}

:deep(.login-form .el-form-item) {
  margin-bottom: 16px;
}

:deep(.login-form .el-form-item__label) {
  line-height: 1.2;
  padding-bottom: 6px;
  color: var(--el-text-color-regular);
  font-size: 13px;
}

:deep(.login-form .el-input__wrapper) {
  box-shadow: 0 0 0 1px var(--el-border-color) inset;
}

:deep(.login-form .el-input__wrapper:hover) {
  box-shadow: 0 0 0 1px var(--el-border-color-dark) inset;
}

:deep(.login-form .el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 1px var(--brand-accent) inset, 0 0 0 3px var(--brand-accent-focus);
}

@media (max-width: 768px) {
  .login-page {
    align-items: flex-start;
    padding: 12px;
    padding-top: max(12px, env(safe-area-inset-top));
  }

  .login-card {
    margin-top: 10vh;
    border-radius: 14px;
    box-shadow: 0 10px 26px rgb(0 0 0 / 11%);
  }

  .title {
    margin-bottom: 16px;
    font-size: 20px;
  }

  .subtitle {
    margin-bottom: 14px;
    font-size: 12px;
  }

  .bg-glow {
    width: 240px;
    height: 240px;
    filter: blur(44px);
    opacity: 0.18;
  }

  :deep(.login-form .el-form-item) {
    margin-bottom: 14px;
  }

  :deep(.login-form .el-form-item__label) {
    font-size: 13px;
  }
}
</style>
