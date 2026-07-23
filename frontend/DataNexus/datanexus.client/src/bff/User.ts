import { service } from '../common/APIService.js'

// BFF 直连 DB 读当前登录用户（nexus.app_user）。调用会带 Bearer → 测 access token 到 BFF 的认证。
export interface MeInfo {
  user_name: string
  display_name: string | null
  is_admin: boolean
}

export interface AppUser {
  id: number
  user_name: string
  display_name: string | null
  is_admin: boolean
  created_at: string | null
}

export interface AppUserPayload {
  user_name: string
  display_name: string | null
  is_admin: boolean
}

export function getMe(): Promise<MeInfo> {
  return service.get('user/me')
}

export function getUsers(): Promise<AppUser[]> {
  return service.get('user')
}

export function createUser(payload: AppUserPayload): Promise<{ id: number; user_name: string }> {
  return service.post('user', payload)
}

export function updateUser(id: number, payload: AppUserPayload): Promise<{ id: number; user_name: string }> {
  return service.put('user/' + id, payload)
}

export function deleteUser(id: number): Promise<{ id: number; user_name: string }> {
  return service.del('user/' + id)
}
