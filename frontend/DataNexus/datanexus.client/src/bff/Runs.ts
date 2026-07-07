import { service } from '../common/APIService.js'

// 运行记录（BFF 直连 DB 读 nexus.run / run_stage / run_node）。
export interface RunListItem {
  run_id: string
  question: string | null
  as_user: string | null
  state: string | null
  cost_ms: number
  created_at: string | null
}

export interface RunStage {
  stage: string
  seq: number
  state: string | null
  input: string | null   // JSON 字符串
  output: string | null  // JSON 字符串（optimizer 行 = plan JSON，画执行图用）
  error: string | null
  cost_ms: number | null
  started_at: string | null
  ended_at: string | null
}

export interface RunNode {
  node_id: string
  state: string | null
  resolver: string | null
  call: string | null
  output: string | null
  value: string | null
  source: string | null
  trust: number | null
  error: string | null
  cost_ms: number | null
  started_at: string | null
  ended_at: string | null
}

export interface RunInfo {
  run_id: string
  question: string | null
  as_user: string | null
  state: string | null
  answer: string | null
  cost_ms: number
  created_at: string | null
  updated_at: string | null
  ontology_id: string | null
}

export interface RunDetail {
  run: RunInfo
  stages: RunStage[]
  nodes: RunNode[]
}

export function getRuns(take = 50): Promise<RunListItem[]> {
  return service.get('runs?take=' + take)
}

export function getRun(runId: string): Promise<RunDetail> {
  return service.get('runs/' + encodeURIComponent(runId))
}
