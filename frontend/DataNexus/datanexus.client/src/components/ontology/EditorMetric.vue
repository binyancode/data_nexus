<template>
  <div class="ked">
    <div class="note">
      <el-icon><InfoFilled /></el-icon>
      指标用<b>属性</b>来表达，例如 <code>SUM(销售·金额 − 销售·成本)</code>。属性自带所属实体，引擎据此<b>自动推导表与 JOIN</b>，无需选单一实体。
    </div>

    <div class="ef">
      <label>聚合表达式</label>
      <el-input ref="exprRef" v-model="expr" type="textarea" :rows="2" class="mono"
                placeholder="点下方按钮/属性插入，如 SUM(attribute.sales.amount - attribute.sales.cost)" />
      <div class="tools">
        <button v-for="fn in fns" :key="fn" class="chip fn" @mousedown.prevent="insert(fn + '(')">{{ fn }}()</button>
        <span class="sep"></span>
        <button v-for="op in ops" :key="op" class="chip op" @mousedown.prevent="insert(' ' + op + ' ')">{{ op }}</button>
        <button class="chip op" @mousedown.prevent="insert(')')">)</button>
      </div>
    </div>

    <div class="ef">
      <label>可用属性（点击插入）</label>
      <div v-if="!attrGroups.length" class="attr-empty">还没有属性概念。先建 attribute 类别的概念（列在实体上）。</div>
      <div v-for="g in attrGroups" :key="g.key" class="ag">
        <div class="ag-h"><span class="ag-dot"></span>{{ g.entityName }}</div>
        <div class="ag-body">
          <button v-for="a in g.items" :key="a.id" class="chip attr" @mousedown.prevent="insert(a.id)" :title="a.id">
            {{ a.name }}
          </button>
        </div>
      </div>
    </div>

    <div class="preview" v-if="expr">
      <div class="pv-row"><span class="pv-k">预览</span><code>{{ prettyExpr }}</code></div>
      <div class="pv-row"><span class="pv-k">涉及实体</span>
        <span v-if="involvedEntities.length" class="ents">
          <span v-for="e in involvedEntities" :key="e" class="ent-tag">{{ entityName(e) }}</span>
        </span>
        <span v-else class="pv-warn">未识别到属性引用</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { attrField } from './attrs'
import type { Concept } from '../../bff/Ontology'

const attrs = defineModel<Record<string, any>>('attrs', { default: () => ({}) })
const props = defineProps<{ concepts: Concept[] }>()

const expr = attrField<string>(attrs, 'expr')
const exprRef = ref<any>(null)
const fns = ['SUM', 'AVG', 'COUNT', 'MIN', 'MAX']
const ops = ['+', '-', '*', '/']

const attributes = computed(() => props.concepts.filter((c) => c.kind === 'attribute'))
function attrEntity(c: Concept): string {
  try { return (JSON.parse(c.attrs || '{}') || {}).entity || '' } catch { return '' }
}
function entityName(id: string): string {
  return props.concepts.find((c) => c.id === id)?.name || id
}
const attrGroups = computed(() => {
  const map = new Map<string, { key: string; entityName: string; items: Concept[] }>()
  for (const a of attributes.value) {
    const ent = attrEntity(a)
    const key = ent || '__none__'
    if (!map.has(key)) map.set(key, { key, entityName: ent ? entityName(ent) : '（未指定实体）', items: [] })
    map.get(key)!.items.push(a)
  }
  return [...map.values()]
})

function insert(token: string) {
  const ta = exprRef.value?.textarea as HTMLTextAreaElement | undefined
  const cur = expr.value || ''
  if (!ta) { expr.value = cur + token; return }
  const s = ta.selectionStart ?? cur.length
  const e = ta.selectionEnd ?? cur.length
  expr.value = cur.slice(0, s) + token + cur.slice(e)
  const pos = s + token.length
  requestAnimationFrame(() => { ta.focus(); ta.setSelectionRange(pos, pos) })
}

const attrToken = /attribute(?:\.[A-Za-z0-9_]+)+/g
const prettyExpr = computed(() =>
  (expr.value || '').replace(attrToken, (id) => {
    const c = props.concepts.find((x) => x.id === id)
    if (!c) return id
    const ent = attrEntity(c)
    return ent ? `${entityName(ent)}·${c.name}` : c.name
  }),
)
const involvedEntities = computed(() => {
  const ids = (expr.value || '').match(attrToken) || []
  const ents: string[] = []
  for (const id of ids) {
    const c = props.concepts.find((x) => x.id === id)
    const ent = c ? attrEntity(c) : ''
    if (ent && !ents.includes(ent)) ents.push(ent)
  }
  return ents
})
</script>

<style scoped>
.ked { display: flex; flex-direction: column; gap: 14px; }
.ef label { display: block; font-size: 12px; color: var(--beone-text-secondary); margin-bottom: 4px; }
.mono :deep(.el-textarea__inner) { font-family: 'Cascadia Code', Consolas, monospace; }
.note {
  display: block; font-size: 12px;
  color: var(--beone-text-regular); background: var(--beone-bg-midnight-soft);
  border-radius: 8px; padding: 10px 12px; line-height: 1.6;
}
.note :deep(.el-icon) { margin-right: 6px; vertical-align: -0.15em; color: var(--beone-cerulean-blue); }
.note b { color: var(--beone-text-primary); }
.note code { color: var(--beone-cerulean-blue); font-family: 'Cascadia Code', Consolas, monospace; }

.tools { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin-top: 8px; }
.sep { width: 1px; height: 18px; background: var(--beone-border); margin: 0 4px; }
.chip {
  border: 1px solid var(--beone-border); background: var(--beone-bg-panel); cursor: pointer;
  border-radius: 6px; font-size: 12px; padding: 3px 9px; color: var(--beone-text-regular);
  font-family: 'Cascadia Code', Consolas, monospace;
}
.chip:hover { border-color: var(--beone-cerulean-blue); color: var(--beone-cerulean-blue); }
.chip.fn { color: var(--beone-cerulean-blue); }
.chip.op { min-width: 26px; text-align: center; }
.chip.attr { font-family: inherit; }

.attr-empty { font-size: 12px; color: var(--beone-text-secondary); }
.ag { margin-bottom: 8px; }
.ag-h { display: flex; align-items: center; gap: 6px; font-size: 11px; color: var(--beone-text-secondary); margin-bottom: 5px; }
.ag-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--beone-cerulean-blue); }
.ag-body { display: flex; flex-wrap: wrap; gap: 6px; }

.preview { font-size: 12px; background: var(--beone-bg-panel-muted); border: 1px solid var(--beone-border); border-radius: 8px; padding: 10px 12px; display: flex; flex-direction: column; gap: 6px; }
.pv-row { display: flex; align-items: center; gap: 8px; }
.pv-k { color: var(--beone-text-secondary); flex: 0 0 auto; width: 56px; }
.preview code { color: var(--beone-cerulean-blue); font-family: 'Cascadia Code', Consolas, monospace; }
.ents { display: flex; flex-wrap: wrap; gap: 6px; }
.ent-tag { background: var(--beone-bg-midnight-soft); color: var(--beone-text-primary); border-radius: 9px; padding: 1px 9px; }
.pv-warn { color: var(--beone-autumn-leaf); font-family: 'Cascadia Code', Consolas, monospace; }
</style>
