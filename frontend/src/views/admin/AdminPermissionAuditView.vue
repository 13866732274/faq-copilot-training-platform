<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { WarningFilled } from '@element-plus/icons-vue'
import {
  getPermissionAudit,
  fixPermissionAudit,
  type PermissionAuditData,
  type ConfigurableMenuAuditEntry,
} from '../../api/permissionAudit'

const loading = ref(false)
const fixing = ref(false)
const auditData = ref<PermissionAuditData | null>(null)
const expandedUser = ref<number | null>(null)

const MENU_LABEL_MAP: Record<string, string> = {
  'dashboard': '首页',
  'quiz-import': '导入案例',
  'quiz-list': '案例管理',
  'quiz-taxonomy': '分类标签中心',
  'user-manage': '用户管理',
  'hospital-manage': '医院管理',
  'department-manage': '科室管理',
  'stats': '统计面板',
  'system-settings': '系统设置',
  'tenant-manage': '租户管理',
  'billing-center': '计费中心',
  'export-center': '数据导出',
  'audit-logs': '审计日志',
  'practice': '模拟练习',
  'records': '我的记录',
}

const menuLabel = (key: string) => MENU_LABEL_MAP[key] || key

const modeLabel = (mode: string) => {
  if (mode === 'default_all') return '默认放行（全部菜单）'
  if (mode === 'custom') return '定制权限'
  if (mode === 'invalid_json') return 'JSON 格式异常'
  return mode
}

const modeType = (mode: string) => {
  if (mode === 'default_all') return 'warning'
  if (mode === 'custom') return 'primary'
  if (mode === 'invalid_json') return 'danger'
  return 'info'
}

const items = computed(() => auditData.value?.items || [])
const summary = computed(() => auditData.value?.summary || null)

const canFix = computed(() => {
  if (!summary.value) return false
  return summary.value.missing_quiz_taxonomy_explicit > 0
})

const load = async () => {
  loading.value = true
  try {
    auditData.value = await getPermissionAudit()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '加载权限审计数据失败')
  } finally {
    loading.value = false
  }
}

const toggleDetail = (userId: number) => {
  expandedUser.value = expandedUser.value === userId ? null : userId
}

