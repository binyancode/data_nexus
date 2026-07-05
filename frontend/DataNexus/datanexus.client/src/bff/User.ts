import { service } from '../common/APIService.js'

// BFF 直连 DB 读当前登录用户（nexus.app_user）。调用会带 Bearer → 测 access token 到 BFF 的认证。
export interface MeInfo {
  user_name: string
  display_name: string | null
  is_admin: boolean
}

export function getMe(): Promise<MeInfo> {
  return service.get('user/me')
}
