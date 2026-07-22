<template>
  <div class="onto-canvas">
    <VueFlow
      :nodes="nodes"
      :edges="edges"
      :node-types="nodeTypes"
      :fit-view-on-init="true"
      :nodes-draggable="editable"
      :nodes-connectable="editable"
      :edges-updatable="false"
      :zoom-on-scroll="true"
      class="oc-flow"
      @node-drag-stop="onDragStop"
      @node-click="onNodeClick"
      @edge-click="onEdgeClick"
      @connect="onConnect"
    >
      <Background pattern-color="#d9e2ee" :gap="24" :size="1.3" />
      <Controls :show-interactive="false" />
    </VueFlow>
    <div v-if="!nodes.length" class="oc-empty">
      画板为空。点「导入实体」从数据源选表，或从右侧添加。
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, markRaw } from 'vue'
import { VueFlow, type Connection, type NodeMouseEvent, type EdgeMouseEvent } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import '@vue-flow/core/dist/style.css'
import '@vue-flow/core/dist/theme-default.css'
import '@vue-flow/controls/dist/style.css'
import EntityNode from './EntityNode.vue'
import type { OntologyGraph } from '../../../bff/Ontology.js'

const props = defineProps<{ graph: OntologyGraph; editable: boolean; selectedEntity?: string | null }>()
const emit = defineEmits<{
  (e: 'layout', id: string, x: number, y: number): void
  (e: 'connect', from: string, to: string): void
  (e: 'select-entity', id: string): void
  (e: 'select-relation', id: string): void
}>()

const nodeTypes: any = { entity: markRaw(EntityNode) }

const nodes = computed(() =>
  props.graph.entities.map((en, i) => ({
    id: en.id,
    type: 'entity',
    position: en.layout || { x: 80 + (i % 3) * 300, y: 80 + Math.floor(i / 3) * 300 },
    data: {
      name: en.name,
      table: en.table,
      selected: en.id === props.selectedEntity,
      isFact: /fact/i.test(en.table || en.name || ''),
      attributes: en.attributes.map((a) => ({
        id: a.id, name: a.name, role: a.role,
        isKey: (Array.isArray(en.key) ? en.key : en.key ? [en.key] : []).includes(a.column || a.name),
      })),
    },
  })),
)

const edges = computed(() =>
  props.graph.relations.map((r) => ({
    id: r.id,
    source: r.from.entity,
    target: r.to.entity,
    label: relationLabel(r),
    type: 'smoothstep',
    animated: false,
    style: { stroke: r.confirmation?.required && !r.confirmation.confirmed ? '#d08a2f' : '#b6c5d8', strokeWidth: 1.8 },
    labelStyle: { fill: '#52657a', fontSize: '11px', fontWeight: 600 },
    labelShowBg: true,
    labelBgStyle: { fill: '#ffffff', stroke: '#e4e9ef' },
    labelBgPadding: [6, 3] as [number, number],
    labelBgBorderRadius: 6,
  })),
)

function endpointNames(entityId: string, value: string | string[]) {
  const entity = props.graph.entities.find((item) => item.id === entityId)
  const ids = Array.isArray(value) ? value : [value]
  return ids.map((id) => entity?.attributes.find((attribute) => attribute.id === id)?.column || id).join(', ')
}
function relationLabel(r: any) {
  const left = r.multiplicity?.to_from?.max === 1 ? '1' : r.multiplicity?.to_from?.max === 'many' ? 'N' : '?'
  const right = r.multiplicity?.from_to?.max === 1 ? '1' : r.multiplicity?.from_to?.max === 'many' ? 'N' : '?'
  const optional = `${r.multiplicity?.from_to?.min === 1 ? '必选' : r.multiplicity?.from_to?.min === 0 ? '可选' : '未知'} / ${r.multiplicity?.to_from?.min === 1 ? '必选' : r.multiplicity?.to_from?.min === 0 ? '可选' : '未知'}`
  const pending = r.confirmation?.required && !r.confirmation.confirmed ? ' · 待确认' : ''
  return `${endpointNames(r.from.entity, r.from.attribute)} = ${endpointNames(r.to.entity, r.to.attribute)} · ${left}:${right} · ${optional}${pending}`
}

function onDragStop(e: NodeMouseEvent) {
  const n = e.node
  emit('layout', n.id, Math.round(n.position.x), Math.round(n.position.y))
}
function onNodeClick(e: NodeMouseEvent) {
  emit('select-entity', e.node.id)
}
function onEdgeClick(e: EdgeMouseEvent) {
  emit('select-relation', e.edge.id)
}
function onConnect(c: Connection) {
  if (c.source && c.target && c.source !== c.target) emit('connect', c.source, c.target)
}
</script>

<style scoped>
.onto-canvas { position: relative; width: 100%; height: 100%; background:
  #f4f8fd; }
.oc-flow { width: 100%; height: 100%; }
.oc-empty {
  position: absolute; inset: 0; display: flex; align-items: center; justify-content: center;
  color: var(--beone-text-secondary); font-size: 13px; pointer-events: none;
}
:deep(.vue-flow__node-entity) { background: none; border: none; padding: 0; box-shadow: none; width: auto; }
:deep(.vue-flow__controls) {
  box-shadow: 0 8px 20px rgba(20, 40, 70, 0.16);
  border: 1px solid #dbe5f2;
  border-radius: 10px;
  overflow: hidden;
}
:deep(.vue-flow__controls-button) {
  background: #fff;
  color: #3f566f;
}
:deep(.vue-flow__controls-button:hover) {
  background: #f1f6fb;
}
</style>
