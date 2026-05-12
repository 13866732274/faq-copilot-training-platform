<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import type { InputInstance } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'
import {
  ArrowRight,
  Bell,
  ChatDotRound,
  ChatLineSquare,
  CircleCheck,
  Collection,
  DataAnalysis,
  DataBoard,
  Download,
  Document,
  HomeFilled,
  List,
  Loading as LoadingIcon,
  Menu,
  OfficeBuilding,
  Operation,
  Search,
  Setting,
  UploadFilled,
  UserFilled,
  WarningFilled,
} from '@element-plus/icons-vue'
import { useUserStore } from '../../stores/user'
import { useNotificationStore, type NoticeItem, type NoticeModule } from '../../stores/notification'
import { getThemeMode, setThemeMode, type ThemeMode } from '../../utils/theme'
import { getPublicSystemSettings, getSystemSettings } from '../../api/system'
import {
  ADMIN_MENUS,
  STUDENT_MENUS,
  hasModuleAccess,
  pathToMenuKey,
  type AdminMenuItem,
  type MenuItem,
} from '../../constants/menus'
import { createDebouncedFn } from '../../composables/useUiStandards'
import { getUsers } from '../../api/users'
import { getQuizList } from '../../api/quiz'
import { getAuditLogs } from '../../api/audit'
import { getAvailablePractices } from '../../api/practice'
import { applyRuntimeBrandAccent } from '../../utils/systemTheme'
import { applyPageTitle, onSiteTitleUpdate } from '../../utils/pageTitle'
import { pushGlobalNotice } from '../../utils/globalNotice'
import {
  broadcastFeatureFlagsUpdate,
  onFeatureFlagsUpdate,
  readFeatureFlagsCache,
  toFeatureFlags,
  type SystemFeatureFlags,
  writeFeatureFlagsCache,
} from '../../utils/systemFeatures'
import {
  evaluateMenuAccess,
  hasMenuAccessByPolicy,
  hasPermissionPoliciesLoaded,
  refreshPermissionPoints,
} from '../../utils/permissionPoints'
import { stopImpersonationApi } from '../../api/auth'
import { setAuth } from '../../utils/auth'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
const notificationStore = useNotificationStore()
const systemSiteName = ref('咨询话术模拟训练系统')
const systemSiteSubtitle = ref('运营管理中台')
const systemLogoUrl = ref('')
const currentTenantLabel = computed(() => userStore.user?.tenant_name || '未绑定租户')
const displayWorkbenchTitle = computed(() =>
  userStore.user?.role === 'student' ? 'AI问答工作台' : systemSiteSubtitle.value,
)
const breadcrumbHomeLabel = computed(() =>
  userStore.user?.role === 'student' ? 'AI问答工作台' : '工作台',
)
const SIDER_COLLAPSE_KEY = 'admin-sider-collapsed'
const COMMAND_PINNED_KEY = 'cmd-pinned-menu-ids'
const COMMAND_RECENT_KEY = 'cmd-recent-menu-items'
const COMMAND_RECENT_LIMIT = 8
const readSiderCollapsed = () => {
  if (typeof window === 'undefined') return false
  return window.localStorage.getItem(SIDER_COLLAPSE_KEY) === '1'
}
const isMobile = ref(false)
const drawerVisible = ref(false)
const siderCollapsed = ref(readSiderCollapsed())
const themeMode = ref<ThemeMode>(getThemeMode())
const commandDialogVisible = ref(false)
const commandKeyword = ref('')
const commandInputRef = ref<InputInstance | null>(null)
const commandPreviewCounts = ref<Record<string, number>>({})
const commandPreviewLoading = ref<Record<string, boolean>>({})
const commandActiveIndex = ref(-1)
const pinnedMenuIds = ref<string[]>([])
const recentMenuPaths = ref<string[]>([])
const featureFlags = ref<SystemFeatureFlags | null>(readFeatureFlagsCache())
const impersonationStopping = ref(false)
const nowMs = ref(Date.now())
let commandPreviewSeq = 0
let impersonationTimer: number | null = null
let unbindSiteTitleUpdate: (() => void) | null = null
let unbindFeatureFlagsUpdate: (() => void) | null = null
const iconMap: Record<string, any> = {
  HomeFilled,
  UploadFilled,
  Document,
  UserFilled,
  OfficeBuilding,
  Operation,
  DataAnalysis,
  Download,
  Setting,
  List,
  ChatDotRound,
  ChatLineSquare,
  DataBoard,
  Collection,
  Loading: LoadingIcon,
  CircleCheck,
  Warning: WarningFilled,
}

type LayoutMenuItem = MenuItem | AdminMenuItem

const menuHasVisibleLeaf = (menu: LayoutMenuItem): boolean => {
  if (menu.path) return true
  return Boolean(menu.children?.some((child) => menuHasVisibleLeaf(child)))
}

const filterAdminMenusByAccess = (
  menus: AdminMenuItem[],
  role: string,
): AdminMenuItem[] => {
  const isPlatformSuperAdmin = Boolean(userStore.user?.is_platform_super_admin)
  const enabledModules = userStore.user?.enabled_modules || []
  return menus.reduce<AdminMenuItem[]>((acc, menu) => {
    if (menu.minRole === 'super_admin' && (role !== 'super_admin' || !isPlatformSuperAdmin)) return acc
    if (menu.children?.length) {
      const children = filterAdminMenusByAccess(menu.children, role)
      if (children.length > 0) {
        acc.push({ ...menu, children })
      }
      return acc
    }
    if (!hasModuleAccess(menu.key, enabledModules, isPlatformSuperAdmin)) return acc
    if (hasMenuAccessByPolicy(menu.key)) {
      acc.push(menu)
    }
    return acc
  }, [])
}

const flattenMenus = <T extends LayoutMenuItem>(menus: T[]): T[] => {
  return menus.flatMap((menu): T[] => {
    const children = menu.children?.length ? flattenMenus(menu.children as T[]) : ([] as T[])
    return [...children, menu]
  })
}

const visibleMenus = computed<LayoutMenuItem[]>(() => {
  const role = userStore.user?.role
  if (!role) return []
  if (role === 'student') {
    const isPlatformSuperAdmin = Boolean(userStore.user?.is_platform_super_admin)
    const enabledModules = userStore.user?.enabled_modules || []
    return STUDENT_MENUS.filter((menu) => hasModuleAccess(menu.key, enabledModules, isPlatformSuperAdmin))
  }
  if (!hasPermissionPoliciesLoaded()) return []
  return filterAdminMenusByAccess(ADMIN_MENUS, role)
})

const visibleLeafMenus = computed<LayoutMenuItem[]>(() => {
  return flattenMenus(visibleMenus.value).filter((menu) => menu.path && menuHasVisibleLeaf(menu) && !menu.children?.length)
})

const normalizePath = (path: string) => (path.length > 1 && path.endsWith('/') ? path.replace(/\/+$/, '') : path)
const isPathMatched = (menuPath: string, currentPath: string) => {
  const m = normalizePath(menuPath)
  const c = normalizePath(currentPath)
  return c === m || c.startsWith(`${m}/`)
}

type BreadcrumbItem = { label: string; path?: string; ellipsis?: boolean }

const homePath = computed(() => (userStore.user?.role === 'student' ? '/practice/faq-copilot' : '/admin/dashboard'))

const activeLeafPath = computed(() => {
  const currentPath = route.path
  const candidates = visibleLeafMenus.value
    .filter((menu) => menu.path && isPathMatched(menu.path, currentPath))
    .sort((a, b) => (b.path?.length || 0) - (a.path?.length || 0))
  return candidates[0]?.path || ''
})

