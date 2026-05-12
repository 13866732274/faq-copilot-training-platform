export type RoleType = 'super_admin' | 'admin' | 'student'

export interface MenuItem {
  key: string
  label: string
  path?: string
  icon: string
  children?: MenuItem[]
}

export interface AdminMenuItem extends MenuItem {
  minRole: 'admin' | 'super_admin'
  configurable: boolean
  children?: AdminMenuItem[]
}

export const ADMIN_MENUS: AdminMenuItem[] = [
  {
    key: 'dashboard',
    label: '首页',
    path: '/admin/dashboard',
    icon: 'HomeFilled',
    minRole: 'admin',
    configurable: false,
  },
  {
    key: 'quiz-group',
    label: '案例库管理',
    icon: 'Document',
    minRole: 'admin',
    configurable: false,
    children: [
      {
        key: 'quiz-import',
        label: '导入案例',
        path: '/admin/quizzes/import',
        icon: 'UploadFilled',
        minRole: 'admin',
        configurable: true,
      },
      {
        key: 'quiz-list',
        label: '案例管理',
        path: '/admin/quizzes',
        icon: 'Document',
        minRole: 'admin',
        configurable: true,
      },
      {
        key: 'quiz-taxonomy',
        label: '分类标签中心',
        path: '/admin/quizzes/taxonomy',
        icon: 'Document',
        minRole: 'admin',
        configurable: true,
      },
    ],
  },
  {
    key: 'org-group',
    label: '组织管理',
    icon: 'OfficeBuilding',
    minRole: 'admin',
    configurable: false,
    children: [
      {
        key: 'user-manage',
        label: '用户管理',
        path: '/admin/users',
        icon: 'UserFilled',
        minRole: 'admin',
        configurable: true,
      },
      {
        key: 'hospital-manage',
        label: '医院管理',
        path: '/admin/hospitals',
        icon: 'OfficeBuilding',
        minRole: 'admin',
        configurable: true,
      },
      {
        key: 'department-manage',
        label: '科室管理',
        path: '/admin/departments',
        icon: 'Operation',
        minRole: 'admin',
        configurable: true,
      },
    ],
  },
  {
    key: 'faq-group',
    label: 'FAQ 知识库',
    icon: 'ChatLineSquare',
    minRole: 'admin',
    configurable: false,
    children: [
      {
        key: 'faq-dashboard',
        label: 'FAQ 概览',
        path: '/admin/faq',
        icon: 'DataBoard',
        minRole: 'admin',
        configurable: true,
      },
      {
        key: 'faq-clusters',
        label: '知识条目',
        path: '/admin/faq/clusters',
        icon: 'Collection',
        minRole: 'admin',
        configurable: true,
      },
      {
        key: 'faq-copilot',
        label: 'AI 问答助手',
        path: '/admin/faq/copilot',
        icon: 'ChatDotRound',
        minRole: 'admin',
        configurable: true,
      },
      {
        key: 'faq-tasks',
        label: '处理任务',
        path: '/admin/faq/tasks',
        icon: 'Loading',
        minRole: 'admin',
        configurable: true,
      },
      {
        key: 'faq-copilot-logs',
        label: 'AI调用统计',
        path: '/admin/faq/copilot-logs',
        icon: 'Document',
        minRole: 'admin',
        configurable: true,
      },
    ],
  },
  {
    key: 'stats',
    label: '统计面板',
    path: '/admin/stats',
    icon: 'DataAnalysis',
    minRole: 'admin',
    configurable: true,
  },
  {
    key: 'system-settings',
    label: '系统设置',
    path: '/admin/system/settings',
    icon: 'Setting',
    minRole: 'admin',
    configurable: false,
  },
  {
    key: 'permission-policy-diagnostics',
    label: '权限策略诊断',
    path: '/admin/system/permission-diagnostics',
    icon: 'Warning',
    minRole: 'super_admin',
    configurable: false,
  },
  {
    key: 'tenant-manage',
    label: '租户管理',
    path: '/admin/system/tenants',
    icon: 'OfficeBuilding',
    minRole: 'super_admin',
    configurable: false,
  },
  {
    key: 'billing-center',
    label: '计费中心',
    path: '/admin/system/billing',
    icon: 'DataBoard',
    minRole: 'super_admin',
    configurable: false,
  },
  {
    key: 'export-center',
    label: '数据导出',
    path: '/admin/system/exports',
    icon: 'Download',
    minRole: 'admin',
    configurable: true,
  },
  {
    key: 'audit-logs',
    label: '审计日志',
    path: '/admin/audit-logs',
    icon: 'List',
    minRole: 'super_admin',
    configurable: false,
  },
  {
    key: 'permission-audit',
    label: '权限体检',
    path: '/admin/permission-audit',
    icon: 'CircleCheck',
    minRole: 'super_admin',
    configurable: false,
  },
]

export const STUDENT_MENUS: MenuItem[] = [
  {
    key: 'practice-faq-copilot',
    label: 'AI 问答助手',
    path: '/practice/faq-copilot',
    icon: 'Document',
  },
]

