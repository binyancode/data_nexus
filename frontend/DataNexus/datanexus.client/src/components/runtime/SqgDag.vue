<template>
  <div class="dag-wrap">
    <div v-if="!nodes.length" class="dag-empty">暂无语义查询图</div>
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
          <span class="nd-op" :style="{ background: opColor(selected.operator) }">{{ selected.operator }}</span>
          <span class="nd-name">{{ selected.name || selected.id }}</span>
          <span class="nd-close" @click="selectedId = null">✕</span>
        </div>
        <div class="nd-row" v-if="selected.concept"><b>概念</b><span>{{ selected.concept }}</span></div>
        <div class="nd-row" v-if="selected.depends_on?.length"><b>依赖</b><span>{{ selected.depends_on.join(', ') }}</span></div>
        <div class="nd-block" v-if="hasParams"><b>参数</b><pre>{{ pretty(selected.params) }}</pre></div>
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
import { computeWaves, positionMap, buildEdges, operatorColor, dagNode } from './dag'
import DagNode from './DagNode.vue'

const nodeTypes: any = { dagNode: markRaw(DagNode) }

interface SqgNode {
  id: string
  operator: string
  name?: string
  concept?: string
  params?: Record<string, unknown>
  depends_on?: string[]
}
const props = defineProps<{ sqg: { nodes?: SqgNode[] } | null }>()

const rawNodes = computed<SqgNode[]>(() => props.sqg?.nodes ?? [])
const selectedId = ref<string | null>(null)

const nodes = computed(() => {
  const ns = rawNodes.value
  const pos = positionMap(computeWaves(ns))
  return ns.map((n) =>
    dagNode(n.id, pos.get(n.id) ?? { x: 0, y: 0 }, {
      name: n.name || n.id,
      badge: n.operator,
      color: operatorColor(n.operator),
      selected: n.id === selectedId.value,
    }),
  )
})
const edges = computed(() => buildEdges(rawNodes.value))

const selected = computed(() => rawNodes.value.find((n) => n.id === selectedId.value) || null)
const hasParams = computed(() => selected.value?.params && Object.keys(selected.value.params).length > 0)

function onNodeClick(e: { node: { id: string } }) {
  selectedId.value = e.node.id
}
function opColor(op?: string) {
  return operatorColor(op)
}
function pretty(v: unknown) {
  return JSON.stringify(v, null, 2)
}
</script>

<style scoped>
.dag-wrap {
  position: relative;
  width: 100%;
  height: 300px;
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
.node-detail {
  position: absolute;
  top: 10px;
  right: 10px;
  width: 240px;
  background: #ffffff;
  border: 1px solid #dbe5f2;
  border-radius: 10px;
  box-shadow: 0 12px 30px rgba(16, 24, 40, 0.14);
  padding: 10px 12px;
  font-size: 12px;
}
.nd-head { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.nd-op { color: #fff; font-size: 10px; padding: 2px 6px; border-radius: 4px; }
.nd-name { font-weight: 700; flex: 1; color: #1f2f43; }
.nd-close { cursor: pointer; color: #7a8da3; }
.nd-row { display: flex; gap: 8px; margin: 3px 0; color: #2f455e; }
.nd-row b { color: #6f859c; font-weight: 600; min-width: 34px; }
.nd-block b { color: #6f859c; font-weight: 600; }
.nd-block pre {
  margin: 4px 0 0;
  background: #f2f6fb;
  border: 1px solid #dce7f2;
  border-radius: 6px;
  padding: 6px 8px;
  font-size: 11px;
  color: #35516c;
  max-height: 150px;
  overflow: auto;
  white-space: pre-wrap;
}
.fade-enter-active, .fade-leave-active { transition: opacity 0.15s; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>