const menuChainByPath = (menus: LayoutMenuItem[], path: string): LayoutMenuItem[] => {
  const walk = (items: LayoutMenuItem[], parent: LayoutMenuItem[]): LayoutMenuItem[] | null => {
    for (const menu of items) {
      const chain = [...parent, menu]
      if (menu.path && normalizePath(menu.path) === normalizePath(path)) return chain
      if (menu.children?.length) {
        const nested = walk(menu.children, chain)
        if (nested) return nested
      }
    }
    return null
  }
  return walk(menus, []) || []
}

const currentRouteMeta = computed(() => route.matched[route.matched.length - 1]?.meta || {})

const breadcrumbBasePath = computed(() => {
  const meta = currentRouteMeta.value as { breadcrumbTo?: string }
  if (meta.breadcrumbTo) return meta.breadcrumbTo
  return activeLeafPath.value
})

const menuChain = computed(() => {
  if (!breadcrumbBasePath.value) return []
  return menuChainByPath(visibleMenus.value, breadcrumbBasePath.value)
})

const activeMenu = computed(() => activeLeafPath.value || homePath.value)

const openedMenuKeys = computed(() => {
  const chain = menuChainByPath(visibleMenus.value, activeMenu.value)
  return chain.filter((item) => item.children?.length).map((item) => item.key)
})

const resolveDynamicDetailLabel = () => {
  const meta = currentRouteMeta.value as { breadcrumbTitle?: string }
  const baseTitle = meta.breadcrumbTitle || '详情'
  const name = [
    route.query.title,
    route.query.name,
    route.query.quiz_title,
    route.query.user_name,
    route.query.label,
  ].find((item) => typeof item === 'string' && item.trim())
  const detailName = typeof name === 'string' ? name.trim() : ''
  const idVal = (route.params.id || route.params.userId || '') as string
  if (detailName) return `${baseTitle}（${detailName}）`
  if (idVal) return `${baseTitle} #${idVal}`
  return baseTitle
}

const breadcrumbItems = computed<BreadcrumbItem[]>(() => {
  const result: BreadcrumbItem[] = [{ label: breadcrumbHomeLabel.value, path: homePath.value }]
  const chain = menuChain.value
  if (chain.length) {
    chain.forEach((item) => {
      result.push({
        label: item.label,
        path: item.path,
      })
    })
  }
  const activeExact = activeLeafPath.value && normalizePath(activeLeafPath.value) === normalizePath(route.path)
  if (!activeExact) {
    result.push({ label: resolveDynamicDetailLabel() })
  }
  const compacted = result.filter((item, idx, arr) => idx === 0 || item.label !== arr[idx - 1]?.label)
  return compacted.length > 1 ? compacted : [...compacted, { label: '当前页面' }]
})

const currentPageTitle = computed(() => breadcrumbItems.value[breadcrumbItems.value.length - 1]?.label || '当前页面')
const isImpersonating = computed(() => Boolean(userStore.user?.is_impersonating))
const impersonationTenantName = computed(
  () => userStore.user?.impersonation_tenant_name || userStore.user?.tenant_name || '未知租户',
)
const impersonationReason = computed(() => userStore.user?.impersonation_reason || '未填写原因')
const impersonationExpiresAt = computed(() => userStore.user?.impersonation_expires_at || '')
const impersonationRemainSeconds = computed(() => {
  if (!isImpersonating.value || !impersonationExpiresAt.value) return 0
  const ts = new Date(impersonationExpiresAt.value).getTime()
  if (Number.isNaN(ts)) return 0
  return Math.max(0, Math.floor((ts - nowMs.value) / 1000))
})
const impersonationRemainText = computed(() => {
  const sec = impersonationRemainSeconds.value
  const min = Math.floor(sec / 60)
  const rem = sec % 60
  return `${String(min).padStart(2, '0')}:${String(rem).padStart(2, '0')}`
})

const condensedBreadcrumbItems = computed<BreadcrumbItem[]>(() => {
  const items = breadcrumbItems.value
  if (items.length <= 6) return items
  return [items[0]!, { label: '...', ellipsis: true }, ...items.slice(-3)]
})

const mobileBreadcrumbItems = computed<BreadcrumbItem[]>(() => {
  const items = breadcrumbItems.value
  if (items.length <= 2) return items
  return items.slice(-2)
})

const showBreadcrumb = computed(() => breadcrumbItems.value.length > 2)

const notificationFilter = ref<NoticeModule>('all')
const filteredNotificationItems = computed(() => {
  if (notificationFilter.value === 'all') return notificationStore.items
  return notificationStore.items.filter((item) => item.module === notificationFilter.value)
})

const siderWidth = computed(() => (siderCollapsed.value ? '64px' : '236px'))

type CommandAction = {
  id: string
  key: string
  label: string
  path: string
  keywords: string
  icon: any
  kind: 'menu' | 'search'
  query?: Record<string, string>
}

type CommandGroup = {
  key: 'pinned' | 'recent' | 'search' | 'menu'
  title: string
  items: CommandAction[]
}

const commandItems = computed<CommandAction[]>(() => {
  return visibleLeafMenus.value.map((menu) => ({
    id: `menu:${menu.key}`,
    key: menu.key,
    label: menu.label,
    path: menu.path || '',
    keywords: `${menu.label} ${menu.key} ${menu.path || ''}`.toLowerCase(),
    icon: iconMap[menu.icon],
    kind: 'menu' as const,
  }))
})

const searchCommandItems = computed<CommandAction[]>(() => {
  const kw = commandKeyword.value.trim().toLowerCase()
  if (!kw) return []
  const text = commandKeyword.value.trim()
  const actions: CommandAction[] = []
  const hasPath = (path: string) => visibleLeafMenus.value.some((menu) => menu.path === path)

  if (hasPath('/admin/users')) {
    actions.push({
      id: 'search:users',
      key: 'search_users',
      label: `搜索用户：${text}`,
      path: '/admin/users',
      query: { q: text },
      keywords: `用户 用户名 姓名 ${kw}`,
      icon: Search,
      kind: 'search',
    })
  }
  if (hasPath('/admin/quizzes')) {
    actions.push({
      id: 'search:quizzes',
      key: 'search_quizzes',
      label: `搜索案例库：${text}`,
      path: '/admin/quizzes',
      query: { q: text },
      keywords: `案例库 案例 标题 ${kw}`,
      icon: Search,
      kind: 'search',
    })
  }
  if (hasPath('/admin/audit-logs')) {
    actions.push({
      id: 'search:audit',
      key: 'search_audit',
      label: `搜索审计日志：${text}`,
      path: '/admin/audit-logs',
      query: { q: text },
      keywords: `审计 日志 操作人 ${kw}`,
      icon: Search,
      kind: 'search',
    })
  }
  if (hasPath('/practice')) {
    actions.push({
      id: 'search:practice',
      key: 'search_practice',
      label: `搜索训练案例：${text}`,
      path: '/practice/list',
      query: { q: text },
      keywords: `练习 案例 ${kw}`,
      icon: Search,
      kind: 'search',
    })
  }
  if (hasPath('/admin/faq/copilot')) {
    actions.push({
      id: 'search:faq',
      key: 'search_faq',
      label: `FAQ 智能问答：${text}`,
      path: '/admin/faq/copilot',
      query: { q: text },
      keywords: `faq 问答 知识库 咨询 患者 ${kw}`,
      icon: ChatDotRound,
      kind: 'search',
    })
  }
  return actions
})

const pinnedMenuItems = computed<CommandAction[]>(() => {
  const map = new Map(commandItems.value.map((item) => [item.id, item]))
  return pinnedMenuIds.value.map((id) => map.get(id)).filter((item): item is CommandAction => !!item)
})

