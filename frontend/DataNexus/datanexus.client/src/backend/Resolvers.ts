import { service } from '../common/APIService.js'
import { backendUrl } from '../bff/Config.js'
import type { EntityNodeData, RelationEdge } from '../bff/Ontology.js'

// 直连 Python 后端：列 resolver、探测 schema、导入预览（产出可并入画板的 graph 片段）。

export interface ResolverInfo {
  name: string
  type: string
  provides_concepts?: boolean
  operators?: string[]
}

export interface ColumnInfo {
  column: string
  type: string
  dtype?: string
}

export interface SchemaInfo {
  tables: Record<string, ColumnInfo[]>
}

export interface ImportFragment {
  entities: EntityNodeData[]
  relations: RelationEdge[]
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
