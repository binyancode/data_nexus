import { service } from '../common/APIService.js'
import { backendUrl } from '../bff/Config.js'

// 直连 Python 后端提问。service 会带 Bearer → 测 access token 到后端的认证。
export interface LineageItem {
  node_id: string
  label: string
  value: string | number | null
  resolver: string
  source: string
  detail: string
}

export interface AskResult {
  answer: string
  lineage: LineageItem[]
}

export async function ask(q: string): Promise<AskResult> {
  const url = await backendUrl('ask')
  // unwrap=false：后端成功时直接返回 { answer, lineage }（非 {state,data} 信封）
  return service.post(url, { q }, true, false)
}