const recentMenuItems = computed<CommandAction[]>(() => {
  const map = new Map(commandItems.value.map((item) => [item.path, item]))
  return recentMenuPaths.value.map((path) => map.get(path)).filter((item): item is CommandAction => !!item)
})

const groupedCommandItems = computed<CommandGroup[]>(() => {
  const kw = commandKeyword.value.trim().toLowerCase()
  const groups: CommandGroup[] = []
  const pinnedIds = new Set(pinnedMenuItems.value.map((item) => item.id))
  const recentIds = new Set(recentMenuItems.value.map((item) => item.id))

  if (kw) {
    const pinnedMatches = pinnedMenuItems.value.filter((item) => item.keywords.includes(kw))
    if (pinnedMatches.length) {
      groups.push({ key: 'pinned', title: '已收藏', items: pinnedMatches })
    }
    if (searchCommandItems.value.length) {
      groups.push({ key: 'search', title: '内容搜索', items: searchCommandItems.value })
    }
    const menuMatches = commandItems.value.filter((item) => item.keywords.includes(kw) && !pinnedIds.has(item.id))
    if (menuMatches.length) {
      groups.push({ key: 'menu', title: '菜单导航', items: menuMatches })
    }
    return groups
  }

  if (pinnedMenuItems.value.length) {
    groups.push({ key: 'pinned', title: '已收藏', items: pinnedMenuItems.value })
  }
  if (recentMenuItems.value.length) {
    groups.push({ key: 'recent', title: '最近访问', items: recentMenuItems.value.filter((item) => !pinnedIds.has(item.id)) })
  }
  const menuItems = commandItems.value.filter((item) => !pinnedIds.has(item.id) && !recentIds.has(item.id))
  if (menuItems.length) {
    groups.push({ key: 'menu', title: '菜单导航', items: menuItems })
  }
  return groups.filter((group) => group.items.length > 0)
})

const flatCommandItems = computed<CommandAction[]>(() => groupedCommandItems.value.flatMap((group) => group.items))

const formatPreviewCount = (item: CommandAction) => {
  if (item.kind !== 'search') return ''
  const loading = commandPreviewLoading.value[item.id]
  if (loading) return '统计中...'
  const total = commandPreviewCounts.value[item.id]
  if (typeof total === 'number') return total > 0 ? `约 ${total} 条` : '无匹配'
  return '无预估'
}

const isPreviewHit = (item: CommandAction) => {
  if (item.kind !== 'search') return false
  if (commandPreviewLoading.value[item.id]) return false
  return (commandPreviewCounts.value[item.id] || 0) > 0
}

const logout = () => {
  userStore.logout()
  router.replace('/login')
}

const stopImpersonationSession = async () => {
  if (!isImpersonating.value || impersonationStopping.value) return
  impersonationStopping.value = true
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
    ElMessage.success('已退出代入模式，恢复超级管理员身份')
    await router.replace('/admin/system/tenants')
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || '退出代入失败，请稍后重试')
  } finally {
    impersonationStopping.value = false
  }
}

const formatNoticeTime = (value: string) => {
  if (!value) return '--'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return '--'
  return d.toLocaleString('zh-CN', { hour12: false })
}

const formatNoticeModule = (module: NoticeItem['module']) => {
  if (module === 'import') return '导入'
  if (module === 'user') return '用户'
  if (module === 'audit') return '审计'
  return '系统'
}

const loadRuntimeSystemSettings = async () => {
  const role = userStore.user?.role
  const canReadTenantSettings = role === 'admin' || role === 'super_admin'
  try {
    if (canReadTenantSettings) {
      const data = await getSystemSettings()
      systemSiteName.value = data.site_name || systemSiteName.value
      systemSiteSubtitle.value = data.site_subtitle || systemSiteSubtitle.value
      systemLogoUrl.value = data.logo_url || ''
      applyRuntimeBrandAccent(data.brand_accent)
      const flags = toFeatureFlags(data)
      featureFlags.value = flags
      writeFeatureFlagsCache(flags)
      broadcastFeatureFlagsUpdate(flags)
      return
    }
    const data = await getPublicSystemSettings()
    systemSiteName.value = data.site_name || systemSiteName.value
    systemSiteSubtitle.value = data.site_subtitle || systemSiteSubtitle.value
    systemLogoUrl.value = data.logo_url || ''
    applyRuntimeBrandAccent(data.brand_accent)
  } catch (e: any) {
    const status = e?.response?.status
    if (status === 401 || status === 403) {
      console.warn('[AdminLayout] loadRuntimeSystemSettings failed:', status)
    }
  }
}

const jumpToNotification = (item: NoticeItem) => {
  if (!item.path) return
  router.push({ path: item.path, query: item.query || {} })
}

const onThemeChange = (value: ThemeMode) => {
  themeMode.value = value
  setThemeMode(value)
}

const ensureCurrentRouteMenuAccessible = async () => {
  if (!route.path.startsWith('/admin') && !route.path.startsWith('/practice') && !route.path.startsWith('/records')) return
  if (userStore.user?.role === 'student') return
  if (!hasPermissionPoliciesLoaded()) return
  const menuKey = pathToMenuKey(route.path)
  if (!menuKey) return
  const decision = evaluateMenuAccess(menuKey)
  if (decision.allowed) return
  const tip = '当前页面已不可访问，已为你切换到工作台'
  pushGlobalNotice({
    title: tip,
    type: 'warning',
    duration: 3000,
    detail: decision.reason || `菜单权限变化导致当前页面不可访问。菜单键：${menuKey}`,
    errorCode: 'RBAC-MENU-REDIRECT',
  })
  await router.replace(homePath.value)
}

const toggleSider = () => {
  siderCollapsed.value = !siderCollapsed.value
  if (typeof window !== 'undefined') {
    window.localStorage.setItem(SIDER_COLLAPSE_KEY, siderCollapsed.value ? '1' : '0')
  }
}

const openCommandPalette = () => {
  commandKeyword.value = ''
  commandActiveIndex.value = -1
  commandPreviewCounts.value = {}
  commandPreviewLoading.value = {}
  commandDialogVisible.value = true
  window.setTimeout(() => {
    commandInputRef.value?.focus()
  }, 0)
}

const closeCommandPalette = () => {
  commandDialogVisible.value = false
}

const navigateFromCommand = (item: CommandAction) => {
  closeCommandPalette()
  const query = item.query || {}
  router.push({ path: item.path, query })
}

const setCommandActiveIndex = (next: number) => {
  const max = flatCommandItems.value.length - 1
  if (max < 0) {
    commandActiveIndex.value = -1
    return
  }
  if (next < 0) {
    commandActiveIndex.value = max
    return
  }
  if (next > max) {
    commandActiveIndex.value = 0
    return
  }
  commandActiveIndex.value = next
}

const navigateActiveCommand = () => {
  const fallback = flatCommandItems.value[0]
  const target = flatCommandItems.value[commandActiveIndex.value] || fallback
  if (target) navigateFromCommand(target)
}

const loadPinnedMenuIds = () => {
  if (typeof window === 'undefined') return
  try {
    const raw = window.localStorage.getItem(COMMAND_PINNED_KEY)
    if (!raw) return
    const parsed = JSON.parse(raw)
    if (Array.isArray(parsed)) {
      pinnedMenuIds.value = parsed.filter((item) => typeof item === 'string')
    }
  } catch {
    pinnedMenuIds.value = []
  }
}

const savePinnedMenuIds = () => {
  if (typeof window === 'undefined') return
  window.localStorage.setItem(COMMAND_PINNED_KEY, JSON.stringify(pinnedMenuIds.value))
}

