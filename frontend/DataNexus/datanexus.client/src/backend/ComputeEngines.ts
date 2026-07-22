import { service } from '../common/APIService.js'
import { backendUrl } from '../bff/Config.js'

export type ComputeEngineType = 'duckdb' | 'sql_server'

export interface ComputeCapabilities {
  joins?: string[]
  aggregates?: string[]
  time_grains?: string[]
  conditional_aggregate?: boolean
  top_n?: boolean
  spill?: boolean
}

export interface ComputeEngineItem {
  engine_name: string
  engine_type: ComputeEngineType
  config: Record<string, any>
  credential_name: string | null
  runtime_user: string | null
  is_default: boolean
  is_active: boolean
  provision_state: string
  provision_error?: string | null
  creation_time: string | null
  update_time: string | null
  capabilities: ComputeCapabilities
}

export interface ComputeEnginePayload {
  engine_name: string
  engine_type: ComputeEngineType
  config: Record<string, any>
  credential_name?: string | null
  runtime_user?: string | null
  is_default: boolean
}

async function endpoint(path = ''): Promise<string> {
  return backendUrl(`compute-engines${path}`)
}

export async function listComputeEngines(): Promise<ComputeEngineItem[]> {
  const response = await service.get(await endpoint(), true, false)
  return response.items || []
}

export async function createComputeEngine(payload: ComputeEnginePayload): Promise<ComputeEngineItem> {
  return service.post(await endpoint(), payload, true, false)
}

export async function updateComputeEngine(
  name: string,
  payload: Pick<ComputeEnginePayload, 'config' | 'is_default'>,
): Promise<ComputeEngineItem> {
  return service.put(await endpoint('/' + encodeURIComponent(name)), payload, true, false)
}

export async function setDefaultComputeEngine(name: string): Promise<ComputeEngineItem> {
  return service.post(await endpoint('/' + encodeURIComponent(name) + '/default'), {}, true, false)
}

export async function testComputeEngine(name: string): Promise<{ engine_name: string; tested: boolean }> {
  return service.post(await endpoint('/' + encodeURIComponent(name) + '/test'), {}, true, false)
}

export async function deleteComputeEngine(name: string): Promise<{ engine_name: string; deleted: boolean }> {
  return service.del(await endpoint('/' + encodeURIComponent(name)), true, false)
}
