import { service } from '../common/APIService.js'

// 本体：整块 graph JSON（BFF 直连 nexus.ontology）。

// kind 编辑器（EditorMetric/Derivation/Action）用的轻量概念形状（由 graph 摊平而来）。
export interface Concept {
  id: string
  kind: string
  name: string
  attrs?: string | null      // JSON 对象字符串
  synonyms?: string | null
  semantics?: string | null
}

export interface AttributeNode {
  id: string
  name: string
  column?: string | null
  role?: 'dimension' | 'measure' | null
  dtype?: 'number' | 'text' | 'date' | 'bool' | 'unknown' | null
  additivity?: 'additive' | 'semi_additive' | 'non_additive' | null
  enabled?: boolean          // 是否启用（停用则不进编译器/查询；默认启用）
  synonyms?: string[]
  semantics?: string | null
}

export interface EntityNodeData {
  id: string
  name: string
  semantics?: string | null
  synonyms?: string[]
  resolver?: string
  table?: string | null
  key?: string | null
  attributes: AttributeNode[]
  layout?: { x: number; y: number }
}

export interface RelationEdge {
  id: string
  name: string
  semantics?: string | null
  synonyms?: string[]
  from_entity: string
  from_key: string
  to_entity: string
  to_key: string
}

export interface MetricItem {
  id: string
  name: string
  semantics?: string | null
  synonyms?: string[]
  expr: string
}

export interface DerivationItem {
  id: string
  name: string
  semantics?: string | null
  synonyms?: string[]
  prompt?: string
  inputs?: string[]
  resolver?: string
}

export interface ActionItem {
  id: string
  name: string
  semantics?: string | null
  synonyms?: string[]
  action?: string
  desc?: string
  resolver?: string
  endpoint?: string
}

export interface AttachedResolver {
  name: string
  type: string
}

export interface OntologyGraph {
  entities: EntityNodeData[]
  relations: RelationEdge[]
  metrics: MetricItem[]
  derivations: DerivationItem[]
  actions: ActionItem[]
  resolvers?: AttachedResolver[]   // 本体挂载的 resolver（SQL 随实体自动、agent/action 手动）
}

export interface OntologyMeta {
  ontologyId: string
  name: string
  description?: string | null
  owner: string
  visibility: 'private' | 'shared' | 'public'
  state: string
  updatedAt?: string | null
  canEdit: boolean
}

export interface OntologyFull extends OntologyMeta {
  grants: string[]
  graph: OntologyGraph
}

export function emptyGraph(): OntologyGraph {
  return { entities: [], relations: [], metrics: [], derivations: [], actions: [], resolvers: [] }
}

export function listOntologies(): Promise<OntologyMeta[]> {
  return service.get('ontologies')
}
export function getOntology(id: string): Promise<OntologyFull> {
  return service.get('ontologies/' + encodeURIComponent(id))
}
export function createOntology(name: string, description?: string): Promise<{ ontologyId: string }> {
  return service.post('ontologies', { name, description })
}
export function saveOntology(id: string, name: string, description: string | null, graph: OntologyGraph): Promise<any> {
  return service.put('ontologies/' + encodeURIComponent(id), { name, description, graph })
}
export function publishOntology(id: string, visibility: string, grants: string[]): Promise<any> {
  return service.post('ontologies/' + encodeURIComponent(id) + '/publish', { visibility, grants })
}
export function deleteOntology(id: string): Promise<any> {
  return service.del('ontologies/' + encodeURIComponent(id))
}
