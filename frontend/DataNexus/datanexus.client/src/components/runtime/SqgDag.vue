<template>
  <div
    class="dag-wrap"
    :class="{ 'is-resizing': isResizing }"
    :style="{ height: `${canvasHeight}px` }"
  >
    <div v-if="!nodes.length" class="dag-empty">暂无语义查询图</div>
    <button v-if="nodes.length" class="dag-reset" title="恢复自动布局" @click="resetLayout">⟲ 自动布局</button>
    <VueFlow
      v-if="nodes.length"
      :nodes="nodes"
      :edges="edges"
      :node-types="nodeTypes"
      :fit-view-on-init="true"
      :nodes-draggable="true"
      :nodes-connectable="false"
      :zoom-on-scroll="false"
      :prevent-scrolling="false"
      class="dag-canvas"
      @node-click="onNodeClick"
      @node-drag-stop="onNodeDragStop"
      @pane-click="closeDetail"
    >
      <Background pattern-color="#d9e2ee" :gap="24" :size="1.3" />
      <Controls :show-interactive="false" />
    </VueFlow>

    <transition name="fade">
      <div
        v-if="selected"
        class="node-detail"
        :class="{ 'is-maximized': detailMaximized }"
        @click.stop
      >
        <div class="nd-head">
          <span class="nd-op" :style="{ background: opColor(selected.operator) }">{{ selected.operator }}</span>
          <span class="nd-name">{{ selected.name || selected.id }}</span>
          <button
            type="button"
            class="nd-action"
            :title="detailMaximized ? '还原详情面板' : '最大化详情面板'"
            :aria-label="detailMaximized ? '还原详情面板' : '最大化详情面板'"
            @click.stop="toggleDetailSize"
          >
            <el-icon><ScaleToOriginal v-if="detailMaximized" /><FullScreen v-else /></el-icon>
          </button>
          <button type="button" class="nd-action nd-close" title="关闭详情面板" aria-label="关闭详情面板" @click.stop="closeDetail">✕</button>
        </div>
        <div class="nd-row" v-if="selected.depends_on?.length"><b>依赖</b><span>{{ selected.depends_on.join(', ') }}</span></div>
        <div class="nd-block" v-if="Object.keys(selected.inputs ?? {}).length"><b>输入</b><pre>{{ pretty(selected.inputs) }}</pre></div>
        <div class="nd-block"><b>Typed Spec</b><pre>{{ pretty(selected.spec) }}</pre></div>
      </div>
    </transition>

    <div
      v-if="nodes.length"
      class="dag-resize-handle"
      :class="{ active: isResizing }"
      role="separator"
      aria-label="调整语义查询图画布高度"
      aria-orientation="horizontal"
      tabindex="0"
      title="向下拖动延伸画布"
      @pointerdown.stop="startResize"
      @keydown.down.prevent="resizeBy(40)"
      @keydown.up.prevent="resizeBy(-40)"
    ><span></span></div>
  </div>
</template>

<script setup lang="ts">
import { computed, markRaw, nextTick, ref } from 'vue'
import { FullScreen, ScaleToOriginal } from '@element-plus/icons-vue'
import { VueFlow, useVueFlow } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import '@vue-flow/core/dist/style.css'
import '@vue-flow/core/dist/theme-default.css'
import '@vue-flow/controls/dist/style.css'
import { computeWaves, positionMap, buildEdges, operatorColor, dagNode } from './dag'
import DagNode from './DagNode.vue'
import { useResizableDag } from './useResizableDag'

const nodeTypes: any = { dagNode: markRaw(DagNode) }

interface SqgNode {
  id: string
  operator: string
  name?: string
  spec: Record<string, unknown>
  depends_on?: string[]
  inputs?: Record<string, { node: string; output?: string; row?: number }>
}
const props = defineProps<{ sqg: { nodes?: SqgNode[] } | null }>()

const rawNodes = computed<SqgNode[]>(() => props.sqg?.nodes ?? [])
const selectedId = ref<string | null>(null)
const detailMaximized = ref(false)
const { canvasHeight, isResizing, startResize, resizeBy } = useResizableDag(300)
const { fitView } = useVueFlow()

// 拖动后的位置覆盖（id → 坐标）；空则用自动布局。恢复布局 = 清空。
const posOverride = ref<Record<string, { x: number; y: number }>>({})
const layoutPos = computed(() => positionMap(computeWaves(rawNodes.value)))

function onNodeDragStop(e: { node: { id: string; position: { x: number; y: number } } }) {
  posOverride.value = { ...posOverride.value, [e.node.id]: { ...e.node.position } }
}
function resetLayout() {
  posOverride.value = {}
  nextTick(() => fitView({ padding: 0.15 }))
}

const nodes = computed(() => {
  const ns = rawNodes.value
  const pos = layoutPos.value
  const over = posOverride.value
  return ns.map((n) =>
    dagNode(n.id, over[n.id] ?? pos.get(n.id) ?? { x: 0, y: 0 }, {
      name: n.name || n.id,
      badge: n.operator,
      color: operatorColor(n.operator),
      selected: n.id === selectedId.value,
    }),
  )
})

