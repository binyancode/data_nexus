import type { RunNode, RunStage } from '../../bff/Runs'

export interface LlmTokenUsage {
  input_tokens?: number | null
  cached_input_tokens?: number | null
  uncached_input_tokens?: number | null
  cache_write_input_tokens?: number | null
  output_tokens?: number | null
  reasoning_tokens?: number | null
  total_tokens?: number | null
  input_token_details?: Record<string, unknown> | null
  output_token_details?: Record<string, unknown> | null
}

export interface LlmCallLog {
  purpose?: string | null
  metadata?: Record<string, unknown> | null
  provider?: string | null
  llm_name?: string | null
  model?: string | null
  deployment?: string | null
  request_id?: string | null
  response_id?: string | null
  finish_reason?: string | null
  started_at?: string | null
  duration_ms?: number | null
  input?: unknown
  output?: unknown
  usage?: LlmTokenUsage | null
  error?: string | null
}

export interface LlmUsageSummary {
  calls: number
  callsWithUsage: number
  inputTokens: number
  outputTokens: number
  totalTokens: number
  cachedInputTokens: number
  cachedAvailable: boolean
  uncachedInputTokens: number
  uncachedAvailable: boolean
  reasoningTokens: number
  reasoningAvailable: boolean
}

function parseJson(value?: string | null): any {
  if (!value) return null
  try { return JSON.parse(value) } catch { return null }
}

export function llmCallsFromLogs(logs?: string | null): LlmCallLog[] {
  const parsed = parseJson(logs)
  return Array.isArray(parsed?.llm_calls) ? parsed.llm_calls : []
}

function callKey(call: LlmCallLog): string {
  return call.request_id || call.response_id || JSON.stringify([
    call.provider, call.llm_name, call.purpose, call.started_at, call.duration_ms,
    call.usage?.input_tokens, call.usage?.output_tokens,
  ])
}

export function collectRunLlmCalls(stages: RunStage[], nodes: RunNode[]): LlmCallLog[] {
  const all = [
    ...stages.flatMap((stage) => llmCallsFromLogs(stage.logs)),
    ...nodes.flatMap((node) => llmCallsFromLogs(node.logs)),
  ]
  const seen = new Set<string>()
  return all.filter((call) => {
    const key = callKey(call)
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
}

function number(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0
}

export function summarizeLlmCalls(calls: LlmCallLog[]): LlmUsageSummary {
  const usages = calls.map((call) => call.usage).filter((usage): usage is LlmTokenUsage => !!usage)
  return {
    calls: calls.length,
    callsWithUsage: usages.length,
    inputTokens: usages.reduce((sum, usage) => sum + number(usage.input_tokens), 0),
    outputTokens: usages.reduce((sum, usage) => sum + number(usage.output_tokens), 0),
    totalTokens: usages.reduce((sum, usage) => sum + number(usage.total_tokens), 0),
    cachedInputTokens: usages.reduce((sum, usage) => sum + number(usage.cached_input_tokens), 0),
    cachedAvailable: usages.some((usage) => usage.cached_input_tokens != null),
    uncachedInputTokens: usages.reduce((sum, usage) => sum + number(usage.uncached_input_tokens), 0),
    uncachedAvailable: usages.some((usage) => usage.uncached_input_tokens != null),
    reasoningTokens: usages.reduce((sum, usage) => sum + number(usage.reasoning_tokens), 0),
    reasoningAvailable: usages.some((usage) => usage.reasoning_tokens != null),
  }
}

export function formatTokens(value: number): string {
  return new Intl.NumberFormat('zh-CN').format(value)
}

export function llmPurposeLabel(value?: string | null): string {
  return ({
    ontology_routing: '本体路由',
    sqg_compilation: 'SQG 编译',
    ask_generation: 'ASK 生成',
  } as Record<string, string>)[value || ''] || value || 'LLM 调用'
}
