<template>
  <StageShell :seq="2" title="编译器" subtitle="自然语言 → 语义查询图 (SQG)" :state="stage?.state" :cost="stage?.cost_ms ?? null">
    <div class="flow">
      <div class="col in-col">
        <div class="col-h">输入 · 问题</div>
        <div class="q-box">{{ question || '—' }}</div>
        <div class="hint" v-if="intent">意图：{{ intent }}</div>
      </div>
      <div class="col-arrow">➜</div>
      <div class="col grow">
        <div class="col-h">输出 · SQG（{{ sqgNodes.length }} 节点）</div>
        <div v-if="sqgNodes.length" class="nodes">
          <div v-for="n in sqgNodes" :key="n.id" class="node">
            <span class="op" :style="{ background: operatorColor(n.operator) }">{{ n.operator }}</span>
            <span class="nm">{{ n.name || n.id }}</span>
            <span class="cc" v-if="n.concept">{{ n.concept }}</span>
          </div>
        </div>
        <div v-else class="muted">尚未生成</div>
      </div>
    </div>
    <div v-if="stage?.error" class="err">{{ stage.error }}</div>
  </StageShell>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import StageShell from './StageShell.vue'
import { safeParse, operatorColor } from './dag'
import type { RunStage } from '../../bff/Runs'

interface SqgNode { id: string; operator: string; name?: string; concept?: string }
const props = defineProps<{ stage: RunStage | null }>()

const question = computed(() => safeParse<{ question?: string }>(props.stage?.input)?.question)
const sqg = computed(() => safeParse<{ nodes?: SqgNode[]; context?: { intent?: string } }>(props.stage?.output))
const sqgNodes = computed(() => sqg.value?.nodes ?? [])
const intent = computed(() => sqg.value?.context?.intent)
</script>

<style scoped>
.flow { display: flex; align-items: stretch; gap: 10px; }
.col { display: flex; flex-direction: column; gap: 6px; }
.col.grow { flex: 1; min-width: 0; }
.in-col { min-width: 120px; max-width: 200px; }
.col-h { font-size: 11px; color: var(--tech-dim); font-weight: 600; letter-spacing: 0.03em; }
.col-arrow { align-self: center; color: var(--tech-cyan-dim); font-size: 18px; }
.q-box { background: var(--tech-panel-2); border: 1px solid var(--tech-border); border-radius: 8px; padding: 8px 10px; font-size: 13px; color: var(--tech-text); }
.hint { font-size: 11px; color: var(--tech-dim); }
.nodes { display: flex; flex-direction: column; gap: 6px; }
.node { display: flex; align-items: center; gap: 8px; padding: 8px 10px; background: var(--tech-panel-2); border: 1px solid var(--tech-border); border-radius: 8px; }
.op { color: #fff; font-size: 10px; padding: 2px 7px; border-radius: 4px; font-weight: 600; letter-spacing: 0.02em; box-shadow: 0 0 10px rgba(0, 0, 0, 0.25); }
.nm { font-size: 13px; font-weight: 600; color: var(--tech-text); }
.cc { margin-left: auto; font-size: 11px; color: var(--tech-cyan-dim); font-family: 'Cascadia Code', Consolas, monospace; }
.muted { color: var(--tech-dim); }
.err { margin-top: 8px; color: #ffd5d0; white-space: pre-wrap; font-size: 12px; }
</style>