const isPinnedMenu = (item: CommandAction) => item.kind === 'menu' && pinnedMenuIds.value.includes(item.id)

const togglePinMenu = (item: CommandAction) => {
  if (item.kind !== 'menu') return
  const next = isPinnedMenu(item)
    ? pinnedMenuIds.value.filter((id) => id !== item.id)
    : [item.id, ...pinnedMenuIds.value].slice(0, 6)
  pinnedMenuIds.value = next
  savePinnedMenuIds()
}

const loadRecentMenuPaths = () => {
  if (typeof window === 'undefined') return
  try {
    const raw = window.localStorage.getItem(COMMAND_RECENT_KEY)
    if (!raw) return
    const parsed = JSON.parse(raw)
    if (Array.isArray(parsed)) {
      recentMenuPaths.value = parsed.filter((item) => typeof item === 'string')
    }
  } catch {
    recentMenuPaths.value = []
  }
}

const saveRecentMenuPaths = () => {
  if (typeof window === 'undefined') return
  window.localStorage.setItem(COMMAND_RECENT_KEY, JSON.stringify(recentMenuPaths.value))
}

const trackRecentMenuByPath = (path: string) => {
  const exists = commandItems.value.some((item) => item.path === path)
  if (!exists) return
  recentMenuPaths.value = [path, ...recentMenuPaths.value.filter((item) => item !== path)].slice(0, COMMAND_RECENT_LIMIT)
  saveRecentMenuPaths()
}

const onGlobalKeydown = (e: KeyboardEvent) => {
  const key = e.key.toLowerCase()
  const target = e.target as HTMLElement | null
  const tag = target?.tagName?.toLowerCase() || ''
  const editable = tag === 'input' || tag === 'textarea' || target?.getAttribute('contenteditable') === 'true'
  if ((e.ctrlKey || e.metaKey) && key === 'k') {
    e.preventDefault()
    if (commandDialogVisible.value) {
      commandInputRef.value?.focus()
      commandInputRef.value?.select?.()
    } else {
      openCommandPalette()
    }
    return
  }
  if ((e.ctrlKey || e.metaKey) && key === 'b' && !editable && !isMobile.value) {
    e.preventDefault()
    toggleSider()
    return
  }
  if (commandDialogVisible.value && key === 'arrowdown') {
    e.preventDefault()
    setCommandActiveIndex(commandActiveIndex.value + 1)
    return
  }
  if (commandDialogVisible.value && key === 'arrowup') {
    e.preventDefault()
    setCommandActiveIndex(commandActiveIndex.value - 1)
    return
  }
  if (commandDialogVisible.value && key === 'enter') {
    e.preventDefault()
    navigateActiveCommand()
    return
  }
  if (key === 'escape' && commandDialogVisible.value && !editable) {
    closeCommandPalette()
  }
}

const refreshCommandPreviewCounts = async () => {
  const keyword = commandKeyword.value.trim()
  if (!commandDialogVisible.value || !keyword) {
    commandPreviewCounts.value = {}
    commandPreviewLoading.value = {}
    return
  }
  const actions = searchCommandItems.value
  if (!actions.length) {
    commandPreviewCounts.value = {}
    commandPreviewLoading.value = {}
    return
  }
  const seq = ++commandPreviewSeq
  commandPreviewLoading.value = actions.reduce<Record<string, boolean>>((acc, item) => {
    acc[item.id] = true
    return acc
  }, {})
  const nextCounts: Record<string, number> = {}

  await Promise.all(
    actions.map(async (item) => {
      try {
        if (item.id === 'search:users') {
          const data = await getUsers({ page: 1, page_size: 1, keyword })
          nextCounts[item.id] = data.total || 0
          return
        }
        if (item.id === 'search:quizzes') {
          const data = await getQuizList({ page: 1, page_size: 1, keyword })
          nextCounts[item.id] = data.total || 0
          return
        }
        if (item.id === 'search:audit') {
          const data = await getAuditLogs({ page: 1, page_size: 1, keyword })
          nextCounts[item.id] = data.total || 0
          return
        }
        if (item.id === 'search:practice') {
          const data = await getAvailablePractices({ page: 1, page_size: 1, keyword })
          nextCounts[item.id] = data.total || 0
        }
      } catch {
        nextCounts[item.id] = 0
      }
    }),
  )

  if (seq !== commandPreviewSeq) return
  commandPreviewCounts.value = nextCounts
  commandPreviewLoading.value = {}
}

const triggerPreviewRefresh = createDebouncedFn(() => {
  refreshCommandPreviewCounts()
}, 240)

const updateViewport = () => {
  isMobile.value = window.innerWidth < 992
  if (!isMobile.value) drawerVisible.value = false
}

const handleMenuSelect = () => {
  if (isMobile.value) drawerVisible.value = false
}

watch(
  () => route.fullPath,
  () => {
    trackRecentMenuByPath(route.path)
    if (isMobile.value) drawerVisible.value = false
  },
)

watch(
  [() => systemSiteName.value, () => currentPageTitle.value],
  ([siteName, pageTitle]) => {
    applyPageTitle(siteName, pageTitle)
  },
  { immediate: true },
)

watch(
  [() => route.path, () => featureFlags.value],
  () => {
    ensureCurrentRouteMenuAccessible()
  },
  { deep: true },
)

watch([commandKeyword, commandDialogVisible], () => {
  triggerPreviewRefresh()
})

watch(
  () => flatCommandItems.value.length,
  (len) => {
    commandActiveIndex.value = len > 0 && commandDialogVisible.value ? 0 : -1
  },
)

watch(
  () => isImpersonating.value,
  (active) => {
    if (!active && impersonationTimer) {
      window.clearInterval(impersonationTimer)
      impersonationTimer = null
      return
    }
    if (active && !impersonationTimer) {
      nowMs.value = Date.now()
      impersonationTimer = window.setInterval(() => {
        nowMs.value = Date.now()
      }, 1000)
    }
  },
  { immediate: true },
)

onMounted(() => {
  updateViewport()
  notificationStore.load()
  loadRuntimeSystemSettings()
  if (userStore.user?.role) {
    refreshPermissionPoints()
      .then(() => ensureCurrentRouteMenuAccessible())
      .catch(() => {
        // ignore permission refresh errors, page-level actions will keep safe defaults
      })
  }
  loadPinnedMenuIds()
  loadRecentMenuPaths()
  trackRecentMenuByPath(route.path)
  unbindSiteTitleUpdate = onSiteTitleUpdate((payload) => {
    if (payload.site_name) systemSiteName.value = payload.site_name
    if (payload.site_subtitle) systemSiteSubtitle.value = payload.site_subtitle
  })
  unbindFeatureFlagsUpdate = onFeatureFlagsUpdate((flags) => {
    featureFlags.value = toFeatureFlags(flags)
    writeFeatureFlagsCache(flags)
    refreshPermissionPoints()
      .then(() => ensureCurrentRouteMenuAccessible())
      .catch(() => {
        // ignore permission refresh failure
      })
  })
  window.addEventListener('resize', updateViewport)
  window.addEventListener('keydown', onGlobalKeydown)
})

onBeforeUnmount(() => {
  if (impersonationTimer) {
    window.clearInterval(impersonationTimer)
    impersonationTimer = null
  }
  triggerPreviewRefresh.cancel()
  window.removeEventListener('resize', updateViewport)
  window.removeEventListener('keydown', onGlobalKeydown)
  unbindSiteTitleUpdate?.()
  unbindSiteTitleUpdate = null
  unbindFeatureFlagsUpdate?.()
  unbindFeatureFlagsUpdate = null
})
</script>

