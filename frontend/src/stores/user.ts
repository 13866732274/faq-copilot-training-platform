import { defineStore } from 'pinia'
import { clearAuth, clearLastRoute, getCurrentUser, getToken, setAuth, type LoginUser } from '../utils/auth'
import { loginApi, meApi } from '../api/auth'
import { clearFeatureFlagsCache } from '../utils/systemFeatures'
import { clearPermissionPointsCache, refreshPermissionPoints } from '../utils/permissionPoints'

interface LoginForm {
  username: string
  password: string
  tenant_code?: string
}

export const useUserStore = defineStore('user', {
  state: () => ({
    token: getToken(),
    user: getCurrentUser() as LoginUser | null,
  }),
  getters: {
    isLogin: (state) => Boolean(state.token),
  },
  actions: {
    async login(form: LoginForm) {
      const data = await loginApi(form)
      setAuth(data.access_token, data.user)
      this.token = data.access_token
      this.user = data.user
      try {
        await refreshPermissionPoints()
      } catch {
        // ignore permission preload failure
      }
    },
    async fetchMe() {
      if (!this.token) return null
      const me = await meApi()
      this.user = {
        id: me.id,
        username: me.username,
        real_name: me.real_name,
        role: me.role,
        avatar: me.avatar,
        hospital_id: me.hospital_id,
        hospital_name: me.hospital_name,
        hospital_ids: me.hospital_ids || [],
        department_id: me.department_id,
        department_name: me.department_name,
        department_ids: me.department_ids || [],
        menu_permissions: me.menu_permissions ?? null,
        is_all_hospitals: me.is_all_hospitals,
        tenant_id: me.tenant_id,
        tenant_name: me.tenant_name,
        is_platform_super_admin: me.is_platform_super_admin,
        is_impersonating: me.is_impersonating,
        impersonation_tenant_id: me.impersonation_tenant_id,
        impersonation_tenant_name: me.impersonation_tenant_name,
        impersonation_expires_at: me.impersonation_expires_at,
        impersonation_reason: me.impersonation_reason,
        enabled_modules: me.enabled_modules || [],
      } as LoginUser
      try {
        await refreshPermissionPoints()
      } catch {
        // ignore permission preload failure
      }
      return this.user
    },
    logout() {
      clearAuth()
      clearLastRoute()
      clearFeatureFlagsCache()
      clearPermissionPointsCache()
      this.token = ''
      this.user = null
    },
  },
})
