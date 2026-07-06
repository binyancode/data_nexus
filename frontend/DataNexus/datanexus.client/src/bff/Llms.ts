import { service } from '../common/APIService.js'

// LLM（规划大脑）管理——走 BFF 直连 nexus.llms（无密文）。保存后需 reload 注册表生效。
export interface LlmItem {
  llm_name: string
  provider: string
  config: string | null
  credential_name: string | null
  is_default: boolean
  is_active: boolean
  update_time: string | null
}

export interface LlmPayload {
  llm_name: string
  provider: string
  config?: string | null
  credential_name?: string | null
  is_default?: boolean
}

export function listLlms(): Promise<LlmItem[]> {
  return service.get('llms')
}

export function createLlm(payload: LlmPayload): Promise<any> {
  return service.post('llms', payload)
}

export function updateLlm(name: string, payload: LlmPayload): Promise<any> {
  return service.put('llms/' + encodeURIComponent(name), payload)
}

export function deleteLlm(name: string): Promise<any> {
  return service.del('llms/' + encodeURIComponent(name))
}

export function setDefaultLlm(name: string): Promise<any> {
  return service.put('llms/' + encodeURIComponent(name) + '/default', {})
}
