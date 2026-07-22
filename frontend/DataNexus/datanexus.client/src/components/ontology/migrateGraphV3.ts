import type { EntityNodeData, OntologyGraph, RelationEdge } from '../../bff/Ontology'

export interface MigrationIssue {
  kind: 'relation' | 'metric'
  id: string
  message: string
}

export interface MigrationResult {
  graph: OntologyGraph
  issues: MigrationIssue[]
}

function deepCopy<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T
}

function attributeId(entities: EntityNodeData[], entityId: string, key: string): string | null {
  const entity = entities.find((item) => item.id === entityId)
  return entity?.attributes.find((attribute) => (attribute.column || attribute.name) === key)?.id || null
}

function parseMetricExpression(text: string): Record<string, any> | null {
  const source = (text || '').trim()
  const aggregate = source.match(/^\s*(SUM|AVG|COUNT|MIN|MAX)\s*\((.*)\)\s*$/i)
  if (!aggregate) return null
  const functionName = aggregate[1]!.toUpperCase()
  const inner = aggregate[2]!.trim()
  if (functionName === 'COUNT' && inner === '*') {
    return { kind: 'aggregate', function: 'COUNT', value: null, nulls: 'IGNORE' }
  }
  const tokens = inner.split(/\s+([+\-*/])\s+/).filter(Boolean)
  if (!tokens.length || tokens.length % 2 === 0) return null
  const attributePattern = /^(?:[A-Za-z0-9_]+::)?attribute(?:\.[A-Za-z0-9_]+)+$/
  if (!attributePattern.test(tokens[0]!)) return null
  let value: Record<string, any> = { kind: 'attribute', concept: tokens[0] }
  for (let index = 1; index < tokens.length; index += 2) {
    const op = tokens[index]!, right = tokens[index + 1]!
    if (!attributePattern.test(right)) return null
    value = {
      kind: 'binary',
      operator: ({ '+': 'ADD', '-': 'SUBTRACT', '*': 'MULTIPLY', '/': 'SAFE_DIVIDE' } as Record<string, string>)[op],
      left: value,
      right: { kind: 'attribute', concept: right },
      zero_division: 'NULL',
    }
  }
  return { kind: 'aggregate', function: functionName, value, nulls: 'IGNORE' }
}

function migrateRelation(raw: any, entities: EntityNodeData[], issues: MigrationIssue[]): RelationEdge | null {
  if (raw?.from && raw?.to && raw?.multiplicity && raw?.integrity) {
    const relation = deepCopy(raw) as RelationEdge
    relation.confirmation = { required: true, confirmed: false }
    return relation
  }
  const fromAttribute = attributeId(entities, raw?.from_entity, raw?.from_key)
  const toAttribute = attributeId(entities, raw?.to_entity, raw?.to_key)
  if (!fromAttribute || !toAttribute) {
    issues.push({ kind: 'relation', id: raw?.id || 'unknown', message: '无法把旧关联键映射到属性 id，已跳过此关系。' })
    return null
  }
  const oldCardinality = String(raw?.cardinality || '').toLowerCase()
  const maxima = oldCardinality === 'n:1' ? ['many', 1]
    : oldCardinality === '1:n' ? [1, 'many']
      : oldCardinality === '1:1' ? [1, 1]
        : ['unknown', 'unknown']
  issues.push({ kind: 'relation', id: raw.id, message: '已转换端点；基数、两个方向可选性和完整性需要人工确认。' })
  return {
    id: raw.id,
    name: raw.name || raw.id,
    semantics: raw.semantics ?? null,
    synonyms: raw.synonyms || [],
    from: { entity: raw.from_entity, attribute: fromAttribute },
    to: { entity: raw.to_entity, attribute: toAttribute },
    multiplicity: {
      from_to: { min: 'unknown', max: maxima[1] as any },
      to_from: { min: 'unknown', max: maxima[0] as any },
    },
    integrity: { mode: 'UNKNOWN', source: 'legacy_conversion', confidence: 0 },
    temporal: null,
    confirmation: { required: true, confirmed: false },
  }
}

export function migrateGraphToV3(source: any): MigrationResult {
  const entities = deepCopy(source?.entities || []) as EntityNodeData[]
  for (const entity of entities) {
    entity.key = Array.isArray(entity.key) ? entity.key : entity.key ? [entity.key] : []
    for (const attribute of entity.attributes || []) {
      const keys = entity.key as string[]
      attribute.constraints = attribute.constraints || {
        nullable: null,
        unique: keys.includes(attribute.column || attribute.name),
        primary_key: keys.includes(attribute.column || attribute.name),
        source: 'legacy_conversion',
      }
    }
  }

  const issues: MigrationIssue[] = []
  const relations = (source?.relations || [])
    .map((relation: any) => migrateRelation(relation, entities, issues))
    .filter(Boolean) as RelationEdge[]
  const metrics = (source?.metrics || []).map((metric: any) => {
    if (metric.expression) return deepCopy(metric)
    const expression = parseMetricExpression(metric.expr || '')
    if (!expression) {
      issues.push({ kind: 'metric', id: metric.id, message: '旧指标表达式无法安全解析；已创建空 SUM，请在保存前重新配置。' })
    }
    return {
      id: metric.id, name: metric.name, semantics: metric.semantics ?? null,
      synonyms: metric.synonyms || [],
      expression: expression || { kind: 'aggregate', function: 'SUM', value: null, nulls: 'IGNORE' },
      result_type: metric.type || 'decimal', unit: metric.unit || null,
    }
  })
  const resolvers = source?.resolvers?.length
    ? deepCopy(source.resolvers)
    : [...new Set(entities.map((entity) => entity.resolver).filter(Boolean))]
      .map((name) => ({ name: name!, type: 'sql' }))

  return {
    graph: {
      version: 3, entities, relations, metrics,
      derivations: deepCopy(source?.derivations || []),
      actions: deepCopy(source?.actions || []), resolvers,
    },
    issues,
  }
}
