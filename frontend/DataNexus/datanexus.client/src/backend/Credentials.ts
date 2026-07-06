import { service } from '../common/APIService.js'
import { backendUrl } from '../bff/Config.js'

// 凭据「密文相关」操作——走 Python 后端（持有 Key Vault 访问）：类型 schema / 详情回填 / 增删改。
// 详情只回非敏感字段值；敏感字段前端置空并要求重新输入。

export interface CredentialField {
  name: string
  type: string          // string | number | password
  required: boolean
  sensitive: boolean
  description?: string
}
export interface CredentialTypeMeta {
  display_name: string
  description: string
  schema: CredentialField[]
}
export interface CredentialDetail {
  credential_name: string
  credential_type: string
  data: Record<string, any>   // 仅非敏感字段
}

export async function getCredentialTypes(): Promise<Record<string, CredentialTypeMeta>> {
  const url = await backendUrl('credentials/types')
  const res = await service.get(url, true, false)
  return res.types
}

export async function getCredentialDetail(name: string): Promise<CredentialDetail> {
  const url = await backendUrl('credentials/' + encodeURIComponent(name))
  return service.get(url, true, false)
}

export async function createCredential(payload: {
  credential_name: string; credential_type: string; data: Record<string, any>; description?: string
}): Promise<any> {
  const url = await backendUrl('credentials')
  return service.post(url, payload, true, false)
}

export async function updateCredential(name: string, payload: {
  credential_type: string; data: Record<string, any>; description?: string
}): Promise<any> {
  const url = await backendUrl('credentials/' + encodeURIComponent(name))
  return service.put(url, payload, true, false)
}

export async function deleteCredential(name: string): Promise<any> {
  const url = await backendUrl('credentials/' + encodeURIComponent(name))
  return service.del(url, true, false)
}
