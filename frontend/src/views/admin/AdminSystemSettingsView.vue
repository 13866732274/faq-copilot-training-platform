<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useRoute } from 'vue-router'
import { getSystemSettings, updateSystemSettings } from '../../api/system'
import { useUserStore } from '../../stores/user'
import { applyRuntimeBrandAccent, normalizeBrandAccent } from '../../utils/systemTheme'
import { applyPageTitle, broadcastSiteTitleUpdate } from '../../utils/pageTitle'
import { broadcastFeatureFlagsUpdate, writeFeatureFlagsCache } from '../../utils/systemFeatures'
import { evaluatePermissionPoint } from '../../utils/permissionPoints'

const userStore = useUserStore()
const route = useRoute()
const loading = ref(false)
const saving = ref(false)
const isSuperAdmin = ref(false)
const updateSettingsPerm = computed(() => evaluatePermissionPoint('system.settings.update'))
const targetTenantId = computed<number | undefined>(() => {
  const q = route.query.tenant_id
  const n = Number(typeof q === 'string' ? q : '')
  return Number.isInteger(n) && n > 0 ? n : undefined
})

const form = reactive({
  site_name: '',
  site_subtitle: '',
  logo_url: '',
  brand_accent: '#07c160',
  enable_ai_scoring: false,
  enable_export_center: true,
  enable_audit_enhanced: true,
  admin_menu_template_lock: true,
  faq_task_timeout_minutes: 15 as 5 | 15 | 30,
})

const capabilityCards = computed(() => [
  {
    key: 'ai',
    title: 'AI 评分能力',
    subtitle: form.enable_ai_scoring ? '练习复盘可用，评分接口已开启' : '练习复盘隐藏评分，接口返回 403',
    active: form.enable_ai_scoring,
  },
  {
    key: 'export',
    title: '导出中心能力',
    subtitle: form.enable_export_center ? '导出中心可访问，CSV导出可执行' : '导出接口被拦截，返回 403',
    active: form.enable_export_center,
  },
  {
    key: 'audit',
    title: '增强审计能力',
    subtitle: form.enable_audit_enhanced ? '审计日志页可访问' : '审计日志接口被拦截，返回 403',
    active: form.enable_audit_enhanced,
  },
  {
    key: 'admin_template_lock',
    title: '管理员模板锁定（全局）',
    subtitle: form.admin_menu_template_lock ? '新增管理员默认锁定“对话+FAQ”模板，所有浏览器统一生效' : '新增管理员可自由修改菜单模板',
    active: form.admin_menu_template_lock,
  },
  {
    key: 'faq_timeout',
    title: 'FAQ 任务心跳超时阈值',
    subtitle: `当前 ${form.faq_task_timeout_minutes} 分钟无阶段变化自动判死`,
    active: true,
  },
])

const load = async () => {
  loading.value = true
  try {
    const data = await getSystemSettings({ tenant_id: targetTenantId.value })
    form.site_name = data.site_name
    form.site_subtitle = data.site_subtitle
    form.logo_url = data.logo_url || ''
    form.brand_accent = normalizeBrandAccent(data.brand_accent) || data.brand_accent
    form.enable_ai_scoring = data.enable_ai_scoring
    form.enable_export_center = data.enable_export_center
    form.enable_audit_enhanced = data.enable_audit_enhanced
    form.admin_menu_template_lock = data.admin_menu_template_lock
    form.faq_task_timeout_minutes = data.faq_task_timeout_minutes
    applyRuntimeBrandAccent(data.brand_accent)
    applyPageTitle(data.site_name, '系统设置')
    writeFeatureFlagsCache(data)
    broadcastFeatureFlagsUpdate(data)
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || '加载系统设置失败')
  } finally {
    loading.value = false
  }
}

