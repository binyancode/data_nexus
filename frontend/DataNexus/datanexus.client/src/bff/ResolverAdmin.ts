import { service } from '../common/APIService.js'

// 源（Resolver）管理——走 BFF 直连 nexus.resolvers（无密文）。保存后需 reload 注册表生效。
export interface ResolverAdminItem {
  resolver_name: string
  resolver_type: string
  config: string | null
  credential_name: string | null
  is_active: boolean
  update_time: string | null
}

export interface ResolverAdminPayload {
  resolver_name: string
  resolver_type: string
  config?: string | null
  credential_name?: string | null
  is_active?: boolean
}

export function listResolverAdmin(): Promise<ResolverAdminItem[]> {
  return service.get('resolver-admin')
}

export function createResolverAdmin(payload: ResolverAdminPayload): Promise<any> {
  return service.post('resolver-admin', payload)
}

export function updateResolverAdmin(name: string, payload: ResolverAdminPayload): Promise<any> {
  return service.put('resolver-admin/' + encodeURIComponent(name), payload)
}

export function deleteResolverAdmin(name: string): Promise<any> {
  return service.del('resolver-admin/' + encodeURIComponent(name))
}

// resolver 类型 → 兼容的 credential 类型（action 无需凭据）
// resolver 类型 → 兼容的 credential 类型（可多个；action 无需凭据）
export const RESOLVER_CRED_TYPE: Record<string, string[]> = {
  sql: ['sql'],
  csv: ['local_file'],
  agent: ['azure_openai'],
  action: [],
}
