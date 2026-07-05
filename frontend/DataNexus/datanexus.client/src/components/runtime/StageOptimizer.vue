<template>
  <StageShell :seq="2" title="优化器" subtitle="语义图 → 物理执行计划（选源 · 生成调用 · 分波）" :state="stage?.state" :cost="stage?.cost_ms ?? null">
    <div class="sum">
      <span class="pill">{{ planNodes.length }} 节点</span>
      <span class="pill">{{ maxWave }} 波并行</span>
      <span class="pill src" v-for="r in resolvers" :key="r">⛁ {{ r }}</span>
    </div>
    <div v-if="planNodes.length" class="nodes">
      <div v-for="n in planNodes" :key="n.id" class="node">
        <div class="node-top">
          <span class="w">波 {{ n.wave ?? '?' }}</span>
          <span class="nm">{{ n.name || n.id }}</span>
          <span class="op">{{ n.operator }}</span>
          <span class="rs">⛁ {{ n.resolver || '—' }}</span>
        </div>
        <pre v-if="callText(n)" class="call">{{ callText(n) }}</pre>
      </div>
    </div>
    <div v-else class="muted">尚未生成</div>
    <div v-if="stage?.error" class="err">{{ stage.error }}</div>
  </StageShell>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import StageShell from './StageShell.vue'
import { safeParse } from './dag'
import type { RunStage } from '../../bff/Runs'

interface PlanNode { id: string; operator: string; name?: string; resolver?: string; wave?: number; call?: { sql?: string; params?: unknown[] } | unknown }
const props = defineProps<{ stage: RunStage | null }>()

const plan = computed(() => safeParse<{ nodes?: PlanNode[]; context?: { max_wave?: number } }>(props.stage?.output))
const planNodes = computed(() => plan.value?.nodes ?? [])
const maxWave = computed(() => plan.value?.context?.max_wave ?? Math.max(1, ...planNodes.value.map((n) => n.wave ?? 1)))
const resolvers = computed(() => [...new Set(planNodes.value.map((n) => n.resolver).filter(Boolean))] as string[])

function callText(n: PlanNode): string {
  const c: any = n.call
  if (!c) return ''
  if (typeof c === 'object' && c.sql) {
    let s = c.sql as string
    if (Array.isArray(c.params) && c.params.length) s += '   -- 参数: ' + c.params.join(', ')
    return s
  }
  return typeof c === 'string' ? c : JSON.stringify(c)
}
</script>

<style scoped>
.sum { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 10px; }
.pill { font-size: 11px; padding: 3px 9px; border-radius: 10px; background: var(--tech-panel-2); border: 1px solid var(--tech-border); color: var(--tech-dim); }
.pill.src { background: rgba(59, 214, 236, 0.12); border-color: rgba(59, 214, 236, 0.3); color: var(--tech-cyan); }
.nodes { display: flex; flex-direction: column; gap: 8px; }
.node { border: 1px solid var(--tech-border); border-radius: 8px; padding: 9px 11px; background: var(--tech-panel-2); }
.node-top { display: flex; align-items: center; gap: 8px; }
.w { font-size: 10px; color: #05121f; font-weight: 700; background: var(--tech-cyan); border-radius: 4px; padding: 2px 6px; box-shadow: 0 0 8px var(--tech-glow); }
.nm { font-size: 13px; font-weight: 600; color: var(--tech-text); }
.op { font-size: 10px; color: var(--tech-dim); border: 1px solid var(--tech-border); border-radius: 4px; padding: 1px 6px; }
.rs { margin-left: auto; font-size: 11px; color: var(--tech-cyan); }
.call {
  margin: 9px 0 0; padding: 9px 11px; border-radius: 6px;
  background: #eef3fb; border: 1px solid #d6e3f1; color: #2f4a62; font-size: 11px;
  font-family: 'Cascadia Code', Consolas, monospace; overflow-x: auto; white-space: pre-wrap; line-height: 1.5;
}
.muted { color: var(--tech-dim); }
.err { margin-top: 8px; color: #ffd5d0; white-space: pre-wrap; font-size: 12px; }
</style>