const save = async () => {
  if (!updateSettingsPerm.value.allowed) {
    ElMessage.warning(updateSettingsPerm.value.reason)
    return
  }
  saving.value = true
  try {
    const normalizedBrandAccent = normalizeBrandAccent(form.brand_accent)
    if (!normalizedBrandAccent) {
      ElMessage.warning('品牌主色格式不正确，请使用 #RGB/#RRGGBB 或 rgb()/rgba()')
      return
    }
    const data = await updateSystemSettings(
      {
        site_name: form.site_name.trim(),
        site_subtitle: form.site_subtitle.trim(),
        logo_url: form.logo_url.trim() || null,
        brand_accent: normalizedBrandAccent,
        enable_ai_scoring: form.enable_ai_scoring,
        enable_export_center: form.enable_export_center,
        enable_audit_enhanced: form.enable_audit_enhanced,
        admin_menu_template_lock: form.admin_menu_template_lock,
        faq_task_timeout_minutes: form.faq_task_timeout_minutes,
      },
      { tenant_id: targetTenantId.value },
    )
    form.site_name = data.site_name
    form.site_subtitle = data.site_subtitle
    form.logo_url = data.logo_url || ''
    form.brand_accent = normalizeBrandAccent(data.brand_accent) || data.brand_accent
    form.enable_ai_scoring = data.enable_ai_scoring
    form.enable_export_center = data.enable_export_center
    form.enable_audit_enhanced = data.enable_audit_enhanced
    form.admin_menu_template_lock = data.admin_menu_template_lock
    form.faq_task_timeout_minutes = data.faq_task_timeout_minutes
    applyRuntimeBrandAccent(data.brand_accent)
    applyPageTitle(data.site_name, '系统设置')
    broadcastSiteTitleUpdate({
      site_name: data.site_name,
      site_subtitle: data.site_subtitle,
    })
    writeFeatureFlagsCache(data)
    broadcastFeatureFlagsUpdate(data)
    ElMessage.success('系统设置已保存')
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || '保存系统设置失败')
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  isSuperAdmin.value = userStore.user?.role === 'super_admin'
  load()
})
</script>

<template>
  <el-card shadow="never" v-loading="loading" class="settings-card">
    <template #header>
      <div class="admin-card-header">
        <div class="settings-header-main">
          <strong class="admin-card-title">系统设置面板</strong>
          <p class="settings-header-desc">站点标题、品牌色、能力开关均实时生效，保存后全局同步。</p>
        </div>
        <div class="admin-card-header-actions">
          <el-tag v-if="targetTenantId" type="info">目标租户ID: {{ targetTenantId }}</el-tag>
          <el-tag v-if="isSuperAdmin" type="success">超级管理员可编辑</el-tag>
          <el-tag v-else type="warning">仅超级管理员可编辑</el-tag>
        </div>
      </div>
    </template>

    <div class="preview-banner">
      <div class="preview-banner-top">
        <strong class="preview-title">{{ form.site_name || '咨询话术模拟训练系统' }}</strong>
        <span class="preview-subtitle">{{ form.site_subtitle || '运营管理中台' }}</span>
      </div>
      <div class="preview-banner-url">
        浏览器标题预览：{{ (form.site_name || '咨询话术模拟训练系统') + ' - 系统设置' }}
      </div>
    </div>

    <el-form label-width="120px" class="settings-form">
      <el-form-item label="系统名称" required>
        <el-input v-model="form.site_name" :disabled="!isSuperAdmin" maxlength="120" />
      </el-form-item>
      <el-form-item label="系统副标题" required>
        <el-input v-model="form.site_subtitle" :disabled="!isSuperAdmin" maxlength="120" />
      </el-form-item>
      <el-form-item label="Logo 地址">
        <el-input v-model="form.logo_url" :disabled="!isSuperAdmin" maxlength="500" placeholder="https://..." />
      </el-form-item>
      <el-form-item label="品牌主色">
        <div class="color-row">
          <el-color-picker v-model="form.brand_accent" :disabled="!isSuperAdmin" show-alpha="false" />
          <el-input v-model="form.brand_accent" :disabled="!isSuperAdmin" maxlength="20" class="color-input" />
        </div>
      </el-form-item>
      <el-divider content-position="left">功能开关</el-divider>
      <div class="capability-switch-grid">
        <el-form-item label="AI 评分能力">
          <el-switch v-model="form.enable_ai_scoring" :disabled="!isSuperAdmin" />
        </el-form-item>
        <el-form-item label="导出中心能力">
          <el-switch v-model="form.enable_export_center" :disabled="!isSuperAdmin" />
        </el-form-item>
        <el-form-item label="增强审计能力">
          <el-switch v-model="form.enable_audit_enhanced" :disabled="!isSuperAdmin" />
        </el-form-item>
        <el-form-item label="模板锁定（全局）">
          <el-switch v-model="form.admin_menu_template_lock" :disabled="!isSuperAdmin" />
        </el-form-item>
        <el-form-item label="FAQ超时阈值">
          <el-select v-model="form.faq_task_timeout_minutes" :disabled="!isSuperAdmin" style="width: 220px">
            <el-option :value="5" label="5 分钟（敏捷，易误杀）" />
            <el-option :value="15" label="15 分钟（推荐）" />
            <el-option :value="30" label="30 分钟（保守）" />
          </el-select>
        </el-form-item>
      </div>
    </el-form>

    <div class="capability-cards">
      <div v-for="item in capabilityCards" :key="item.key" class="capability-card" :class="{ active: item.active }">
        <div class="capability-state-dot" />
        <div class="capability-main">
          <strong>{{ item.title }}</strong>
          <span>{{ item.subtitle }}</span>
        </div>
        <el-tag :type="item.active ? 'success' : 'info'" size="small">
          {{ item.active ? '已启用' : '已关闭' }}
        </el-tag>
      </div>
    </div>

    <div class="settings-actions">
      <el-button :disabled="saving" @click="load">重新加载</el-button>
      <el-tooltip :disabled="updateSettingsPerm.allowed" :content="updateSettingsPerm.reason" placement="top">
        <span>
          <el-button type="primary" :loading="saving" :disabled="!updateSettingsPerm.allowed" @click="save">保存设置</el-button>
        </span>
      </el-tooltip>
    </div>
  </el-card>
