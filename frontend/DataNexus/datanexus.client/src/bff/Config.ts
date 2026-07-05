import { service } from '../common/APIService.js'

interface BackendAPIConfig {
  baseUrl: string
  version: string
  endpoints?: Record<string, { path: string; method: string }>
}

let _cached: BackendAPIConfig | null = null

// 从 BFF 取后端地址（config/BackendAPI，匿名）。BFF 用 System.Text.Json → camelCase 字段。
async function BackendAPI(): Promise<BackendAPIConfig> {
  if (!_cached) {
    _cached = await service.get('config/BackendAPI', false)
  }
  return _cached!
}

// 拼后端 API 完整 URL，如 http://localhost:8000/api/v1/ask
async function backendUrl(path: string): Promise<string> {
  const c = await BackendAPI()
  return `${c.baseUrl}/${c.version}/${path.replace(/^\//, '')}`
}

export { BackendAPI, backendUrl, type BackendAPIConfig }