// 选中节点的上游 + 下游相关连线 id（点击后高亮）
const relatedEdgeIds = computed<Set<string>>(() => {
  const sel = selectedId.value
  const out = new Set<string>()
  if (!sel) return out
  const ns = rawNodes.value
  const parents = new Map<string, string[]>()
  const children = new Map<string, string[]>()
  for (const n of ns) {
    parents.set(n.id, n.depends_on ?? [])
    for (const d of n.depends_on ?? []) {
      if (!children.has(d)) children.set(d, [])
      children.get(d)!.push(n.id)
    }
  }
  const up = new Set<string>([sel])
  const down = new Set<string>([sel])
  const su = [sel]
  while (su.length) { const x = su.pop()!; for (const p of parents.get(x) ?? []) if (!up.has(p)) { up.add(p); su.push(p) } }
  const sd = [sel]
  while (sd.length) { const x = sd.pop()!; for (const c of children.get(x) ?? []) if (!down.has(c)) { down.add(c); sd.push(c) } }
  for (const n of ns) for (const d of n.depends_on ?? []) {
    if ((up.has(d) && up.has(n.id)) || (down.has(d) && down.has(n.id))) out.add(`${d}->${n.id}`)
  }
  return out
})

const edges = computed(() => {
  const rel = relatedEdgeIds.value
  return buildEdges(rawNodes.value).map((e) => {
    const on = rel.has(e.id as string)
    return {
      ...e,
      class: on ? 'edge-hl' : '',
      animated: on ? true : e.animated,
      style: on ? { ...(e.style as object), strokeWidth: 2.6 } : e.style,
    }
  })
})

const selected = computed(() => rawNodes.value.find((n) => n.id === selectedId.value) || null)
function onNodeClick(e: { node: { id: string } }) {
  selectedId.value = e.node.id
  detailMaximized.value = false
}
function closeDetail() {
  selectedId.value = null
  detailMaximized.value = false
}
function toggleDetailSize() {
  detailMaximized.value = !detailMaximized.value
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
.dag-wrap.is-resizing { user-select: none; }
.dag-canvas { width: 100%; height: 100%; }
.dag-reset {
  position: absolute;
  top: 10px; left: 10px; z-index: 5;
  font-size: 12px; color: #3f566f; cursor: pointer;
  background: #fff; border: 1px solid #dbe5f2; border-radius: 8px;
  padding: 4px 10px; line-height: 1.4;
  box-shadow: 0 4px 12px rgba(20, 40, 70, 0.12);
  transition: background 0.15s, border-color 0.15s;
}
.dag-reset:hover { background: #f1f6fb; border-color: #7c5cff; color: #5b3fd6; }
.dag-empty {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--tech-dim);
  font-size: 13px;
}
/* 选中节点的上下游连线高亮：柔和发光 + 流动虚线 */
:deep(.vue-flow__edge.edge-hl .vue-flow__edge-path) {
  filter: drop-shadow(0 0 3px rgba(124, 92, 255, 0.55));
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
  max-height: calc(100% - 20px);
  overflow: auto;
  z-index: 8;
  box-sizing: border-box;
  transition: inset 0.16s ease, width 0.16s ease, border-radius 0.16s ease;
}
.node-detail.is-maximized {
  inset: 0;
  width: auto;
  max-height: none;
  border: 0;
  border-radius: 11px;
  padding: 16px 18px 22px;
}
.nd-head { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.node-detail.is-maximized .nd-head {
  position: sticky;
  top: -16px;
  z-index: 2;
  margin: -16px 0 10px;
  padding: 16px 0 10px;
  border-bottom: 1px solid #e3ebf4;
  background: #fff;
}
.nd-op { color: #fff; font-size: 10px; padding: 2px 6px; border-radius: 4px; }
.nd-name { font-weight: 700; flex: 1; color: #1f2f43; }
.nd-action {
  width: 24px;
  height: 24px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 auto;
  padding: 0;
  border: 0;
  border-radius: 5px;
  background: transparent;
  color: #7a8da3;
  cursor: pointer;
}
.nd-action:hover { color: #146f8b; background: #edf5fa; }
.nd-action .el-icon { font-size: 15px; }
.nd-close { font-size: 14px; }
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
.node-detail.is-maximized .nd-block pre { max-height: none; }
.dag-resize-handle {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  height: 11px;
  z-index: 20;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: ns-resize;
  touch-action: none;
  outline: none;
}
.dag-resize-handle span {
  width: 54px;
  height: 3px;
  border-radius: 3px;
  background: #aebfd1;
  opacity: 0.72;
  transition: width 0.15s, background 0.15s, opacity 0.15s;
}
.dag-resize-handle:hover span,
.dag-resize-handle:focus-visible span,
.dag-resize-handle.active span {
  width: 78px;
  background: #177c99;
  opacity: 1;
}
.fade-enter-active, .fade-leave-active { transition: opacity 0.15s; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>
