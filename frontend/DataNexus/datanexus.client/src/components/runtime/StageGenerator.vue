<template>
  <StageShell :seq="5" title="生成器" subtitle="合并结果 → 自然语言答案 + 血缘" :state="stage?.state" :cost="stage?.cost_ms ?? null">
    <div v-if="answerText" class="answer">
      <el-icon class="a-icon"><Opportunity /></el-icon>
      <span>{{ answerText }}</span>
    </div>
    <div v-else class="muted">尚未生成</div>

    <div v-if="lineage.length" class="lin-h">血缘 · 每个数字的来源</div>
    <div v-if="lineage.length" class="lineage">
      <div v-for="(li, i) in lineage" :key="i" class="li">
        <div class="li-top">
          <span class="li-name">{{ li.label }}</span>
          <span class="li-val">{{ li.value }}</span>
        </div>
        <div class="li-src">⛁ {{ li.source }}</div>
        <pre v-if="li.detail" class="li-sql">{{ li.detail }}</pre>
      </div>
    </div>
    <div v-if="stage?.error" class="err">{{ stage.error }}</div>
  </StageShell>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import StageShell from './StageShell.vue'
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
</script>

<style scoped>
.answer { display: flex; align-items: center; gap: 8px; font-size: 15px; color: var(--tech-text); font-weight: 700; margin-bottom: 12px; }
.a-icon { color: var(--tech-amber); font-size: 18px; }
.lin-h { font-size: 11px; color: var(--tech-dim); font-weight: 600; margin-bottom: 8px; }
.lineage { display: flex; flex-direction: column; gap: 8px; }
.li { border: 1px solid var(--tech-border); border-radius: 8px; padding: 9px 11px; background: var(--tech-panel-2); }
.li-top { display: flex; align-items: baseline; gap: 10px; }
.li-name { font-size: 12px; color: var(--tech-dim); }
.li-val { font-size: 15px; font-weight: 700; color: var(--tech-text); }
.li-src { font-size: 11px; color: var(--tech-cyan); margin-top: 2px; }
.li-sql {
  margin: 8px 0 0; padding: 8px 10px; border-radius: 6px;
  background: #eef3fb; border: 1px solid #d6e3f1; color: #2f4a62; font-size: 11px;
  font-family: 'Cascadia Code', Consolas, monospace; overflow-x: auto; white-space: pre-wrap; line-height: 1.5;
}
.muted { color: var(--tech-dim); }
.err { margin-top: 8px; color: #ffd5d0; white-space: pre-wrap; font-size: 12px; }
</style>