<template>
  <el-container class="layout-wrap">
    <div v-if="isImpersonating" class="impersonation-banner">
      <el-icon class="impersonation-banner-icon"><WarningFilled /></el-icon>
      <span class="impersonation-banner-text">
        代入中：{{ impersonationTenantName }} ｜剩余 {{ impersonationRemainText }} ｜原因：{{ impersonationReason }}
      </span>
      <el-button
        size="small"
        type="warning"
        plain
        class="impersonation-stop-btn"
        :loading="impersonationStopping"
        @click="stopImpersonationSession"
      >
        退出代入
      </el-button>
    </div>
    <template v-if="!isMobile">
      <el-aside :width="siderWidth" class="sider" :class="{ collapsed: siderCollapsed }">
        <div class="brand">
          <img v-if="systemLogoUrl" :src="systemLogoUrl" class="brand-logo" alt="logo" />
          <span v-else class="brand-dot" />
          <span class="brand-text" :title="siderCollapsed ? systemSiteName : ''">{{ systemSiteName }}</span>
          <el-button class="collapse-btn" @click="toggleSider">
            <span class="collapse-btn-text">{{ siderCollapsed ? '>>' : '<<' }}</span>
          </el-button>
        </div>
        <el-menu
          class="modern-menu"
          :default-active="activeMenu"
          :default-openeds="openedMenuKeys"
          :collapse="siderCollapsed"
          :collapse-transition="false"
          router
          @select="handleMenuSelect"
        >
          <template v-for="menu in visibleMenus" :key="menu.key">
            <el-sub-menu v-if="menu.children?.length" :index="menu.key">
              <template #title>
                <el-icon><component :is="iconMap[menu.icon]" /></el-icon>
                <span>{{ menu.label }}</span>
              </template>
              <el-menu-item
                v-for="child in menu.children"
                :key="child.key"
                :index="child.path || child.key"
                :title="child.label"
              >
                <el-icon><component :is="iconMap[child.icon]" /></el-icon>
                <span>{{ child.label }}</span>
              </el-menu-item>
            </el-sub-menu>
            <el-menu-item v-else :index="menu.path || menu.key" :title="menu.label">
              <el-icon><component :is="iconMap[menu.icon]" /></el-icon>
              <span>{{ menu.label }}</span>
            </el-menu-item>
          </template>
        </el-menu>
      </el-aside>

      <el-container>
        <el-header class="topbar">
          <div class="topbar-left">
            <div class="topbar-title">{{ displayWorkbenchTitle }}</div>
            <div class="topbar-subtitle">当前页面：{{ currentPageTitle }}</div>
          </div>
          <div class="user-area">
              <el-button class="cmd-btn" @click="openCommandPalette">
                <el-icon><Search /></el-icon>
                <span class="cmd-label">全局搜索</span>
                <span class="cmd-kbd">Ctrl+K</span>
              </el-button>
              <el-select
                v-model="themeMode"
                size="small"
                style="width: 120px"
                @change="onThemeChange"
              >
                <el-option label="跟随系统" value="system" />
                <el-option label="浅色" value="light" />
                <el-option label="深色" value="dark" />
              </el-select>
              <el-popover
                placement="bottom-end"
                :width="360"
                trigger="click"
                @show="notificationStore.markAllRead()"
              >
                <template #reference>
                  <el-badge :value="notificationStore.unread || ''" :hidden="notificationStore.unread <= 0" :max="99">
                    <el-button class="cmd-btn notice-btn">
                      <el-icon><Bell /></el-icon>
                    </el-button>
                  </el-badge>
                </template>
                <div class="notice-header">
                  <strong>通知中心</strong>
                  <div class="notice-actions">
                    <el-select v-model="notificationFilter" size="small" class="notice-filter">
                      <el-option label="全部" value="all" />
                      <el-option label="导入" value="import" />
                      <el-option label="用户" value="user" />
                      <el-option label="审计" value="audit" />
                      <el-option label="系统" value="system" />
                    </el-select>
                    <el-button text size="small" @click="notificationStore.clear()">清空</el-button>
                  </div>
                </div>
                <el-empty v-if="!filteredNotificationItems.length" class="admin-empty" description="暂无通知" />
                <div v-else class="notice-list">
                  <button
                    v-for="item in filteredNotificationItems"
                    :key="item.id"
                    type="button"
                    class="notice-item"
                    @click="jumpToNotification(item)"
                  >
                    <div class="notice-item-title">
                      {{ item.title }}
                      <el-tag size="small" effect="plain" class="notice-module-tag">{{ formatNoticeModule(item.module) }}</el-tag>
                    </div>
                    <div class="notice-item-message">{{ item.message || '-' }}</div>
                    <div class="notice-item-time">
                      {{ formatNoticeTime(item.created_at) }}
                      <span v-if="item.path" class="notice-jump-tip">点击跳转</span>
                    </div>
                  </button>
                </div>
              </el-popover>
              <el-tag size="small" effect="light" class="tenant-badge" :title="`当前租户：${currentTenantLabel}`">
                租户：{{ currentTenantLabel }}
              </el-tag>
              <span class="user-name">
                {{ userStore.user?.real_name || '管理员' }}
                <span v-if="userStore.user?.hospital_name || userStore.user?.department_name">
                  （{{ userStore.user?.hospital_name || '未分配医院' }} / {{ userStore.user?.department_name || '未分配科室' }}）
                </span>
              </span>
              <el-button link type="primary" @click="router.push('/profile')">个人中心</el-button>
              <el-button link type="primary" @click="logout">退出登录</el-button>
          </div>
        </el-header>
        <div v-if="showBreadcrumb" class="crumb-strip">
          <div class="topbar-crumb-row">
            <el-breadcrumb class="topbar-breadcrumb" :separator-icon="ArrowRight">
              <el-breadcrumb-item
                v-for="(item, idx) in condensedBreadcrumbItems"
                :key="`${item.label}-${idx}`"
                :to="item.path ? { path: item.path } : undefined"
              >
                <span
                  class="crumb-pill"
                  :class="{
                    'crumb-ellipsis': item.ellipsis,
                    'crumb-current': idx === condensedBreadcrumbItems.length - 1 && !item.ellipsis,
                  }"
                  :style="{ '--crumb-delay': `${Math.min(idx, 6) * 56}ms` }"
                >
                  {{ item.label }}
                </span>
              </el-breadcrumb-item>
            </el-breadcrumb>
          </div>
        </div>
        <el-main class="content">
          <router-view v-slot="{ Component, route: childRoute }">
            <transition name="scene-fade" mode="out-in">
              <div :key="childRoute.fullPath" class="app-scene">
                <component :is="Component" />
              </div>
            </transition>
          </router-view>
        </el-main>
      </el-container>
    </template>

    <template v-else>
      <el-container>
        <el-header class="topbar mobile-topbar">
          <div class="mobile-left">
            <el-button class="menu-btn" text @click="drawerVisible = true">
              <el-icon><Menu /></el-icon>
            </el-button>
          <img v-if="systemLogoUrl" :src="systemLogoUrl" class="mobile-logo" alt="logo" />
            <span class="mobile-title">{{ systemSiteName }}</span>
          </div>
          <div class="mobile-right">
            <el-button class="cmd-btn mobile-cmd-btn" @click="openCommandPalette">
              <el-icon><Search /></el-icon>
            </el-button>
            <el-popover placement="bottom-end" :width="320" trigger="click" @show="notificationStore.markAllRead()">
              <template #reference>
                <el-badge :value="notificationStore.unread || ''" :hidden="notificationStore.unread <= 0" :max="99">
                  <el-button class="cmd-btn mobile-cmd-btn">
                    <el-icon><Bell /></el-icon>
                  </el-button>
                </el-badge>
              </template>
              <div class="notice-header">
                <strong>通知中心</strong>
                <div class="notice-actions">
                  <el-select v-model="notificationFilter" size="small" class="notice-filter">
                    <el-option label="全部" value="all" />
                    <el-option label="导入" value="import" />
                    <el-option label="用户" value="user" />
                    <el-option label="审计" value="audit" />
                    <el-option label="系统" value="system" />
                  </el-select>
                  <el-button text size="small" @click="notificationStore.clear()">清空</el-button>
                </div>
              </div>
              <el-empty v-if="!filteredNotificationItems.length" class="admin-empty" description="暂无通知" />
              <div v-else class="notice-list">
                <button
                  v-for="item in filteredNotificationItems"
                  :key="item.id"
                  type="button"
                  class="notice-item"
                  @click="jumpToNotification(item)"
                >
                  <div class="notice-item-title">
                    {{ item.title }}
                    <el-tag size="small" effect="plain" class="notice-module-tag">{{ formatNoticeModule(item.module) }}</el-tag>
                  </div>
                  <div class="notice-item-message">{{ item.message || '-' }}</div>
                  <div class="notice-item-time">
                    {{ formatNoticeTime(item.created_at) }}
                    <span v-if="item.path" class="notice-jump-tip">点击跳转</span>
                  </div>
                </button>
              </div>
            </el-popover>
            <el-select
              v-model="themeMode"
              size="small"
              style="width: 112px"
              @change="onThemeChange"
            >
              <el-option label="系统" value="system" />
              <el-option label="浅色" value="light" />
              <el-option label="深色" value="dark" />
            </el-select>
            <el-tag size="small" effect="light" class="tenant-badge mobile-tenant-badge">
              {{ currentTenantLabel }}
            </el-tag>
            <el-button link type="primary" @click="logout">退出</el-button>
            <el-button link type="primary" @click="router.push('/profile')">我</el-button>
          </div>
        </el-header>
        <div v-if="showBreadcrumb" class="mobile-breadcrumb-wrap">
          <el-breadcrumb class="mobile-breadcrumb" :separator-icon="ArrowRight">
            <el-breadcrumb-item
              v-for="(item, idx) in mobileBreadcrumbItems"
              :key="`mobile-${item.label}-${idx}`"
              :to="item.path ? { path: item.path } : undefined"
            >
              <span
                class="crumb-pill"
                :class="{
                  'crumb-ellipsis': item.ellipsis,
                  'crumb-current': idx === mobileBreadcrumbItems.length - 1 && !item.ellipsis,
                }"
                :style="{ '--crumb-delay': `${Math.min(idx, 6) * 56}ms` }"
              >
                {{ item.label }}
              </span>
            </el-breadcrumb-item>
          </el-breadcrumb>
        </div>
        <el-main class="content mobile-content">
          <router-view v-slot="{ Component, route: childRoute }">
            <transition name="scene-fade" mode="out-in">
              <div :key="childRoute.fullPath" class="app-scene">
                <component :is="Component" />
              </div>
            </transition>
          </router-view>
        </el-main>
      </el-container>

      <el-drawer v-model="drawerVisible" direction="ltr" size="220px" :with-header="false">
        <div class="brand">
          <img v-if="systemLogoUrl" :src="systemLogoUrl" class="brand-logo" alt="logo" />
          <span v-else class="brand-dot" />
          <span class="brand-text">{{ systemSiteName }}</span>
        </div>
        <el-menu class="modern-menu" :default-active="activeMenu" :default-openeds="openedMenuKeys" router @select="handleMenuSelect">
          <template v-for="menu in visibleMenus" :key="menu.key">
            <el-sub-menu v-if="menu.children?.length" :index="menu.key">
              <template #title>
                <el-icon><component :is="iconMap[menu.icon]" /></el-icon>
                <span>{{ menu.label }}</span>
              </template>
              <el-menu-item v-for="child in menu.children" :key="child.key" :index="child.path || child.key">
                <el-icon><component :is="iconMap[child.icon]" /></el-icon>
                <span>{{ child.label }}</span>
              </el-menu-item>
            </el-sub-menu>
            <el-menu-item v-else :index="menu.path || menu.key">
              <el-icon><component :is="iconMap[menu.icon]" /></el-icon>
              <span>{{ menu.label }}</span>
            </el-menu-item>
          </template>
        </el-menu>
      </el-drawer>
    </template>

    <el-dialog
      v-model="commandDialogVisible"
      width="560px"
      top="10vh"
      class="command-dialog"
      :show-close="false"
      align-center
    >
      <template #header>
        <div class="command-title">
          <span>全局快速搜索</span>
          <span class="command-tip">输入菜单名实时筛选，回车或点击跳转</span>
        </div>
      </template>
      <el-input
        ref="commandInputRef"
        v-model="commandKeyword"
        clearable
        autofocus
        placeholder="例如：案例库、统计、用户、日志..."
      />
      <div class="command-list">
        <el-empty v-if="!flatCommandItems.length" class="admin-empty" description="没有匹配的内容或菜单" />
        <template v-else>
          <div v-for="group in groupedCommandItems" :key="group.key" class="command-group">
            <div class="command-group-title">{{ group.title }}</div>
            <button
              v-for="item in group.items"
              :key="item.id"
              type="button"
              class="command-item"
              :class="{
                'is-hit': isPreviewHit(item),
                'is-active': flatCommandItems[commandActiveIndex]?.id === item.id,
              }"
              @click="navigateFromCommand(item)"
            >
              <span class="command-item-left">
                <el-icon><component :is="item.icon" /></el-icon>
                <span>{{ item.label }}</span>
                <span class="command-item-kind">{{ item.kind === 'search' ? '内容搜索' : '菜单' }}</span>
                <span v-if="item.kind === 'search'" class="command-item-count">{{ formatPreviewCount(item) }}</span>
              </span>
              <span class="command-item-right">
                <span class="command-item-path">{{ item.path }}</span>
                <button
                  v-if="item.kind === 'menu'"
                  type="button"
                  class="pin-btn"
                  :class="{ pinned: isPinnedMenu(item) }"
                  :title="isPinnedMenu(item) ? '取消收藏' : '收藏命令'"
                  @click.stop="togglePinMenu(item)"
                >
                  {{ isPinnedMenu(item) ? '★' : '☆' }}
                </button>
              </span>
            </button>
          </div>
        </template>
      </div>
    </el-dialog>
  </el-container>