const handleFix = async () => {
  try {
    await ElMessageBox.confirm(
      '将为所有拥有「案例管理」权限但数据库中缺少「分类标签中心」的账号，自动写入 quiz-taxonomy 权限。\n\n此操作不可撤销，确认执行？',
      '一键修复确认',
      { confirmButtonText: '执行修复', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }
  fixing.value = true
  try {
    const result = await fixPermissionAudit()
    if (result.fixed_count > 0) {
      ElMessage.success(`已修复 ${result.fixed_count} 个账号`)
    } else {
      ElMessage.info('无需修复，所有账号权限正常')
    }
    await load()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '修复失败')
  } finally {
    fixing.value = false
  }
}

const entryIcon = (entry: ConfigurableMenuAuditEntry) => {
  if (entry.via_compat) return '⚠️'
  if (entry.runtime_allowed) return '✅'
  return '❌'
}

const entryNote = (entry: ConfigurableMenuAuditEntry) => {
  if (entry.via_compat) return '兼容逻辑隐式放行'
  if (entry.in_db === null) return '默认放行'
  if (entry.runtime_allowed && entry.in_db) return '数据库显式授权'
  if (!entry.runtime_allowed && !entry.in_db) return '未授权'
  return ''
}

onMounted(load)
</script>

<template>
  <el-card shadow="never" v-loading="loading" class="audit-card">
    <template #header>
      <div class="admin-card-header">
        <div class="audit-header-main">
          <strong class="admin-card-title">权限体检中心</strong>
          <p class="audit-header-desc">全面审计管理员账号的菜单权限配置，数据库实际值 vs 运行时判定结果一目了然。</p>
        </div>
        <div class="admin-card-header-actions">
          <el-button @click="load" :loading="loading">刷新</el-button>
          <el-button
            v-if="canFix"
            type="warning"
            :loading="fixing"
            @click="handleFix"
          >
            一键修复缺失权限
          </el-button>
        </div>
      </div>
    </template>

    <div v-if="summary" class="summary-grid">
      <div class="summary-item">
        <div class="summary-number">{{ summary.total }}</div>
        <div class="summary-label">管理员总数</div>
      </div>
      <div class="summary-item">
        <div class="summary-number active-num">{{ summary.active }}</div>
        <div class="summary-label">活跃账号</div>
      </div>
      <div class="summary-item">
        <div class="summary-number" :class="{ 'warn-num': summary.inactive > 0 }">{{ summary.inactive }}</div>
        <div class="summary-label">已禁用</div>
      </div>
      <div class="summary-item">
        <div class="summary-number" :class="{ 'warn-num': summary.default_all > 0 }">{{ summary.default_all }}</div>
        <div class="summary-label">默认放行</div>
      </div>
      <div class="summary-item">
        <div class="summary-number">{{ summary.custom }}</div>
        <div class="summary-label">定制权限</div>
      </div>
      <div class="summary-item">
        <div class="summary-number" :class="{ 'danger-num': summary.invalid_json > 0 }">{{ summary.invalid_json }}</div>
        <div class="summary-label">JSON 异常</div>
      </div>
      <div class="summary-item">
        <div class="summary-number" :class="{ 'warn-num': summary.has_issues > 0 }">{{ summary.has_issues }}</div>
        <div class="summary-label">有告警</div>
      </div>
      <div class="summary-item">
        <div class="summary-number" :class="{ 'warn-num': summary.missing_quiz_taxonomy_explicit > 0 }">{{ summary.missing_quiz_taxonomy_explicit }}</div>
        <div class="summary-label">隐式taxonomy</div>
      </div>
    </div>

    <el-table :data="items" stripe class="audit-table" row-key="user_id">
      <el-table-column label="ID" prop="user_id" width="60" />
      <el-table-column label="用户名" prop="username" width="140" />
      <el-table-column label="姓名" prop="real_name" width="120" />
      <el-table-column label="角色" width="120">
        <template #default="{ row }">
          <el-tag :type="row.role === 'super_admin' ? 'danger' : 'primary'" size="small">
            {{ row.role === 'super_admin' ? '超级管理员' : '管理员' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="80">
        <template #default="{ row }">
          <el-tag :type="row.is_active ? 'success' : 'info'" size="small">
            {{ row.is_active ? '活跃' : '禁用' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="权限模式" width="200">
        <template #default="{ row }">
          <el-tag :type="modeType(row.permission_mode)" size="small">
            {{ modeLabel(row.permission_mode) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="告警" width="80">
        <template #default="{ row }">
          <el-badge v-if="row.issue_count > 0" :value="row.issue_count" type="warning" class="issue-badge" />
          <span v-else class="no-issue">0</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="100">
        <template #default="{ row }">
          <el-button link type="primary" size="small" @click="toggleDetail(row.user_id)">
            {{ expandedUser === row.user_id ? '收起' : '详情' }}
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <template v-for="user in items" :key="'detail-' + user.user_id">
      <transition name="audit-expand">
        <div v-if="expandedUser === user.user_id" class="user-detail-panel">
          <div class="detail-section">
            <div class="detail-section-title">菜单权限审计 — {{ user.real_name }}（{{ user.username }}）</div>

            <div v-if="user.issues.length > 0" class="issue-list">
              <div v-for="(issue, idx) in user.issues" :key="idx" class="issue-item">
                <el-icon class="issue-icon"><WarningFilled /></el-icon>
                {{ issue }}
              </div>
            </div>
            <div v-else class="no-issue-msg">无告警，权限配置正常。</div>

            <div class="detail-section-title mt-3">可配置菜单权限对照</div>
            <el-table :data="user.configurable_menu_audit" size="small" border class="menu-audit-table">
              <el-table-column label="菜单" width="160">
                <template #default="{ row: entry }">
                  {{ menuLabel(entry.menu_key) }}
                  <span class="menu-key-hint">{{ entry.menu_key }}</span>
                </template>
              </el-table-column>
              <el-table-column label="运行时" width="90" align="center">
                <template #default="{ row: entry }">
                  <span>{{ entryIcon(entry) }}</span>
                </template>
              </el-table-column>
              <el-table-column label="数据库" width="90" align="center">
                <template #default="{ row: entry }">
                  <span v-if="entry.in_db === null">—</span>
                  <span v-else-if="entry.in_db">✅</span>
                  <span v-else>❌</span>
                </template>
              </el-table-column>
              <el-table-column label="说明">
                <template #default="{ row: entry }">
                  <el-tag v-if="entry.via_compat" type="warning" size="small">{{ entryNote(entry) }}</el-tag>
                  <span v-else class="entry-note">{{ entryNote(entry) }}</span>
                </template>
              </el-table-column>
            </el-table>

            <div class="detail-section-title mt-3">原始 menu_permissions（数据库值）</div>
            <div class="raw-json">
              <code>{{ user.raw_menu_permissions ?? 'null' }}</code>
            </div>
          </div>
        </div>
      </transition>
    </template>
  </el-card>
</template>

<style scoped>
.audit-card {
  position: relative;
}

.audit-header-main {
  display: grid;
  gap: 4px;
}

.audit-header-desc {
  margin: 0;
  color: var(--el-text-color-secondary);
  font-size: var(--font-size-xs);
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
  gap: var(--space-2);
  margin-bottom: var(--space-4);
}

.summary-item {
  text-align: center;
  padding: 12px 8px;
  border-radius: 12px;
  border: 1px solid var(--ui-border-soft);
  background: var(--ui-surface-1);
}

.summary-number {
  font-size: 24px;
  font-weight: 700;
  line-height: 1.2;
  color: var(--el-text-color-primary);
}

.summary-number.active-num {
  color: var(--el-color-success);
}

.summary-number.warn-num {
  color: var(--el-color-warning);
}

.summary-number.danger-num {
  color: var(--el-color-danger);
}

.summary-label {
  margin-top: 4px;
  font-size: var(--font-size-xs);
  color: var(--el-text-color-secondary);
}

.audit-table {
  margin-bottom: var(--space-2);
}

.issue-badge {
  cursor: default;
}

.no-issue {
  color: var(--el-text-color-placeholder);
}

.user-detail-panel {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 10px;
  padding: var(--space-3);
  margin-bottom: var(--space-2);
  background: var(--ui-surface-1);
}

.detail-section-title {
  font-weight: 600;
  font-size: var(--font-size-sm);
  margin-bottom: 8px;
}

.mt-3 {
  margin-top: var(--space-3);
}

.issue-list {
  display: grid;
  gap: 6px;
  margin-bottom: var(--space-2);
}

.issue-item {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--el-color-warning-dark-2);
  font-size: var(--font-size-sm);
  padding: 6px 10px;
  border-radius: 8px;
  background: color-mix(in srgb, var(--el-color-warning-light-9) 60%, transparent 40%);
}

.issue-icon {
  font-size: 16px;
  color: var(--el-color-warning);
  flex-shrink: 0;
}

.no-issue-msg {
  color: var(--el-color-success);
  font-size: var(--font-size-sm);
  padding: 6px 10px;
  border-radius: 8px;
  background: color-mix(in srgb, var(--el-color-success-light-9) 60%, transparent 40%);
  margin-bottom: var(--space-2);
}

.menu-audit-table {
  max-width: 600px;
}

.menu-key-hint {
  display: block;
  font-size: 11px;
  color: var(--el-text-color-placeholder);
  font-family: monospace;
}

.entry-note {
  font-size: var(--font-size-xs);
  color: var(--el-text-color-secondary);
}

.raw-json {
  padding: 10px 14px;
  border-radius: 8px;
  background: var(--el-fill-color-lighter);
  font-size: 12px;
  overflow-x: auto;
  max-width: 100%;
  word-break: break-all;
}

.raw-json code {
  font-family: 'Menlo', 'Consolas', monospace;
  color: var(--el-text-color-regular);
}

.audit-expand-enter-active,
.audit-expand-leave-active {
  transition: all 0.25s ease;
  overflow: hidden;
}

.audit-expand-enter-from,
.audit-expand-leave-to {
  opacity: 0;
  max-height: 0;
  transform: translateY(-8px);
}

.audit-expand-enter-to,
.audit-expand-leave-from {
  opacity: 1;
  max-height: 1200px;
}
</style>
