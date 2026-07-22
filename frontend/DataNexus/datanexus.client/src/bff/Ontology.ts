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
  constraints?: {
    nullable?: boolean | null
    unique?: boolean
    primary_key?: boolean
    source?: string
  }
}

export interface EntityNodeData {
  id: string
  name: string
  semantics?: string | null
  synonyms?: string[]
  resolver?: string
  table?: string | null
  key?: string | string[] | null
  attributes: AttributeNode[]
  layout?: { x: number; y: number }
}

export interface RelationEdge {
  id: string
  name: string
  semantics?: string | null
  synonyms?: string[]
  from: { entity: string; attribute: string | string[] }
  to: { entity: string; attribute: string | string[] }
  multiplicity: {
    from_to: { min: 0 | 1 | 'unknown'; max: 1 | 'many' | 'unknown' }
    to_from: { min: 0 | 1 | 'unknown'; max: 1 | 'many' | 'unknown' }
  }
  integrity: {
    mode: 'ENFORCED' | 'DECLARED' | 'INFERRED' | 'UNKNOWN'
    source?: string | null
    constraint_name?: string | null
    confidence: number
  }
  temporal?: { fact_time: string; valid_from: string; valid_to: string } | null
  confirmation?: { required: boolean; confirmed: boolean }
}

export interface MetricItem {
  id: string
  name: string
  semantics?: string | null
  synonyms?: string[]
  expression: Record<string, any>
  result_type?: string
  unit?: string
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
  version: 3
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
  return { version: 3, entities: [], relations: [], metrics: [], derivations: [], actions: [], resolvers: [] }
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
