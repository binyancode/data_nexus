import { service } from '../common/APIService.js'

export interface ApiLogListItem {
  id: number
  function_name: string | null
  method: string | null
  path: string | null
  user_name: string | null
  state: string | null
  cost_ms: number | null
  request_time: string | null
  response_time: string | null
  source: string | null
  has_message: boolean
}

export interface ApiLogDetail extends ApiLogListItem {
  payload: string | null
  response: string | null
  message: string | null
}

export interface ApiLogQuery {
  page: number
  pageSize: number
  state?: string
  source?: string
  user?: string
  function?: string
  keyword?: string
  from?: string
  to?: string
}

export interface ApiLogPage {
  items: ApiLogListItem[]
  total: number
  page: number
  page_size: number
}

export function getApiLogs(query: ApiLogQuery): Promise<ApiLogPage> {
  const params = new URLSearchParams({
    page: String(query.page),
    pageSize: String(query.pageSize),
  })
  for (const key of ['state', 'source', 'user', 'function', 'keyword', 'from', 'to'] as const) {
    const value = query[key]
    if (value) params.set(key, value)
  }
  return service.get('api-logs?' + params.toString())
}

export function getApiLog(id: number): Promise<ApiLogDetail> {
  return service.get('api-logs/' + id)
}