</template>

<style scoped>
.settings-card {
  position: relative;
}

.settings-header-main {
  display: grid;
  gap: 4px;
}

.settings-header-desc {
  margin: 0;
  color: var(--el-text-color-secondary);
  font-size: var(--font-size-xs);
}

.settings-form {
  max-width: 760px;
}

.preview-banner {
  border: 1px solid color-mix(in srgb, var(--el-color-primary) 20%, var(--ui-border-soft) 80%);
  border-radius: 14px;
  padding: 12px var(--space-4);
  margin-bottom: var(--space-4);
  background:
    radial-gradient(circle at 84% 16%, color-mix(in srgb, var(--el-color-primary) 20%, transparent 80%) 0%, transparent 46%),
    linear-gradient(140deg, color-mix(in srgb, var(--ui-surface-1) 88%, #fff 12%) 0%, color-mix(in srgb, var(--ui-surface-2) 90%, #fff 10%) 100%);
  box-shadow: var(--ui-shadow-soft);
}

.preview-banner-top {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 10px;
}

.preview-title {
  font-size: var(--font-size-h5);
  line-height: var(--line-height-tight);
}

.preview-subtitle {
  color: var(--el-text-color-secondary);
  font-size: var(--font-size-sm);
}

.preview-banner-url {
  margin-top: 6px;
  font-size: var(--font-size-xs);
  color: var(--el-color-primary);
}

.settings-actions {
  margin-top: var(--space-4);
  display: flex;
  justify-content: flex-end;
  gap: var(--space-2);
}

.color-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  width: 100%;
}

.color-input {
  max-width: 200px;
}

.capability-switch-grid {
  display: grid;
  gap: 0;
}

.capability-cards {
  margin-top: var(--space-3);
  display: grid;
  gap: var(--space-2);
}

.capability-card {
  display: flex;
  align-items: center;
  gap: 10px;
  border: 1px solid var(--ui-border-soft);
  border-radius: 12px;
  background: color-mix(in srgb, var(--ui-surface-1) 94%, transparent 6%);
  padding: 10px 12px;
  transition: transform 0.2s ease, box-shadow 0.2s ease, border-color 0.2s ease;
}

.capability-card:hover {
  transform: translateY(-1px);
  box-shadow: var(--ui-shadow-soft);
}

.capability-card.active {
  border-color: color-mix(in srgb, var(--el-color-success) 40%, var(--ui-border-soft) 60%);
  box-shadow: 0 10px 20px rgb(36 181 113 / 10%);
}

.capability-state-dot {
  width: 8px;
  height: 8px;
  border-radius: 999px;
  background: var(--el-color-info-light-5);
  box-shadow: 0 0 0 4px color-mix(in srgb, var(--el-color-info-light-9) 60%, transparent 40%);
}

.capability-card.active .capability-state-dot {
  background: var(--el-color-success);
  box-shadow: 0 0 0 4px color-mix(in srgb, var(--el-color-success-light-8) 60%, transparent 40%);
}

.capability-main {
  min-width: 0;
  flex: 1;
  display: grid;
  gap: 2px;
}

.capability-main strong {
  font-size: var(--font-size-sm);
}

.capability-main span {
  color: var(--el-text-color-secondary);
  font-size: var(--font-size-xs);
}
</style>
