import { service } from '../common/APIService.js'
import { backendUrl } from '../bff/Config.js'
import type { EntityNodeData, RelationEdge } from '../bff/Ontology.js'

// 直连 Python 后端：列 resolver、探测 schema、导入预览（产出可并入画板的 graph 片段）。

export interface ResolverInfo {
  name: string
  type: string
  provides_concepts?: boolean
  operators?: string[]
  relational?: Record<string, unknown>
}

export interface ColumnInfo {
  column: string
  type: string
  dtype?: string
  nullable?: boolean | null
  unique?: boolean
}

export interface SchemaInfo {
  tables: Record<string, ColumnInfo[]>
}

export interface ImportFragment {
  version: 3
  entities: EntityNodeData[]
  relations: RelationEdge[]
}

export interface ResolverSample {
  resolver: string
  target: string
  columns: string[]
  rows: Array<Record<string, unknown>>
}

export async function listResolvers(): Promise<ResolverInfo[]> {
  const url = await backendUrl('resolvers')
  return service.get(url, true, false)
}

export async function resolverSchema(name: string): Promise<SchemaInfo> {
  const url = await backendUrl('resolvers/' + encodeURIComponent(name) + '/schema')
  return service.get(url, true, false)
}

export async function importPreview(name: string, tables: string[]): Promise<ImportFragment> {
  const url = await backendUrl('resolvers/' + encodeURIComponent(name) + '/import-preview')
  return service.post(url, { tables }, true, false)
}

export async function resolverSample(name: string, target: string, limit = 20): Promise<ResolverSample> {
  const url = await backendUrl('resolvers/' + encodeURIComponent(name) + '/sample')
  return service.post(url, { target, limit }, true, false)
}
