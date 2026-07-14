<template>
  <StageShell :seq="5" title="生成器" subtitle="合并结果 → 自然语言答案 + 血缘" :state="stage?.state" :cost="stage?.cost_ms ?? null">
    <div v-if="answerText" class="answer">
      <el-icon class="a-icon"><Opportunity /></el-icon>
      <MarkdownContent class="answer-md" :content="answerText" compact />
    </div>
    <div v-else class="muted">尚未生成</div>

    <div v-if="lineage.length" class="lin-h">血缘 · 每个数字的来源</div>
    <div v-if="lineage.length" class="lineage">
      <div v-for="(li, i) in lineage" :key="i" class="li">
        <div class="li-top">
          <span class="li-name">{{ li.label }}</span>
          <span v-if="!sameLineageUrl(li)" class="li-val">{{ li.value }}</span>
        </div>
        <div class="li-src">
          <span>⛁</span>
          <a v-if="isUrl(li.source)" :href="li.source" target="_blank" rel="noopener noreferrer">{{ li.source }}</a>
          <span v-else>{{ li.source }}</span>
        </div>
        <pre v-if="li.detail" class="li-sql">{{ li.detail }}</pre>
      </div>
    </div>
    <div v-if="stage?.error" class="err">{{ stage.error }}</div>
  </StageShell>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import StageShell from './StageShell.vue'
import MarkdownContent from '../common/MarkdownContent.vue'
import { safeParse } from './dag'
import type { RunStage } from '../../bff/Runs'

interface Answer {
  text?: string
  lineage?: { label: string; value: unknown; source: string; detail?: string }[]
}
const props = defineProps<{ stage: RunStage | null }>()

const answer = computed(() => safeParse<Answer>(props.stage?.output))
const answerText = computed(() => answer.value?.text ?? '')
const lineage = computed(() => answer.value?.lineage ?? [])
function isUrl(value: unknown): boolean { return /^https?:\/\//i.test(String(value ?? '')) }
function sameLineageUrl(li: { value: unknown; source: string }): boolean {
  return isUrl(li.value) && String(li.value) === li.source
}
</script>

<style scoped>
.answer { display: flex; align-items: flex-start; gap: 8px; color: var(--tech-text); margin-bottom: 12px; }
.a-icon { color: var(--tech-amber); font-size: 18px; }
.answer-md { flex: 1; min-width: 0; }
.lin-h { font-size: 11px; color: var(--tech-dim); font-weight: 600; margin-bottom: 8px; }
.lineage { display: flex; flex-direction: column; gap: 8px; }
.li { min-width: 0; overflow: hidden; border: 1px solid var(--tech-border); border-radius: 8px; padding: 9px 11px; background: var(--tech-panel-2); }
.li-top { display: flex; align-items: baseline; gap: 10px; min-width: 0; }
.li-name { font-size: 12px; color: var(--tech-dim); overflow-wrap: anywhere; }
.li-val { min-width: 0; font-size: 15px; font-weight: 700; color: var(--tech-text); overflow-wrap: anywhere; word-break: break-word; }
.li-src { display: flex; align-items: flex-start; gap: 4px; min-width: 0; font-size: 11px; color: var(--tech-cyan); margin-top: 2px; }
.li-src a, .li-src span:last-child { min-width: 0; overflow-wrap: anywhere; word-break: break-word; }
.li-src a { color: inherit; text-decoration: none; }
.li-src a:hover { text-decoration: underline; }
.li-sql {
  margin: 8px 0 0; padding: 8px 10px; border-radius: 6px;
  background: #eef3fb; border: 1px solid #d6e3f1; color: #2f4a62; font-size: 11px;
  font-family: 'Cascadia Code', Consolas, monospace; overflow-x: auto; white-space: pre-wrap; line-height: 1.5;
}
.muted { color: var(--tech-dim); }
.err { margin-top: 8px; color: #ffd5d0; white-space: pre-wrap; font-size: 12px; }
</style>
