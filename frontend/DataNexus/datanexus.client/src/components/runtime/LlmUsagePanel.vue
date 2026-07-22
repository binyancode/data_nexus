<template>
  <div v-if="showEmpty || calls.length" class="llm-usage">
    <div class="lu-head">
      <b>LLM Token</b>
      <span v-if="calls.length">{{ calls.length }} 次调用</span>
      <span v-else>本阶段无 LLM 调用</span>
    </div>
    <div class="lu-metrics">
      <span>输入 <b>{{ formatTokens(summary.inputTokens) }}</b></span>
      <span>输出 <b>{{ formatTokens(summary.outputTokens) }}</b></span>
      <span v-if="summary.cachedAvailable">Cached <b>{{ formatTokens(summary.cachedInputTokens) }}</b></span>
      <span v-if="summary.uncachedAvailable">未缓存输入 <b>{{ formatTokens(summary.uncachedInputTokens) }}</b></span>
      <span v-if="summary.reasoningAvailable">推理 <b>{{ formatTokens(summary.reasoningTokens) }}</b></span>
      <span>总计 <b>{{ formatTokens(summary.totalTokens) }}</b></span>
      <span v-if="calls.length && !summary.callsWithUsage" class="lu-unavailable">Provider 未返回 usage</span>
    </div>

    <details v-for="(call, index) in calls" :key="call.request_id || call.response_id || index" class="lu-call">
      <summary>
        <b>{{ llmPurposeLabel(call.purpose) }}</b>
        <span>{{ call.model || call.deployment || call.llm_name || call.provider || '—' }}</span>
        <span v-if="call.metadata?.attempt">第 {{ call.metadata.attempt }} 次</span>
        <span v-if="call.duration_ms != null">{{ call.duration_ms }} ms</span>
      </summary>
      <div class="lu-grid">
        <span>输入 token</span><b>{{ token(call.usage?.input_tokens) }}</b>
        <span>Cached token</span><b>{{ token(call.usage?.cached_input_tokens) }}</b>
        <span>未缓存输入</span><b>{{ token(call.usage?.uncached_input_tokens) }}</b>
        <span>输出 token</span><b>{{ token(call.usage?.output_tokens) }}</b>
        <span>推理 token</span><b>{{ token(call.usage?.reasoning_tokens) }}</b>
        <span>总 token</span><b>{{ token(call.usage?.total_tokens) }}</b>
        <span>结束原因</span><b>{{ call.finish_reason || '—' }}</b>
        <span>Request ID</span><b class="lu-id">{{ call.request_id || call.response_id || '—' }}</b>
      </div>
      <div class="lu-io"><b>输入</b><pre>{{ pretty(call.input) }}</pre></div>
      <div class="lu-io"><b>输出</b><pre>{{ pretty(call.output) }}</pre></div>
      <div v-if="call.usage" class="lu-io"><b>Usage 原始明细</b><pre>{{ pretty(call.usage) }}</pre></div>
      <div v-if="call.error" class="lu-error">{{ call.error }}</div>
    </details>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import {
  formatTokens,
  llmCallsFromLogs,
  llmPurposeLabel,
  summarizeLlmCalls,
} from './llmUsage'

const props = withDefaults(defineProps<{ logs?: string | null; showEmpty?: boolean }>(), {
  logs: null,
  showEmpty: true,
})
const calls = computed(() => llmCallsFromLogs(props.logs))
const summary = computed(() => summarizeLlmCalls(calls.value))
function token(value?: number | null): string { return value == null ? '—' : formatTokens(value) }
function pretty(value: unknown): string {
  if (value == null) return '—'
  return typeof value === 'string' ? value : JSON.stringify(value, null, 2)
}
</script>

<style scoped>
.llm-usage { margin: 0 0 10px; padding: 9px 10px; border: 1px solid #d8e4f0; border-radius: 8px; background: #f7faff; color: #35516c; }
.lu-head { display: flex; align-items: center; gap: 8px; font-size: 11px; color: #6c8298; }
.lu-head b { color: #27465f; font-size: 12px; }
.lu-metrics { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 7px; }
.lu-metrics span { padding: 2px 7px; border: 1px solid #d6e2ee; border-radius: 10px; background: #fff; font-size: 10.5px; color: #667e94; }
.lu-metrics b { color: #183b57; font-variant-numeric: tabular-nums; }
.lu-metrics .lu-unavailable { color: #a06c24; border-color: #ead4aa; background: #fffaf1; }
.lu-call { margin-top: 8px; border-top: 1px solid #dce6f0; padding-top: 7px; }
.lu-call summary { cursor: pointer; display: flex; flex-wrap: wrap; gap: 8px; font-size: 11px; color: #6a8095; }
.lu-call summary b { color: #24516f; }
.lu-grid { display: grid; grid-template-columns: 105px minmax(0, 1fr); gap: 4px 8px; margin: 8px 0; font-size: 10.5px; }
.lu-grid span { color: #74899d; }
.lu-grid b { color: #314d66; font-weight: 600; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
.lu-id { font-family: 'Cascadia Code', Consolas, monospace; }
.lu-io { margin-top: 7px; font-size: 10.5px; color: #6a8095; }
.lu-io pre { margin: 4px 0 0; max-height: 220px; overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere; border: 1px solid #dbe5ef; border-radius: 6px; padding: 7px 8px; background: #fff; color: #304b63; font: 10px/1.45 'Cascadia Code', Consolas, monospace; }
.lu-error { margin-top: 7px; color: #a33a3a; white-space: pre-wrap; }
</style>