</template>

<style scoped>
.layout-wrap {
  min-height: 100vh;
  background: var(--ui-page-bg);
  color: var(--el-text-color-primary);
}

.impersonation-banner {
  position: sticky;
  top: 0;
  z-index: 2100;
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 40px;
  padding: 6px 14px;
  border-bottom: 1px solid color-mix(in srgb, var(--el-color-warning) 36%, var(--ui-border-soft) 64%);
  background: linear-gradient(
    90deg,
    color-mix(in srgb, var(--el-color-warning-light-8) 86%, transparent 14%) 0%,
    color-mix(in srgb, var(--el-color-warning-light-9) 92%, transparent 8%) 100%
  );
  color: color-mix(in srgb, var(--el-color-warning-dark-2) 72%, var(--el-text-color-primary) 28%);
  backdrop-filter: saturate(140%) blur(4px);
}

.impersonation-banner-icon {
  flex-shrink: 0;
  font-size: 16px;
}

.impersonation-banner-text {
  flex: 1;
  font-size: 12px;
  font-weight: 700;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.impersonation-stop-btn {
  flex-shrink: 0;
}

.sider {
  border-right: 1px solid var(--ui-border-soft);
  background: linear-gradient(180deg, var(--ui-surface-1) 0%, var(--ui-surface-2) 100%);
  box-shadow: inset -1px 0 0 rgb(255 255 255 / 4%);
  transition: width 280ms cubic-bezier(0.4, 0, 0.2, 1);
  overflow: hidden;
}

.brand {
  height: 56px;
  display: flex;
  align-items: center;
  justify-content: flex-start;
  gap: 8px;
  padding: 0 14px;
  font-weight: 700;
  color: var(--el-text-color-primary);
  border-bottom: 1px solid var(--ui-border-soft);
  position: relative;
  transition: padding 280ms cubic-bezier(0.4, 0, 0.2, 1);
}

.brand-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: linear-gradient(135deg, var(--el-color-primary) 0%, var(--el-color-success) 100%);
  box-shadow: var(--ui-glow-primary);
}

