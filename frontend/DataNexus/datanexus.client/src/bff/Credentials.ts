import { service } from '../common/APIService.js'

// 凭据「基础列表」——走 BFF 直连 DB 读 nexus.app_credential 的非敏感元数据。
export interface CredentialListItem {
  credential_name: string
  credential_type: string
  description: string | null
  is_active: boolean
  creation_time: string | null
  update_time: string | null
}

export function listCredentials(): Promise<CredentialListItem[]> {
  return service.get('credentials')
}