const flattenAdminMenus = (menus: AdminMenuItem[]): AdminMenuItem[] => {
  return menus.flatMap((menu) => {
    const children = menu.children && menu.children.length > 0 ? flattenAdminMenus(menu.children) : []
    return [...children, menu]
  })
}

const ADMIN_LEAF_MENUS = flattenAdminMenus(ADMIN_MENUS).filter((menu) => !menu.children?.length && Boolean(menu.path))

export const CONFIGURABLE_MENUS = ADMIN_LEAF_MENUS.filter((menu) => menu.configurable)
export const CONFIGURABLE_MENU_KEYS = CONFIGURABLE_MENUS.map((menu) => menu.key)

export interface MenuPermissionTemplate {
  key: string
  label: string
  menuKeys: string[]
}

export const MENU_PERMISSION_TEMPLATES: MenuPermissionTemplate[] = [
  {
    key: 'dialog-faq',
    label: '对话 + FAQ（推荐）',
    menuKeys: [
      'quiz-import',
      'quiz-list',
      'quiz-taxonomy',
      'faq-dashboard',
      'faq-clusters',
      'faq-copilot',
      'faq-tasks',
      'faq-copilot-logs',
    ],
  },
  {
    key: 'all-management',
    label: '全管理',
    menuKeys: [...CONFIGURABLE_MENU_KEYS],
  },
  {
    key: 'quiz-operator',
    label: '案例库运营',
    menuKeys: ['quiz-import', 'quiz-list', 'stats'],
  },
  {
    key: 'org-operator',
    label: '人员管理',
    menuKeys: ['user-manage', 'hospital-manage', 'department-manage', 'stats'],
  },
]

export function pathToMenuKey(path: string): string | null {
  if (path.startsWith('/admin/quizzes/import')) return 'quiz-import'
  if (path.startsWith('/admin/quizzes/taxonomy')) return 'quiz-taxonomy'
  if (path.startsWith('/admin/quizzes')) return 'quiz-list'
  if (path.startsWith('/admin/users')) return 'user-manage'
  if (path.startsWith('/admin/hospitals')) return 'hospital-manage'
  if (path.startsWith('/admin/departments')) return 'department-manage'
  if (path.startsWith('/admin/faq/copilot-logs')) return 'faq-copilot-logs'
  if (path.startsWith('/admin/faq/copilot')) return 'faq-copilot'
  if (path.startsWith('/admin/faq/tasks')) return 'faq-tasks'
  if (path.startsWith('/admin/faq/clusters')) return 'faq-clusters'
  if (path.startsWith('/admin/faq')) return 'faq-dashboard'
  if (path.startsWith('/admin/stats')) return 'stats'
  if (path.startsWith('/admin/system/settings')) return 'system-settings'
  if (path.startsWith('/admin/system/permission-diagnostics')) return 'permission-policy-diagnostics'
  if (path.startsWith('/admin/system/tenants')) return 'tenant-manage'
  if (path.startsWith('/admin/system/billing')) return 'billing-center'
  if (path.startsWith('/admin/system/exports')) return 'export-center'
  if (path.startsWith('/admin/audit-logs')) return 'audit-logs'
  if (path.startsWith('/admin/permission-audit')) return 'permission-audit'
  if (path.startsWith('/admin/dashboard')) return 'dashboard'
  if (path.startsWith('/practice/faq-copilot')) return 'practice-faq-copilot'
  if (path.startsWith('/practice')) return 'practice'
  if (path.startsWith('/records')) return 'records'
  return null
}

export const MENU_MODULE_MAP: Record<string, string> = {
  'quiz-import': 'mod_training',
  'quiz-list': 'mod_training',
  'quiz-taxonomy': 'mod_training',
  'practice-faq-copilot': 'mod_faq',
  practice: 'mod_training',
  records: 'mod_training',
  'faq-dashboard': 'mod_faq',
  'faq-clusters': 'mod_faq',
  'faq-copilot': 'mod_faq',
  'faq-copilot-logs': 'mod_faq',
  'faq-tasks': 'mod_faq',
  stats: 'mod_stats',
  'export-center': 'mod_export',
  'audit-logs': 'mod_audit',
}

export function hasModuleAccess(
  menuKey: string,
  enabledModules: string[] | null | undefined,
  isPlatformSuperAdmin = false,
): boolean {
  if (isPlatformSuperAdmin) return true
  const moduleId = MENU_MODULE_MAP[menuKey]
  if (!moduleId) return true
  const modules = enabledModules || []
  return modules.includes(moduleId)
}

export function hasMenuAccess(
  role: string | undefined,
  menuPermissions: string[] | null | undefined,
  menuKey: string,
): boolean {
  if (!role) return false
  const menu = ADMIN_LEAF_MENUS.find((item) => item.key === menuKey)
  if (menu) {
    if (menu.minRole === 'super_admin' && role !== 'super_admin') return false
    if (role === 'super_admin') return true
    if (role !== 'admin') return false
    if (!menu.configurable) return true
    if (!menuPermissions) return true
    if (menuKey === 'quiz-taxonomy' && menuPermissions.includes('quiz-list')) return true
    return menuPermissions.includes(menuKey)
  }
  if (menuKey === 'practice-faq-copilot' || menuKey === 'practice' || menuKey === 'records') return role === 'student'
  return true
}