.brand-logo {
  width: 20px;
  height: 20px;
  border-radius: 6px;
  object-fit: cover;
  flex-shrink: 0;
}

.brand-text {
  font-size: 15px;
  letter-spacing: 0.3px;
  white-space: nowrap;
  transition:
    opacity 220ms ease,
    max-width 280ms cubic-bezier(0.4, 0, 0.2, 1);
  max-width: 220px;
  overflow: hidden;
}

.collapse-btn {
  position: absolute;
  right: 8px;
  top: 50%;
  transform: translateY(-50%);
  width: 34px;
  height: 24px;
  border-radius: 999px;
  border: 1px solid var(--ui-border-soft);
  color: var(--el-text-color-secondary);
  background: color-mix(in srgb, var(--ui-surface-1) 86%, transparent 14%);
  transition: border-color 0.2s ease, transform 0.2s ease, box-shadow 0.2s ease;
}

.collapse-btn-text {
  font-size: 12px;
  line-height: 1;
  letter-spacing: -0.5px;
  font-weight: 700;
  display: inline-block;
  transition: transform 0.2s ease;
}

.collapse-btn:hover {
  border-color: var(--ui-border-strong);
  box-shadow: var(--ui-shadow-soft);
}

.collapse-btn:hover .collapse-btn-text {
  transform: translateX(-1px);
}

.sider.collapsed .brand {
  justify-content: center;
  padding: 0 6px;
}

.sider.collapsed .brand-text {
  opacity: 0;
  max-width: 0;
}

.sider.collapsed .collapse-btn {
  right: 4px;
}

.sider.collapsed .collapse-btn:hover .collapse-btn-text {
  transform: translateX(1px);
}

:global(.sider-collapse-tooltip.el-popper) {
  background: var(--ui-surface-1) !important;
  border: 1px solid var(--ui-border-soft) !important;
  color: var(--el-text-color-primary) !important;
  font-size: 12px;
  box-shadow: var(--ui-shadow-soft) !important;
}

:global(.sider-collapse-tooltip.el-popper .el-popper__arrow::before) {
  background: var(--ui-surface-1) !important;
  border-color: var(--ui-border-soft) !important;
}

.topbar {
  min-height: 56px;
  background: color-mix(in srgb, var(--ui-surface-1) 88%, transparent 12%);
  color: var(--el-text-color-primary);
  border-bottom: 1px solid var(--ui-border-soft);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  backdrop-filter: saturate(140%) blur(6px);
}

.crumb-strip {
  padding: 8px 20px;
  border-bottom: 1px solid color-mix(in srgb, var(--ui-border-soft) 68%, transparent 32%);
  background: color-mix(in srgb, var(--ui-surface-1) 94%, transparent 6%);
}

.topbar-left {
  min-width: 180px;
  overflow: hidden;
}

