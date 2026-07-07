<template>
  <StageShell :seq="4" title="协调器" subtitle="分波并行执行 · 回填 · 逐节点取数" :state="stage?.state" :cost="stage?.cost_ms ?? null">
    <div class="prog">
      <div class="prog-bar"><div class="prog-fill" :style="{ width: pct + '%' }"></div></div>
      <span class="prog-txt">{{ doneCount }} / {{ nodes.length }} 完成</span>
    </div>
    <div v-if="nodes.length" class="rows">
      <div v-for="n in nodes" :key="n.node_id" class="row" :class="{ live: n.state === 'running' }">
        <span class="dot" :style="{ background: stateColor(n.state) }"></span>
        <span class="nm">{{ n.node_id }}</span>
        <span class="st">{{ label(n.state) }}</span>
        <span class="val" v-if="n.value != null">= {{ n.value }}</span>
        <span class="src" v-if="n.source">⛁ {{ n.source }}</span>
        <span class="cost" v-if="n.cost_ms != null">{{ n.cost_ms }} ms</span>
      </div>
    </div>
    <div v-else class="muted">尚未执行</div>
  </StageShell>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import StageShell from './StageShell.vue'
import { stateColor } from './dag'
import type { RunStage, RunNode } from '../../bff/Runs'

const props = defineProps<{ stage: RunStage | null; nodes: RunNode[] }>()

const nodes = computed(() => props.nodes ?? [])
const doneCount = computed(() => nodes.value.filter((n) => n.state === 'done').length)
const pct = computed(() => (nodes.value.length ? Math.round((doneCount.value / nodes.value.length) * 100) : 0))
function label(s?: string | null) {
  return { pending: '待执行', running: '执行中', done: '完成', failed: '失败', skipped: '跳过' }[s ?? 'pending'] ?? s ?? ''
}
</script>

<style scoped>
.prog { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
.prog-bar { flex: 1; height: 7px; border-radius: 4px; background: rgba(255, 255, 255, 0.08); overflow: hidden; }
.prog-fill { height: 100%; background: linear-gradient(90deg, var(--tech-cyan), var(--tech-green)); box-shadow: 0 0 10px var(--tech-glow); transition: width 0.4s ease; }
.prog-txt { font-size: 11px; color: var(--tech-dim); white-space: nowrap; font-variant-numeric: tabular-nums; }
.rows { display: flex; flex-direction: column; gap: 6px; }
.row { display: flex; align-items: center; gap: 10px; padding: 8px 11px; border: 1px solid var(--tech-border); border-radius: 8px; background: var(--tech-panel-2); }
.row.live { border-color: var(--tech-cyan); background: rgba(59, 214, 236, 0.1); box-shadow: 0 0 14px var(--tech-glow); }
.dot { width: 9px; height: 9px; border-radius: 50%; flex: 0 0 auto; box-shadow: 0 0 6px currentColor; }
.nm { font-size: 13px; font-weight: 600; color: var(--tech-text); min-width: 40px; }
.st { font-size: 11px; color: var(--tech-dim); }
.val { font-size: 13px; font-weight: 700; color: var(--tech-text); }
.src { font-size: 11px; color: var(--tech-cyan); }
.cost { margin-left: auto; font-size: 11px; color: var(--tech-dim); font-variant-numeric: tabular-nums; }
.muted { color: var(--tech-dim); }
</style>
