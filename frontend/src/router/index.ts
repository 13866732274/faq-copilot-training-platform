import { createRouter, createWebHistory } from 'vue-router'
import { getCurrentUser, getToken, setLastRoute } from '../utils/auth'
import { useUserStore } from '../stores/user'
import { hasMenuAccess, hasModuleAccess, pathToMenuKey } from '../constants/menus'
import { ensurePermissionPoliciesLoaded, evaluateMenuAccess } from '../utils/permissionPoints'
import { pushGlobalNotice } from '../utils/globalNotice'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      redirect: '/login',
    },
    {
      path: '/login',
      name: 'login',
      component: () => import('../views/login/LoginView.vue'),
    },
    {
      path: '/admin',
      component: () => import('../components/layout/AdminLayout.vue'),
      meta: { requiresAuth: true, roles: ['admin', 'super_admin'], breadcrumbTitle: '后台管理' },
      children: [
        {
          path: 'dashboard',
          name: 'admin-dashboard',
          meta: { breadcrumbTitle: '首页' },
          component: () => import('../views/dashboard/AdminDashboardView.vue'),
        },
        {
          path: 'quizzes/import',
          name: 'admin-quiz-import',
          meta: { breadcrumbTitle: '导入案例' },
          component: () => import('../views/admin/AdminImportView.vue'),
        },
        {
          path: 'quizzes',
          name: 'admin-quiz-list',
          meta: { breadcrumbTitle: '案例库管理' },
          component: () => import('../views/admin/AdminQuizListView.vue'),
        },
        {
          path: 'quizzes/taxonomy',
          name: 'admin-quiz-taxonomy',
          meta: { breadcrumbTitle: '分类标签中心' },
          component: () => import('../views/admin/AdminQuizTaxonomyView.vue'),
        },
        {
          path: 'quizzes/:id',
          name: 'admin-quiz-detail',
          meta: { breadcrumbTitle: '案例详情', breadcrumbTo: '/admin/quizzes' },
          component: () => import('../views/admin/AdminQuizDetailView.vue'),
        },
        {
          path: 'users',
          name: 'admin-users',
          meta: { breadcrumbTitle: '用户管理' },
          component: () => import('../views/admin/AdminUserManageView.vue'),
        },
        {
          path: 'hospitals',
          name: 'admin-hospitals',
          meta: { breadcrumbTitle: '医院管理' },
          component: () => import('../views/admin/AdminHospitalManageView.vue'),
        },
        {
          path: 'departments',
          name: 'admin-departments',
          meta: { breadcrumbTitle: '科室管理' },
          component: () => import('../views/admin/AdminDepartmentManageView.vue'),
        },
        {
          path: 'stats',
          name: 'admin-stats',
          meta: { breadcrumbTitle: '统计分析' },
          component: () => import('../views/admin/AdminStatsView.vue'),
        },
        {
          path: 'system/settings',
          name: 'admin-system-settings',
          meta: { breadcrumbTitle: '系统设置' },
          component: () => import('../views/admin/AdminSystemSettingsView.vue'),
        },
        {
          path: 'system/permission-diagnostics',
          name: 'admin-permission-policy-diagnostics',
          meta: { roles: ['super_admin'], breadcrumbTitle: '权限策略诊断', breadcrumbTo: '/admin/system/settings' },
          component: () => import('../views/admin/AdminPermissionPolicyDiagnosticsView.vue'),
        },
        {
          path: 'system/tenants',
          name: 'admin-tenant-manage',
          meta: { roles: ['super_admin'], breadcrumbTitle: '租户管理' },
          component: () => import('../views/admin/AdminTenantManageView.vue'),
        },
        {
          path: 'system/exports',
          name: 'admin-export-center',
          meta: { breadcrumbTitle: '数据导出' },
          component: () => import('../views/admin/AdminExportCenterView.vue'),
        },
        {
          path: 'system/billing',
          name: 'admin-billing-center',
          meta: { roles: ['super_admin'], breadcrumbTitle: '计费中心' },
          component: () => import('../views/admin/AdminBillingCenterView.vue'),
        },
        {
          path: 'stats/:userId',
          name: 'admin-student-detail',
          meta: { breadcrumbTitle: '咨询员详情', breadcrumbTo: '/admin/stats' },
          component: () => import('../views/admin/AdminStudentDetailView.vue'),
        },
        {
          path: 'audit-logs',
          name: 'admin-audit-logs',
          meta: { roles: ['super_admin'], breadcrumbTitle: '审计日志' },
          component: () => import('../views/admin/AdminAuditLogView.vue'),
        },
        {
          path: 'permission-audit',
          name: 'admin-permission-audit',
          meta: { roles: ['super_admin'], breadcrumbTitle: '权限体检' },
          component: () => import('../views/admin/AdminPermissionAuditView.vue'),
        },
        {
          path: 'faq',
          name: 'admin-faq-dashboard',
          meta: { breadcrumbTitle: 'FAQ 知识库' },
          component: () => import('../views/admin/FaqDashboardView.vue'),
        },
        {
          path: 'faq/clusters',
          name: 'admin-faq-clusters',
          meta: { breadcrumbTitle: 'FAQ 条目', breadcrumbTo: '/admin/faq' },
          component: () => import('../views/admin/FaqClusterListView.vue'),
        },
        {
          path: 'faq/clusters/:id',
          name: 'admin-faq-cluster-detail',
          meta: { breadcrumbTitle: 'FAQ 详情', breadcrumbTo: '/admin/faq/clusters' },
          component: () => import('../views/admin/FaqClusterDetailView.vue'),
        },
        {
          path: 'faq/tasks',
          name: 'admin-faq-tasks',
          meta: { breadcrumbTitle: '处理任务', breadcrumbTo: '/admin/faq' },
          component: () => import('../views/admin/FaqTaskListView.vue'),
        },
        {
          path: 'faq/copilot',
          name: 'admin-faq-copilot',
          meta: { breadcrumbTitle: 'AI 问答助手', breadcrumbTo: '/admin/faq' },
          component: () => import('../views/admin/FaqCopilotView.vue'),
        },
        {
          path: 'faq/copilot-logs',
          name: 'admin-faq-copilot-logs',
          meta: { breadcrumbTitle: '查询日志', breadcrumbTo: '/admin/faq' },
          component: () => import('../views/admin/FaqCopilotLogsView.vue'),
        },
      ],
    },
    {
      path: '/practice',
      component: () => import('../components/layout/AdminLayout.vue'),
      meta: { requiresAuth: true, roles: ['student'], breadcrumbTitle: 'AI问答工作台' },
      children: [
        {
          path: '',
          redirect: '/practice/faq-copilot',
        },
        {
          path: 'faq-copilot',
          name: 'practice-faq-copilot',
          meta: { breadcrumbTitle: 'AI 问答助手' },
          component: () => import('../views/practice/PracticeFaqCopilotView.vue'),
        },
        {
          path: 'dashboard',
          name: 'practice-dashboard',
          meta: { breadcrumbTitle: 'AI问答看板' },
          component: () => import('../views/practice/PracticeDashboardView.vue'),
        },
        {
          path: 'list',
          name: 'practice-list',
          meta: { breadcrumbTitle: '案例库列表' },
          component: () => import('../views/practice/PracticeListView.vue'),
        },
        {
          path: ':id/chat',
          name: 'practice-chat',
          meta: { breadcrumbTitle: '对话会话', breadcrumbTo: '/practice/list' },
          component: () => import('../views/practice/PracticeChatView.vue'),
        },
        {
          path: ':id/review',
          name: 'practice-review',
          meta: { breadcrumbTitle: '历史回看', breadcrumbTo: '/records' },
          component: () => import('../views/practice/PracticeReviewView.vue'),
        },
      ],
    },
    {
      path: '/records',
      component: () => import('../components/layout/AdminLayout.vue'),
      meta: { requiresAuth: true, roles: ['student'], breadcrumbTitle: '我的记录' },
      children: [
        {
          path: '',
          name: 'record-list',
          meta: { breadcrumbTitle: '记录列表' },
          component: () => import('../views/record/MyRecordView.vue'),
        },
        {
          path: ':id',
          name: 'record-detail',
          meta: { breadcrumbTitle: '记录详情' },
          component: () => import('../views/record/RecordDetailView.vue'),
        },
      ],
    },
    {
      path: '/profile',
      component: () => import('../components/layout/AdminLayout.vue'),
      meta: { requiresAuth: true, breadcrumbTitle: '个人中心' },
      children: [
        {
          path: '',
          name: 'profile',
          meta: { breadcrumbTitle: '个人信息' },
          component: () => import('../views/profile/ProfileView.vue'),
        },
      ],
    },
    {
      path: '/:pathMatch(.*)*',
      redirect: '/login',
    },
  ],
})