.topbar-title {
  font-size: 16px;
  font-weight: 700;
  line-height: 1.2;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.topbar-subtitle {
  margin-top: 3px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.topbar-crumb-row {
  display: flex;
  align-items: center;
  min-height: 34px;
  padding: 0 10px;
  border: 1px solid var(--ui-border-soft);
  border-radius: 10px;
  background: color-mix(in srgb, var(--ui-surface-1) 92%, transparent 8%);
}

.topbar-breadcrumb {
  font-size: 12px;
  overflow-x: auto;
  white-space: nowrap;
  width: 100%;
}

.topbar-breadcrumb :deep(.el-breadcrumb__inner) {
  display: inline-flex;
  align-items: center;
  border-radius: 999px;
  transition:
    color 0.24s ease,
    background-color 0.24s ease,
    box-shadow 0.26s ease,
    transform 0.22s ease;
}

.topbar-breadcrumb :deep(.el-breadcrumb__inner.is-link) {
  color: var(--el-color-primary);
  font-weight: 600;
}

.topbar-breadcrumb :deep(.el-breadcrumb__inner.is-link:hover) {
  transform: translateY(-1px);
}

.topbar-breadcrumb :deep(.el-breadcrumb__separator),
.mobile-breadcrumb :deep(.el-breadcrumb__separator) {
  color: color-mix(in srgb, var(--el-color-primary) 52%, var(--el-text-color-secondary) 48%);
  transition: color 0.24s ease;
}

.crumb-pill {
  display: inline-flex;
  align-items: center;
  min-height: 24px;
  padding: 2px 10px;
  border-radius: 999px;
  animation: crumbSlideIn 320ms cubic-bezier(0.22, 1, 0.36, 1) both;
  animation-delay: var(--crumb-delay, 0ms);
  transition:
    color 0.24s ease,
    background-color 0.24s ease,
    box-shadow 0.26s ease,
    transform 0.22s ease;
}

.crumb-current {
  color: var(--el-color-primary);
  background: color-mix(in srgb, var(--el-color-primary-light-9) 72%, transparent 28%);
  box-shadow:
    inset 0 0 0 1px color-mix(in srgb, var(--el-color-primary) 24%, transparent 76%),
    0 6px 16px color-mix(in srgb, var(--el-color-primary) 18%, transparent 82%);
  font-weight: 700;
}

@keyframes crumbSlideIn {
  from {
    opacity: 0;
    transform: translate3d(0, 6px, 0) scale(0.98);
    filter: blur(1px);
  }
  to {
    opacity: 1;
    transform: translate3d(0, 0, 0) scale(1);
    filter: blur(0);
  }
}

.crumb-ellipsis {
  color: var(--el-text-color-secondary);
}

.user-area {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-shrink: 0;
  margin-left: 10px;
}

.tenant-badge {
  max-width: 240px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  border-color: color-mix(in srgb, var(--el-color-success) 36%, var(--ui-border-soft) 64%);
  color: color-mix(in srgb, var(--el-color-success) 76%, var(--el-text-color-primary) 24%);
  background: color-mix(in srgb, var(--el-color-success) 10%, var(--ui-surface-1) 90%);
}

.notice-btn {
  width: 34px;
  padding: 0;
}

.notice-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.notice-actions {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.notice-filter {
  width: 90px;
}

.notice-list {
  max-height: 360px;
  overflow-y: auto;
  display: grid;
  gap: 8px;
}

.notice-item {
  width: 100%;
  text-align: left;
  cursor: pointer;
  border: 1px solid var(--ui-border-soft);
  color: inherit;
  border-radius: 10px;
  background: var(--ui-surface-1);
  padding: 8px 10px;
  transition: border-color 0.2s ease, transform 0.2s ease;
  appearance: none;
  outline: none;
}

.notice-item:hover {
  border-color: var(--ui-border-strong);
  transform: translateY(-1px);
}

.notice-item-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--el-text-color-primary);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.notice-module-tag {
  flex-shrink: 0;
}

.notice-item-message {
  margin-top: 3px;
  font-size: 12px;
  color: var(--el-text-color-regular);
}

.notice-item-time {
  margin-top: 4px;
  font-size: 11px;
  color: var(--el-text-color-secondary);
  display: flex;
  justify-content: space-between;
  gap: 8px;
}

.notice-jump-tip {
  color: var(--el-color-primary);
}

.cmd-label {
  display: inline-flex;
}

@media (max-width: 1360px) {
  .user-name {
    display: none;
  }

  .cmd-kbd {
    display: none;
  }

  .tenant-badge {
    max-width: 140px;
  }
}

@media (max-width: 1200px) {
  .cmd-label {
    display: none;
  }

  .cmd-btn {
    width: 34px;
    padding: 0;
  }
}

.user-name {
  font-size: 13px;
  color: var(--el-text-color-regular);
  max-width: 520px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.content {
  padding: 16px 20px;
  background: transparent;
}

.mobile-topbar {
  padding: 0 10px;
  min-height: 56px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.mobile-breadcrumb-wrap {
  padding: 8px 10px 6px;
  border-bottom: 1px solid var(--ui-border-soft);
  background: color-mix(in srgb, var(--ui-surface-1) 90%, transparent 10%);
}

.mobile-breadcrumb {
  overflow-x: auto;
  white-space: nowrap;
  font-size: 12px;
}

.mobile-breadcrumb :deep(.el-breadcrumb__inner) {
  display: inline-flex;
  align-items: center;
  border-radius: 999px;
  transition:
    color 0.24s ease,
    background-color 0.24s ease,
    box-shadow 0.26s ease,
    transform 0.22s ease;
}

.mobile-breadcrumb :deep(.el-breadcrumb__inner.is-link) {
  color: var(--el-color-primary);
  font-weight: 600;
}

.mobile-breadcrumb :deep(.el-breadcrumb__inner.is-link:hover) {
  transform: translateY(-1px);
}

.mobile-left {
  display: flex;
  align-items: center;
  min-width: 0;
  gap: 4px;
}

.menu-btn {
  font-size: 18px;
}

.mobile-title {
  font-weight: 700;
  font-size: 14px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.mobile-logo {
  width: 20px;
  height: 20px;
  border-radius: 6px;
  object-fit: cover;
  flex-shrink: 0;
}

.mobile-right {
  display: flex;
  align-items: center;
  gap: 6px;
}

.mobile-tenant-badge {
  max-width: 90px;
}

.cmd-btn {
  height: 30px;
  border: 1px solid var(--ui-border-soft);
  background: var(--ui-surface-1);
}

.mobile-cmd-btn {
  width: 34px;
  padding: 0;
}

.cmd-kbd {
  margin-left: 6px;
  padding: 0 6px;
  border-radius: 6px;
  border: 1px solid var(--ui-border-soft);
  color: var(--el-text-color-secondary);
  font-size: 11px;
  line-height: 18px;
}

.mobile-content {
  padding: 10px;
}

:deep(.el-menu) {
  border-right: none;
  background: transparent;
}

:deep(.modern-menu) {
  padding: 10px 8px;
}

:deep(.modern-menu.el-menu--collapse) {
  padding: 10px 6px;
}

:deep(.modern-menu .el-menu-item) {
  height: 40px;
  margin: 4px 0;
  border-radius: 10px;
  color: var(--el-text-color-regular);
  font-weight: 600;
  transition: all 0.18s ease;
}

:deep(.modern-menu .el-sub-menu__title) {
  height: 40px;
  margin: 4px 0;
  border-radius: 10px;
  color: var(--el-text-color-regular);
  font-weight: 600;
  transition: all 0.18s ease;
}

:deep(.modern-menu.el-menu--collapse .el-menu-item) {
  justify-content: center;
  padding: 0 !important;
}

:deep(.modern-menu.el-menu--collapse .el-sub-menu__title) {
  justify-content: center;
  padding: 0 !important;
}

:deep(.modern-menu .el-menu-item .el-icon) {
  font-size: 15px;
}

:deep(.modern-menu .el-sub-menu__title .el-icon) {
  font-size: 15px;
}

:deep(.modern-menu .el-menu-item:hover) {
  color: var(--el-color-primary);
  background: color-mix(in srgb, var(--el-color-primary-light-9) 52%, var(--ui-surface-1) 48%);
}

:deep(.modern-menu .el-sub-menu__title:hover) {
  color: var(--el-color-primary);
  background: color-mix(in srgb, var(--el-color-primary-light-9) 52%, var(--ui-surface-1) 48%);
}

:deep(.modern-menu .el-menu-item.is-active) {
  color: var(--el-color-primary);
  background: color-mix(in srgb, var(--el-color-primary-light-8) 66%, var(--ui-surface-1) 34%);
  box-shadow: var(--ui-glow-primary);
}

:deep(.modern-menu .el-sub-menu.is-active > .el-sub-menu__title) {
  color: var(--el-color-primary);
  background: color-mix(in srgb, var(--el-color-primary-light-8) 66%, var(--ui-surface-1) 34%);
}

.command-title {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.command-tip {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.command-list {
  margin-top: 10px;
  max-height: 360px;
  overflow: auto;
  display: grid;
  gap: 8px;
}

.command-group {
  display: grid;
  gap: 6px;
}

.command-group-title {
  font-size: 11px;
  line-height: 16px;
  color: var(--el-text-color-secondary);
  font-weight: 700;
  letter-spacing: 0.3px;
  padding: 4px 2px 0;
}

.command-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  border: 1px solid var(--ui-border-soft);
  border-radius: 10px;
  background: var(--ui-surface-1);
  color: inherit;
  width: 100%;
  text-align: left;
  padding: 8px 10px;
  cursor: pointer;
  transition: border-color 0.2s ease, transform 0.2s ease, box-shadow 0.2s ease;
}

.command-item:hover {
  border-color: var(--ui-border-strong);
  transform: translateY(-1px);
  box-shadow: var(--ui-shadow-soft);
}

.command-item.is-active {
  border-color: var(--ui-border-strong);
  transform: translateY(-1px);
  box-shadow: var(--ui-shadow-soft);
}

.command-item.is-hit {
  border-color: color-mix(in srgb, var(--el-color-primary) 28%, var(--ui-border-soft) 72%);
  box-shadow:
    inset 0 0 0 1px color-mix(in srgb, var(--el-color-primary) 12%, transparent 88%),
    0 8px 18px rgb(24 125 255 / 10%);
}

.command-item-left {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
}

.command-item-kind {
  border: 1px solid var(--ui-border-soft);
  border-radius: 999px;
  padding: 0 8px;
  font-size: 11px;
  line-height: 18px;
  color: var(--el-text-color-secondary);
  font-weight: 500;
}

.command-item-count {
  border: 1px solid var(--ui-border-soft);
  border-radius: 999px;
  padding: 0 8px;
  font-size: 11px;
  line-height: 18px;
  color: var(--el-color-primary);
  background: color-mix(in srgb, var(--el-color-primary-light-9) 72%, transparent 28%);
  font-weight: 600;
}

.command-item-path {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.command-item-right {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.pin-btn {
  border: 1px solid var(--ui-border-soft);
  border-radius: 8px;
  background: transparent;
  color: var(--el-text-color-secondary);
  width: 22px;
  height: 22px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  padding: 0;
  font-size: 13px;
  line-height: 1;
}

.pin-btn:hover {
  border-color: var(--el-color-primary-light-5);
  color: var(--el-color-primary);
}

.pin-btn.pinned {
  border-color: var(--el-color-warning-light-5);
  color: #d68a00;
  background: color-mix(in srgb, var(--el-color-warning-light-9) 72%, transparent 28%);
}
</style>
