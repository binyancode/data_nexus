<template>
  <div class="dag-wrap">
    <div v-if="!planNodes.length" class="dag-empty">暂无执行图</div>
    <VueFlow
      v-else
      :nodes="nodes"
      :edges="edges"
      :node-types="nodeTypes"
      :fit-view-on-init="true"
      :nodes-draggable="false"
      :nodes-connectable="false"
      :zoom-on-scroll="false"
      :prevent-scrolling="false"
      class="dag-canvas"
      @node-click="onNodeClick"
    >
      <Background pattern-color="#d9e2ee" :gap="24" :size="1.3" />
      <Controls :show-interactive="false" />
    </VueFlow>

    <transition name="fade">
      <div v-if="selected" class="node-detail">
        <div class="nd-head">
          <span class="nd-dot" :style="{ background: stateColor(state?.state) }"></span>
          <span class="nd-name">{{ selected.name || selected.id }}</span>
          <span class="nd-badge">{{ stateLabel(state?.state) }}</span>
          <span class="nd-close" @click="selectedId = null">✕</span>
        </div>
        <div class="nd-row"><b>算子</b><span>{{ selected.operator }}</span></div>
        <div class="nd-row"><b>源</b><span>{{ state?.resolver || selected.resolver || '—' }}</span></div>
        <div class="nd-row" v-if="selected.depends_on?.length"><b>依赖</b><span>{{ selected.depends_on.join(', ') }}</span></div>
        <div class="nd-row" v-if="state?.value != null"><b>值</b><span class="nd-val">{{ state.value }}</span></div>
        <div class="nd-row" v-if="state?.source"><b>来源</b><span>{{ state.source }}</span></div>
        <div class="nd-row" v-if="state?.cost_ms != null"><b>耗时</b><span>{{ state.cost_ms }} ms</span></div>
        <div class="nd-block" v-if="callText"><b>调用</b><pre>{{ callText }}</pre></div>
        <div class="nd-block err" v-if="state?.error"><b>错误</b><pre>{{ state.error }}</pre></div>
      </div>
    </transition>
  </div>
</template>

<script setup lang="ts">
import { computed, markRaw, ref } from 'vue'
import { VueFlow } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import '@vue-flow/core/dist/style.css'
import '@vue-flow/core/dist/theme-default.css'
import '@vue-flow/controls/dist/style.css'
import { computeWaves, positionMap, buildEdges, stateColor, safeParse, dagNode } from './dag'
import DagNode from './DagNode.vue'
import type { RunNode } from '../../bff/Runs'

const nodeTypes: any = { dagNode: markRaw(DagNode) }

interface PlanNode {
  id: string
  operator: string
  name?: string
  resolver?: string
  depends_on?: string[]
  wave?: number
  call?: unknown
}
const props = defineProps<{
  plan: { nodes?: PlanNode[] } | null
  nodeStates: Record<string, RunNode>
}>()

const planNodes = computed<PlanNode[]>(() => props.plan?.nodes ?? [])
const selectedId = ref<string | null>(null)

function st(id: string): string {
  return props.nodeStates?.[id]?.state ?? 'pending'
}
function stateLabel(s?: string | null): string {
  return { pending: '待执行', running: '执行中', done: '完成', failed: '失败', skipped: '跳过' }[s ?? 'pending'] ?? s ?? ''
}

const nodes = computed(() => {
  const ns = planNodes.value
  const pos = positionMap(computeWaves(ns))
  return ns.map((n) => {
    const s = st(n.id)
    const rn = props.nodeStates?.[n.id]
    const raw = rn?.value != null && rn.value !== '' ? String(rn.value) : stateLabel(s)
    const tail = raw.length > 26 ? raw.slice(0, 26) + '…' : raw
    return dagNode(
      n.id,
      pos.get(n.id) ?? { x: 0, y: 0 },
      {
        name: n.name || n.id,
        badge: n.operator,
        value: tail,
        color: stateColor(s),
        selected: n.id === selectedId.value,
      },
      s === 'running' ? 'rn-pulse' : '',
    )
  })
})
const edges = computed(() => buildEdges(planNodes.value, (id) => st(id)))

const selected = computed(() => planNodes.value.find((n) => n.id === selectedId.value) || null)
const state = computed<RunNode | undefined>(() =>
  selectedId.value ? props.nodeStates?.[selectedId.value] : undefined,
)
const callText = computed(() => {
  const c = state.value?.call
  if (!c) return ''
  const parsed = safeParse(c)
  return parsed ? JSON.stringify(parsed, null, 2) : String(c)
})

function onNodeClick(e: { node: { id: string } }) {
  selectedId.value = e.node.id
}
</script>

<style scoped>
.dag-wrap {
  position: relative;
  width: 100%;
  height: 340px;
  border: 1px solid #dbe5f2;
  border-radius: 12px;
  overflow: hidden;
  background: #f4f8fd;
}
.dag-canvas { width: 100%; height: 100%; }
.dag-empty {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--tech-dim);
  font-size: 13px;
}
:deep(.vue-flow__node) { white-space: pre-line; text-align: center; line-height: 1.35; }
:deep(.vue-flow__node-dagNode) { background: none; border: none; padding: 0; box-shadow: none; width: auto; border-radius: 0; }
:deep(.vue-flow__controls) {
  box-shadow: 0 8px 20px rgba(20, 40, 70, 0.16);
  border: 1px solid #dbe5f2;
  border-radius: 10px;
  overflow: hidden;
}
:deep(.vue-flow__controls-button) { background: #fff; color: #3f566f; }
:deep(.vue-flow__controls-button:hover) { background: #f1f6fb; }
:deep(.vue-flow__node.rn-pulse) { animation: rnpulse 1.1s ease-in-out infinite; }
@keyframes rnpulse {
  0%, 100% { filter: drop-shadow(0 0 2px rgba(47, 124, 180, 0.26)); }
  50% { filter: drop-shadow(0 0 10px rgba(47, 124, 180, 0.68)); }
}
.node-detail {
  position: absolute;
  top: 10px;
  right: 10px;
  width: 258px;
  background: #ffffff;
  border: 1px solid #dbe5f2;
  border-radius: 10px;
  box-shadow: 0 12px 30px rgba(16, 24, 40, 0.14);
  padding: 10px 12px;
  font-size: 12px;
  max-height: 92%;
  overflow: auto;
}
.nd-head { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.nd-dot { width: 10px; height: 10px; border-radius: 50%; flex: 0 0 auto; box-shadow: 0 0 0 2px rgba(157, 170, 186, 0.2); }
.nd-name { font-weight: 700; flex: 1; color: #1f2f43; }
.nd-badge { font-size: 10px; color: #6f859c; }
.nd-close { cursor: pointer; color: #7a8da3; }
.nd-row { display: flex; gap: 8px; margin: 3px 0; color: #2f455e; }
.nd-row b { color: #6f859c; font-weight: 600; min-width: 34px; }
.nd-val { font-weight: 700; color: #1f2f43; }
.nd-block b { color: #6f859c; font-weight: 600; }
.nd-block pre {
  margin: 4px 0 0;
  background: #f2f6fb;
  border: 1px solid #dce7f2;
  border-radius: 6px;
  padding: 6px 8px;
  font-size: 11px;
  color: #35516c;
  max-height: 140px;
  overflow: auto;
  white-space: pre-wrap;
}
.nd-block.err pre { background: #fff2f2; border-color: #f0caca; color: #a33a3a; }
.fade-enter-active, .fade-leave-active { transition: opacity 0.15s; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>
