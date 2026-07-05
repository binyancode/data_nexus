import { service } from '../common/APIService.js'
import { backendUrl } from '../bff/Config.js'

// 直连 Python 后端提问（异步）：立即返回 run_id，后台执行；前端据 run_id 轮询运行记录。
export interface AskStarted {
  run_id: string
}

export async function ask(q: string, ontologyId?: string | null): Promise<AskStarted> {
  const url = await backendUrl('ask')
  // unwrap=false：后端返回 { run_id }
  return service.post(url, { q, ontology_id: ontologyId || null }, true, false)
}
