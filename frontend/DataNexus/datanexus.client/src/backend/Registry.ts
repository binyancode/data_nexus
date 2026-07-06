import { service } from '../common/APIService.js'
import { backendUrl } from '../bff/Config.js'

// 触发 Python 端注册表热重载：源/凭据/LLM 保存后调用，使内存实例即时生效（免重启）。
export async function reloadRegistry(): Promise<{ resolvers: number; llms: number }> {
  const url = await backendUrl('resolvers/reload')
  return service.post(url, {}, true, false)
}
