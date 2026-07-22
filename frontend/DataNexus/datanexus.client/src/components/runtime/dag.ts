// DAG 布局与状态色（SqgDag / CoordinatorDag 共用）。
import { MarkerType, type Edge, type Node } from '@vue-flow/core'
import type { LlmUsageSummary } from './llmUsage'

// 运行完成时 NexusRuntime 向外抛出的最终答案
export interface RuntimeAnswer {
  text: string
  lineage: { label: string; value: unknown; source: string; detail?: string }[]
  usage?: LlmUsageSummary
}

export interface DagNodeIn {
  id: string
  depends_on?: string[]
  wave?: number
}

// 拓扑分波：优先用 node.wave，否则按 depends_on 计算
export function computeWaves<T extends DagNodeIn>(nodes: T[]): T[][] {
  const ids = new Set(nodes.map((n) => n.id))
  if (nodes.length && nodes.every((n) => (n.wave ?? 0) >= 1)) {
    const buckets = new Map<number, T[]>()
    for (const n of nodes) {
      const w = n.wave as number
      if (!buckets.has(w)) buckets.set(w, [])
      buckets.get(w)!.push(n)
    }
    return [...buckets.keys()].sort((a, b) => a - b).map((w) => buckets.get(w)!)
  }
  const done = new Set<string>()
  let rem = [...nodes]
  const waves: T[][] = []
  let guard = 0
  while (rem.length && guard++ < 50) {
    const ready = rem.filter((n) => (n.depends_on ?? []).every((d) => done.has(d) || !ids.has(d)))
    const wave = ready.length ? ready : rem
    waves.push(wave)
    wave.forEach((n) => done.add(n.id))
    rem = rem.filter((n) => !done.has(n.id))
  }
  return waves
}

export function positionMap<T extends DagNodeIn>(
  waves: T[][],
  xGap = 250,
  yGap = 84,
  x0 = 24,
  y0 = 24,
): Map<string, { x: number; y: number }> {
  const pos = new Map<string, { x: number; y: number }>()
  const maxRows = Math.max(1, ...waves.map((w) => w.length))
  waves.forEach((wave, wi) => {
    // 每一波竖直居中
    const offset = ((maxRows - wave.length) * yGap) / 2
    wave.forEach((n, ni) => pos.set(n.id, { x: x0 + wi * xGap, y: y0 + offset + ni * yGap }))
  })
  return pos
}

export function buildEdges<T extends DagNodeIn>(
  nodes: T[],
  edgeState?: (targetId: string) => string | undefined,
): Edge[] {
  const ids = new Set(nodes.map((n) => n.id))
  const edges: Edge[] = []
  for (const n of nodes) {
    for (const dep of n.depends_on ?? []) {
      if (!ids.has(dep)) continue
      const st = edgeState?.(n.id)
      const col = edgeColor(st)
      edges.push({
        id: `${dep}->${n.id}`,
        source: dep,
        target: n.id,
        type: 'smoothstep',
        animated: st === 'running',
        style: { stroke: col, strokeWidth: 1.6 },
        markerEnd: { type: MarkerType.ArrowClosed, color: col, width: 14, height: 14 },
      })
    }
  }
  return edges
}

// 执行状态色
export function stateColor(state?: string | null): string {
  switch (state) {
    case 'running':
      return '#2f7cb4'
    case 'done':
      return '#2e9b5b'
    case 'failed':
      return '#d52b1e'
    case 'skipped':
      return '#97a3ae'
    case 'pending':
    default:
      return '#c4cbd1'
  }
}

function edgeColor(state?: string | null): string {
  if (!state) return '#c4cbd1'
  return stateColor(state)
}

// 算子色（SQG 逻辑图按算子上色）
export function operatorColor(op?: string | null): string {
  switch (op) {
    case 'AGGREGATE':
      return '#0a6b83'
    case 'SELECT':
      return '#2f7cb4'
    case 'CALCULATE':
      return '#7456c8'
    case 'SEARCH':
      return '#168aad'
    case 'BROWSE':
      return '#277da1'
    case 'ASK':
      return '#e97600'
    case 'ACT':
      return '#d52b1e'
    default:
      return '#28334a'
  }
}

// 组一个自定义 VueFlow 节点（配合 DagNode.vue）
export function dagNode(
  id: string,
  pos: { x: number; y: number },
  data: { name: string; badge?: string; value?: string; color: string; selected?: boolean; fuseTag?: string; cost?: string },
  extraClass = '',
): Node {
  return {
    id,
    type: 'dagNode',
    position: pos,
    data,
    class: extraClass,
  }
}

export function safeParse<T = any>(s?: string | null): T | null {
  if (!s) return null
  try {
    return JSON.parse(s) as T
  } catch {
    return null
  }
}
