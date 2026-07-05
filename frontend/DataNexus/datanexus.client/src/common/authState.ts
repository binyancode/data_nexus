import { reactive } from 'vue'
import { getMe } from '../bff/User.js'

// 登录用户状态（displayName 来自 BFF → nexus.app_user）。
export const authState = reactive({
  loaded: false,
  isAdmin: false,
  userName: '',
  displayName: '',
})

export async function loadAuthState() {
  try {
    const me = await getMe()
    authState.userName = me.user_name ?? ''
    authState.displayName = me.display_name ?? ''
    authState.isAdmin = !!me.is_admin
  } catch {
    authState.isAdmin = false
  } finally {
    authState.loaded = true
  }
}