router.beforeEach(async (to) => {
  if (!to.meta.requiresAuth) return true

  const token = getToken()
  if (!token) {
    pushGlobalNotice({
      title: '登录状态已失效，请重新登录',
      type: 'warning',
      duration: 3000,
      detail: `访问受保护页面时未检测到有效令牌。目标地址：${to.fullPath}`,
      errorCode: 'AUTH-TOKEN-MISSING',
    })
    return { name: 'login', query: { redirect: to.fullPath } }
  }

  const userStore = useUserStore()
  let user = getCurrentUser()
  if (!user && token) {
    try {
      user = await userStore.fetchMe()
    } catch {
      pushGlobalNotice({
        title: '登录状态已失效，请重新登录',
        type: 'warning',
        duration: 3000,
        detail: `用户信息校验失败，可能是令牌已过期。目标地址：${to.fullPath}`,
        errorCode: 'AUTH-ME-FAILED',
      })
      return { name: 'login' }
    }
  }

  const allowedRoles = (to.meta.roles as string[] | undefined) || []
  if (allowedRoles.length > 0) {
    const role = user?.role || ''
    if (!allowedRoles.includes(role)) {
      // 角色目标页纠偏：管理员误访问咨询员页时，自动回到 FAQ。
      if ((role === 'admin' || role === 'super_admin') && to.path.startsWith('/practice')) {
        return { path: '/admin/faq' }
      }
      pushGlobalNotice({
        title: '当前账号无权访问该页面，已为你切换到可访问页面',
        type: 'warning',
        duration: 3000,
        detail: `角色校验失败。当前角色：${role || 'unknown'}，允许角色：${allowedRoles.join(', ') || '-'}`,
        errorCode: 'RBAC-ROLE-DENY',
      })
      if (role === 'student') return { path: '/practice/faq-copilot' }
      if (role === 'admin' || role === 'super_admin') return { path: '/admin/dashboard' }
      return { name: 'login' }
    }
  }

  const role = user?.role || ''
  if (role === 'student' && to.path.startsWith('/practice') && !to.path.startsWith('/practice/faq-copilot')) {
    return { path: '/practice/faq-copilot' }
  }

  const menuKey = pathToMenuKey(to.path)
  if (menuKey && user) {
    const hasModule = hasModuleAccess(
      menuKey,
      user.enabled_modules || [],
      Boolean(user.is_platform_super_admin),
    )
    if (!hasModule) {
      pushGlobalNotice({
        title: '当前租户未开通该模块，已为你切换到工作台',
        type: 'warning',
        duration: 3000,
        detail: `模块开关校验失败。菜单键：${menuKey}`,
        errorCode: 'SAAS-MODULE-DENY',
      })
      if (user.role === 'student') {
        // Avoid self-redirect loops when /practice itself is blocked by module switch.
        if (to.path.startsWith('/practice')) return { name: 'login' }
        return { path: '/practice/faq-copilot' }
      }
      if (user.role === 'admin' || user.role === 'super_admin') return { path: '/admin/dashboard' }
      return { name: 'login' }
    }
    // 咨询员页只走角色+模块校验，不依赖后台菜单权限点，避免误拦截。
    if (user.role === 'student') return true
    try {
      await ensurePermissionPoliciesLoaded()
    } catch {
      // ignore and continue with current snapshot
    }
    const menuDecision = evaluateMenuAccess(menuKey)
    // 降级策略：权限策略接口短时失败/未就绪时，使用登录态快照兜底，避免误判拒绝
    const fallbackAllowed =
      user.role === 'super_admin'
      || (menuDecision.reason?.includes('权限点加载中') && hasMenuAccess(user.role, user.menu_permissions, menuKey))
    if (!menuDecision.allowed && !fallbackAllowed) {
      pushGlobalNotice({
        title: '当前账号无权访问该功能，已为你切换到工作台',
        type: 'warning',
        duration: 3000,
        detail: menuDecision.reason || `菜单权限校验失败。菜单键：${menuKey}，当前角色：${user.role}`,
        errorCode: 'RBAC-MENU-DENY',
      })
      if (user.role === 'admin' || user.role === 'super_admin') return { path: '/admin/dashboard' }
      return { name: 'login' }
    }
  }
  return true
})

router.afterEach((to) => {
  if (
    to.path.startsWith('/admin') ||
    to.path.startsWith('/practice') ||
    to.path.startsWith('/records') ||
    to.path.startsWith('/profile')
  ) {
    const full = to.fullPath || to.path
    setLastRoute(full)
  }
})

export default router
