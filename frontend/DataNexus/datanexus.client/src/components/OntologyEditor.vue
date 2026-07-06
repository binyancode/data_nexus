<template>
  <div class="oe">
    <!-- 顶栏 -->
    <header class="oe-head">
      <button class="oe-back" @click="$emit('back')">← 本体列表</button>
      <div class="oe-title">
        <input v-if="meta?.canEdit" v-model="name" class="oe-name-in" placeholder="本体名称" />
        <span v-else class="oe-name">{{ name }}</span>
        <span class="oe-vis" :class="meta?.visibility">{{ visLabel }}</span>
        <span v-if="!meta?.canEdit" class="oe-ro">只读</span>
      </div>
      <div class="oe-actions" v-if="meta?.canEdit">
        <el-button size="small" @click="importOpen = true">导入实体</el-button>
        <el-button size="small" @click="refreshAll">刷新结构</el-button>
        <el-button size="small" @click="publishOpen = true">发布</el-button>
        <el-button size="small" type="primary" :loading="saving" @click="save">保存</el-button>
      </div>
    </header>

    <div class="oe-desc" v-if="meta?.canEdit">
      <textarea v-model="description" class="oe-desc-in" rows="2"
                placeholder="描述：这个本体能回答什么问题（给大模型/agent 理解，用于自动路由）"></textarea>
    </div>
    <div class="oe-desc ro" v-else-if="description">{{ description }}</div>

    <!-- 主体：画板 + 侧栏 -->
    <div class="oe-body" v-loading="loading" element-loading-text="加载本体…">
      <div class="oe-canvas">
        <OntologyCanvas
          :graph="graph" :editable="!!meta?.canEdit" :selected-entity="selEntityId"
          @layout="onLayout" @connect="onConnect"
          @select-entity="selectEntity" @select-relation="selectRelation" />
      </div>

      <div class="oe-splitter" :class="{ dragging: resizing }" @mousedown="startResize"></div>

      <aside class="oe-side" :style="{ width: sideWidth + 'px' }">
        <!-- 实体检视 -->
        <template v-if="selEntity">
          <div class="side-h">
            <span>实体 · {{ selEntity.name }}</span>
            <span class="sh-actions">
              <button v-if="meta?.canEdit" class="sh-refresh" title="从数据库刷新该表结构" @click="refreshEntity(selEntity)">⟳</button>
              <button class="x" @click="selEntityId = null">✕</button>
            </span>
          </div>
          <div class="fld"><label>名称</label><el-input v-model="selEntity.name" :disabled="!meta?.canEdit" size="small" /></div>
          <div class="fld"><label>语义</label><el-input v-model="selEntity.semantics" type="textarea" :rows="2" :disabled="!meta?.canEdit" /></div>
          <div class="fld"><label>物理表</label><el-input :model-value="selEntity.table || ''" disabled size="small" class="mono" /></div>
          <div class="fld"><label>主键</label>
            <el-select v-model="selEntity.key" size="small" :disabled="!meta?.canEdit" style="width:100%">
              <el-option v-for="a in selEntity.attributes" :key="a.id" :value="a.column || a.name" :label="a.column || a.name" />
            </el-select>
          </div>
          <div class="attr-list">
            <div class="al-h">
              <span>字段（{{ selEntity.attributes.length }}）· 维度可过滤/分组，度量可计算/过滤</span>
              <el-switch v-if="meta?.canEdit" :model-value="allAttrsEnabled" size="small"
                         title="全部启用 / 全部停用" @update:model-value="toggleAllAttrs" />
            </div>
            <template v-for="a in selEntity.attributes" :key="a.id">
              <div class="al-row" :class="{ off: a.enabled === false }">
                <span class="al-caret" @click="toggleAttr(a)">{{ selAttrId === a.id ? '▾' : '▸' }}</span>
                <span class="al-name clickable" @click="toggleAttr(a)">{{ a.name }}</span>
                <span class="al-dtype">{{ a.dtype || '?' }}</span>
                <span class="al-role" :class="a.role || 'dimension'">{{ a.role === 'measure' ? '度量' : '维度' }}</span>
                <el-switch :model-value="a.enabled !== false" :disabled="!meta?.canEdit" size="small"
                           @update:model-value="(v:any) => setAttrEnabled(a, v)" />
              </div>
              <div v-if="selAttrId === a.id" class="al-edit">
                <div class="fld"><label>名称</label>
                  <el-input v-model="a.name" :disabled="!meta?.canEdit" size="small" placeholder="业务名称" />
                </div>
                <div class="fld"><label>角色</label>
                  <el-select :model-value="a.role || 'dimension'" :disabled="!meta?.canEdit" size="small" style="width:100%"
                             @update:model-value="(v:any) => setAttrRole(a, v)">
                    <el-option value="dimension" label="维度（可过滤 / 可分组）" />
                    <el-option value="measure" label="度量（可计算 / 可过滤）" />
                  </el-select>
                </div>
                <div class="fld" v-if="a.role === 'measure'"><label>可加性（计算指导）</label>
                  <el-select v-model="a.additivity" :disabled="!meta?.canEdit" size="small" style="width:100%">
                    <el-option value="additive" label="可累加（任意维度可 SUM）" />
                    <el-option value="semi_additive" label="半可加（跨时间不可 SUM，如库存/余额）" />
                    <el-option value="non_additive" label="不可累加（比率/百分比/单价，禁 SUM）" />
                  </el-select>
                </div>
                <div class="fld"><label>同义词</label>
                  <el-select v-model="a.synonyms" multiple filterable allow-create default-first-option
                             :disabled="!meta?.canEdit" size="small" style="width:100%" placeholder="回车添加" />
                </div>
                <div class="fld"><label>描述（给大模型的提示）</label>
                  <el-input v-model="a.semantics" type="textarea" :rows="2" :disabled="!meta?.canEdit" size="small"
                            placeholder="如：字符串型季度，格式 YYYYQn（2025Q1）；「第一季度」→ 2025Q1" />
                </div>
                <div class="fld"><label>物理列 · 类型</label>
                  <el-input :model-value="`${a.column || ''}  ·  ${a.dtype || '?'}`" disabled size="small" class="mono" />
                </div>
              </div>
            </template>
          </div>
          <el-button v-if="meta?.canEdit" size="small" type="danger" plain @click="deleteEntity">删除实体</el-button>
        </template>

        <!-- 概念列表：指标 / 派生 / 动作 -->
        <template v-else>
          <!-- 本体能力源（挂载的 resolver）：SQL 随实体自动，agent/action 手动 -->
          <div class="rsrc">
            <div class="rsrc-h">
              <span>能力源（{{ (graph.resolvers || []).length }}）</span>
              <el-button v-if="meta?.canEdit" size="small" text @click="attachOpen = true">＋ 挂载</el-button>
            </div>
            <div v-if="(graph.resolvers || []).length" class="rsrc-list">
              <span v-for="r in graph.resolvers" :key="r.name" class="rsrc-chip" :class="r.type">
                <span class="rc-dot"></span>{{ r.name }}<span class="rc-type">{{ r.type }}</span>
                <button v-if="meta?.canEdit && r.type !== 'sql'" class="rc-x" title="卸载" @click="detachResolver(r.name)">✕</button>
              </span>
            </div>
            <div v-else class="rsrc-empty">未挂载任何源。导入实体会自动挂 SQL 源；agent/action 点「挂载」。</div>
          </div>

          <div class="seg3">
            <button v-for="t in tabs" :key="t.k" :class="{ on: tab === t.k }" @click="tab = t.k">{{ t.label }}</button>
          </div>

          <div class="cl-head">
            <span>{{ tabLabel }}（{{ currentList.length }}）</span>
            <el-button v-if="meta?.canEdit" size="small" @click="addConcept">＋ 新增</el-button>
          </div>

          <div class="cl-list">
            <template v-for="it in currentList" :key="it.id">
              <div class="cl-item" :class="{ active: it.id === selConceptId }"
                   @click="selConceptId = selConceptId === it.id ? null : it.id">
                <div class="cli-text">
                  <span class="cli-name">{{ it.name }}</span>
                  <span class="cli-id">{{ it.id }}</span>
                </div>
                <span class="cli-caret">{{ it.id === selConceptId ? '−' : '+' }}</span>
              </div>
              <!-- 概念编辑（手风琴：展开在点击项下方） -->
              <div v-if="it.id === selConceptId && selConcept" class="cl-edit">
                <div class="fld"><label>名称</label><el-input v-model="selConcept.name" :disabled="!meta?.canEdit" size="small" @input="onNameInput" /></div>
                <div class="fld"><label>ID</label><el-input v-model="selConcept.id" :disabled="!meta?.canEdit || !isNewId" size="small" class="mono" /></div>
                <div class="fld"><label>语义</label><el-input v-model="selConcept.semantics" type="textarea" :rows="2" :disabled="!meta?.canEdit" /></div>
                <div class="fld"><label>同义词</label>
                  <el-select v-model="selConcept.synonyms" multiple filterable allow-create default-first-option
                             :disabled="!meta?.canEdit" size="small" style="width:100%" />
                </div>
                <component :is="editorFor" v-if="editorFor" v-model:attrs="conceptAttrs" :concepts="pseudoConcepts" />
                <el-button v-if="meta?.canEdit" size="small" type="danger" plain @click="deleteConcept">删除</el-button>
              </div>
            </template>
            <div v-if="!currentList.length" class="cl-empty">暂无</div>
          </div>
        </template>
      </aside>
    </div>

    <!-- 关系对话框 -->
    <el-dialog v-model="relDlg" :title="relEditing ? '编辑关系' : '新建关系'" width="460px" class="rel-dialog">
      <div v-if="relForm" class="rel-dlg">
        <div class="rd-card">
          <div class="rd-tag">从</div>
          <div class="rd-ent">{{ entName(relForm.from_entity) }}</div>
          <el-select v-model="relForm.from_key" placeholder="选择关联键" class="rd-sel">
            <el-option v-for="c in entCols(relForm.from_entity)" :key="c" :value="c" :label="c" />
          </el-select>
        </div>

        <div class="rd-join">
          <span class="rd-line"></span>
          <span class="rd-badge">＝</span>
          <span class="rd-line"></span>
        </div>

        <div class="rd-card">
          <div class="rd-tag to">到</div>
          <div class="rd-ent">{{ entName(relForm.to_entity) }}</div>
          <el-select v-model="relForm.to_key" placeholder="选择关联键" class="rd-sel">
            <el-option v-for="c in entCols(relForm.to_entity)" :key="c" :value="c" :label="c" />
          </el-select>
        </div>
      </div>
      <template #footer>
        <div class="rd-footer">
          <el-button v-if="relEditing" type="danger" plain @click="deleteRelation">删除</el-button>
          <span class="rd-spacer"></span>
          <el-button @click="relDlg = false">取消</el-button>
          <el-button type="primary" @click="saveRelation">确定</el-button>
        </div>
      </template>
    </el-dialog>

    <!-- 发布对话框 -->
    <el-dialog v-model="publishOpen" title="发布本体" width="460px">
      <div class="fld"><label>可见性</label>
        <el-radio-group v-model="pubVis">
          <el-radio value="private">私有（仅自己）</el-radio>
          <el-radio value="shared">指定用户</el-radio>
          <el-radio value="public">所有人</el-radio>
        </el-radio-group>
      </div>
      <div class="fld" v-if="pubVis === 'shared'"><label>授权用户（邮箱，回车添加）</label>
        <el-select v-model="pubGrants" multiple filterable allow-create default-first-option
                   placeholder="user@domain" style="width:100%" />
      </div>
      <template #footer>
        <el-button @click="publishOpen = false">取消</el-button>
        <el-button type="primary" :loading="publishing" @click="doPublish">发布</el-button>
      </template>
    </el-dialog>

    <ImportWizard v-model="importOpen" @imported="onImported" />

    <!-- 挂载能力源（无 concept 的 resolver：agent/action） -->
    <el-dialog v-model="attachOpen" title="挂载能力源" width="440px">
      <div class="fld">
        <label>选择一个能力源（agent / action）</label>
        <el-select v-model="attachPick" style="width:100%" placeholder="选择 resolver" filterable>
          <el-option v-for="r in attachable" :key="r.name" :value="r.name"
                     :label="`${r.name}（${r.type}）`" />
        </el-select>
        <div v-if="!attachable.length" class="hint">没有可挂载的能力源。请先到「源管理」新增 agent / action 源。</div>
      </div>
      <template #footer>
        <el-button @click="attachOpen = false">取消</el-button>
        <el-button type="primary" :disabled="!attachPick" @click="attachResolver">挂载</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import OntologyCanvas from './ontology/canvas/OntologyCanvas.vue'
import ImportWizard from './ontology/ImportWizard.vue'
import EditorMetric from './ontology/EditorMetric.vue'
import EditorDerivation from './ontology/EditorDerivation.vue'
import EditorAction from './ontology/EditorAction.vue'
import {
  getOntology, saveOntology, publishOntology, emptyGraph,
  type OntologyFull, type OntologyGraph, type OntologyMeta,
} from '../bff/Ontology.js'
import type { ImportFragment } from '../backend/Resolvers.js'
import { listResolvers, resolverSchema, type ResolverInfo } from '../backend/Resolvers.js'

const props = defineProps<{ ontologyId: string }>()
defineEmits<{ (e: 'back'): void }>()

const meta = ref<OntologyMeta | null>(null)
const graph = ref<OntologyGraph>(emptyGraph())
const name = ref('')
const description = ref('')
const saving = ref(false)
const loading = ref(true)          // 初始即加载态，打开时立刻显示

const visLabel = computed(() => ({ private: '私有', shared: '共享', public: '公开' } as any)[meta.value?.visibility || 'private'])

// 侧栏宽度可拖拽
const sideWidth = ref(360)
const resizing = ref(false)
function startResize(e: MouseEvent) {
  e.preventDefault()
  resizing.value = true
  const startX = e.clientX
  const startW = sideWidth.value
  const onMove = (ev: MouseEvent) => {
    // 侧栏在右侧：向左拖变宽
    sideWidth.value = Math.min(720, Math.max(280, startW - (ev.clientX - startX)))
  }
  const onUp = () => {
    resizing.value = false
    window.removeEventListener('mousemove', onMove)
    window.removeEventListener('mouseup', onUp)
  }
  window.addEventListener('mousemove', onMove)
  window.addEventListener('mouseup', onUp)
}

onMounted(load)
async function load() {
  loading.value = true
  // 先拿到 resolver 能力（provides_concepts），syncSqlResolvers 才能正确区分能力源
  try { allResolvers.value = await listResolvers() } catch { /* ignore */ }
  try {
    const o: OntologyFull = await getOntology(props.ontologyId)
    meta.value = o
    name.value = o.name
    description.value = o.description || ''
    const g = o.graph || emptyGraph()
    graph.value = {
      entities: g.entities || [], relations: g.relations || [],
      metrics: g.metrics || [], derivations: g.derivations || [], actions: g.actions || [],
      resolvers: g.resolvers || [],
    }
    syncSqlResolvers()
  } catch (e: any) { ElMessage.error('加载失败：' + (e?.message || e)) }
  finally { loading.value = false }
}

// ── 本体挂载的 resolver（能力集）──
const allResolvers = ref<ResolverInfo[]>([])
const attachOpen = ref(false)
const attachPick = ref('')

function resolverType(nm: string): string {
  return allResolvers.value.find((r) => r.name === nm)?.type || 'sql'
}
// 无 concept 的可挂能力源（agent/action 等），且尚未挂载
const attachable = computed(() =>
  allResolvers.value.filter((r) => r.provides_concepts === false
    && !(graph.value.resolvers || []).some((x) => x.name === r.name)),
)
// SQL 源随实体自动挂载/摘除：把实体引用到的 resolver 补进来；不再被任何实体引用的“有concept源”摘除
function syncSqlResolvers() {
  const list = graph.value.resolvers || (graph.value.resolvers = [])
  const referenced = new Set(graph.value.entities.map((e) => (e as any).resolver).filter(Boolean))
  for (const nm of referenced) {
    if (!list.some((x) => x.name === nm)) list.push({ name: nm, type: resolverType(nm) })
  }
  // 摘除：仅对**已知有 concept 的源**（SQL）在无实体引用时摘除；agent/action 等手动挂载的保留
  graph.value.resolvers = list.filter((x) => {
    const info = allResolvers.value.find((r) => r.name === x.name)
    const conceptful = info?.provides_concepts === true
    return conceptful ? referenced.has(x.name) : true
  })
}
function attachResolver() {
  if (!attachPick.value) return
  const list = graph.value.resolvers || (graph.value.resolvers = [])
  if (!list.some((x) => x.name === attachPick.value)) {
    list.push({ name: attachPick.value, type: resolverType(attachPick.value) })
  }
  attachPick.value = ''
  attachOpen.value = false
}
function detachResolver(nm: string) {
  graph.value.resolvers = (graph.value.resolvers || []).filter((x) => x.name !== nm)
}

// ── 画板交互 ──
const selEntityId = ref<string | null>(null)
const selEntity = computed(() => graph.value.entities.find((e) => e.id === selEntityId.value) || null)
function selectEntity(id: string) { selEntityId.value = id }
const selAttrId = ref<string | null>(null)
function toggleAttr(a: any) {
  selAttrId.value = selAttrId.value === a.id ? null : a.id
}
function setAttrRole(a: any, role: string) {
  a.role = role
  if (role === 'measure') {
    if (!a.additivity) a.additivity = 'additive'
  } else {
    a.additivity = null
  }
}
// 启用/停用：停用的属性不进编译器/查询（默认 undefined = 启用）
const allAttrsEnabled = computed(() => (selEntity.value?.attributes || []).every((a: any) => a.enabled !== false))
function setAttrEnabled(a: any, v: boolean) { a.enabled = v }
function toggleAllAttrs(v: boolean) {
  for (const a of (selEntity.value?.attributes || []) as any[]) a.enabled = v
}

// ── 从数据库刷新表结构（只改结构属性 column/dtype，保留用户的 role/additivity/名称/同义词/语义）──
async function refreshEntity(ent: any): Promise<number> {
  if (!ent?.table || !ent?.resolver) return 0
  let schema: any
  try { schema = await resolverSchema(ent.resolver) } catch { ElMessage.error('探测失败'); return 0 }
  const cols: Array<{ column: string; dtype?: string }> = (schema?.tables || {})[ent.table] || []
  if (!cols.length) { ElMessage.warning(`表 ${ent.table} 未探测到字段`); return 0 }
  const byCol = new Map(cols.map((c) => [c.column, c]))
  const existing = new Map((ent.attributes as any[]).map((a) => [a.column || a.name, a]))
  const local = (t: string) => (t.split('.').pop() || t).replace(/[^A-Za-z0-9_]/g, '_')
  let added = 0, removed = 0
  // 更新已有列的结构属性；新增列按 dtype 定默认角色
  for (const c of cols) {
    const cur = existing.get(c.column)
    if (cur) {
      cur.dtype = c.dtype || 'unknown'   // 结构属性可更新；role/additivity/name/synonyms 保留
    } else {
      const dt = c.dtype || 'unknown'
      const isPk = ent.key && c.column === ent.key
      const role = (isPk || dt !== 'number') ? 'dimension' : 'measure'
      ent.attributes.push({
        id: `attribute.${local(ent.table)}.${c.column}`, name: c.column, column: c.column,
        role, dtype: dt, additivity: role === 'measure' ? 'additive' : null, synonyms: [], semantics: null,
      })
      added++
    }
  }
  // 移除数据库里已不存在的列
  const before = ent.attributes.length
  ent.attributes = (ent.attributes as any[]).filter((a) => byCol.has(a.column || a.name))
  removed = before - ent.attributes.length
  return added + removed
}

async function refreshAll() {
  if (!graph.value.entities.length) return
  let total = 0
  for (const e of graph.value.entities) total += await refreshEntity(e)
  ElMessage.success(total ? `已刷新，结构变更 ${total} 处` : '结构无变化')
}
function onLayout(id: string, x: number, y: number) {
  const e = graph.value.entities.find((en) => en.id === id)
  if (e) e.layout = { x, y }
}
function deleteEntity() {
  if (!selEntity.value) return
  const id = selEntity.value.id
  graph.value.entities = graph.value.entities.filter((e) => e.id !== id)
  graph.value.relations = graph.value.relations.filter((r) => r.from_entity !== id && r.to_entity !== id)
  selEntityId.value = null
  syncSqlResolvers()
}

// ── 关系 ──
const relDlg = ref(false)
const relEditing = ref(false)
const relForm = ref<any>(null)
function entName(id: string) { return graph.value.entities.find((e) => e.id === id)?.name || id }
function entCols(id: string) {
  const e = graph.value.entities.find((x) => x.id === id)
  return e ? e.attributes.map((a) => a.column || a.name) : []
}
function onConnect(from: string, to: string) {
  if (!meta.value?.canEdit) return
  relEditing.value = false
  const fe = graph.value.entities.find((e) => e.id === from)
  const te = graph.value.entities.find((e) => e.id === to)
  relForm.value = {
    id: `relation.${slug(from)}_${slug(to)}`,
    name: `${fe?.name}-${te?.name}`,
    from_entity: from, from_key: fe?.key || '', to_entity: to, to_key: te?.key || '',
  }
  relDlg.value = true
}
function selectRelation(id: string) {
  if (!meta.value?.canEdit) return
  const r = graph.value.relations.find((x) => x.id === id)
  if (!r) return
  relEditing.value = true
  relForm.value = { ...r }
  relDlg.value = true
}
function saveRelation() {
  const f = relForm.value
  if (!f.from_key || !f.to_key) { ElMessage.warning('请选择两侧关联键'); return }
  const idx = graph.value.relations.findIndex((r) => r.id === f.id)
  const rel = { id: f.id, name: f.name, from_entity: f.from_entity, from_key: f.from_key,
                to_entity: f.to_entity, to_key: f.to_key, synonyms: [], semantics: null }
  if (idx >= 0) graph.value.relations[idx] = rel as any
  else graph.value.relations.push(rel as any)
  relDlg.value = false
}
function deleteRelation() {
  graph.value.relations = graph.value.relations.filter((r) => r.id !== relForm.value.id)
  relDlg.value = false
}

// ── 指标 / 派生 / 动作 ──
type TabKey = 'metrics' | 'derivations' | 'actions'
const tabs: { k: TabKey; label: string }[] = [
  { k: 'metrics', label: '指标' }, { k: 'derivations', label: '派生' }, { k: 'actions', label: '动作' },
]
const tab = ref<TabKey>('metrics')
const tabLabel = computed(() => tabs.find((t) => t.k === tab.value)?.label || '')
const selConceptId = ref<string | null>(null)
const isNewId = ref(false)

const currentList = computed<any[]>(() => (graph.value as any)[tab.value] || [])
const selConcept = computed<any>(() => currentList.value.find((x) => x.id === selConceptId.value) || null)

const editorFor = computed(() => ({ metrics: EditorMetric, derivations: EditorDerivation, actions: EditorAction } as any)[tab.value])

// 给 kind 编辑器用的伪 concepts（把 graph 摊平成 Concept[] 形状）
const pseudoConcepts = computed(() => {
  const arr: any[] = []
  for (const e of graph.value.entities) {
    arr.push({ id: e.id, kind: 'entity', name: e.name, attrs: '{}' })
    for (const a of e.attributes) {
      arr.push({ id: a.id, kind: 'attribute', name: a.name, attrs: JSON.stringify({ entity: e.id, role: a.role }) })
    }
  }
  for (const m of graph.value.metrics) arr.push({ id: m.id, kind: 'metric', name: m.name, attrs: '{}' })
  return arr
})

// 把当前概念的 kind 专属字段暴露成 {attrs} 供编辑器 v-model
const conceptAttrs = computed<Record<string, any>>({
  get() {
    const c = selConcept.value
    if (!c) return {}
    if (tab.value === 'metrics') return { expr: c.expr }
    if (tab.value === 'derivations') return { prompt: c.prompt, inputs: c.inputs || [] }
    return { action: c.action, desc: c.desc }
  },
  set(v) {
    const c = selConcept.value
    if (!c) return
    if (tab.value === 'metrics') c.expr = v.expr
    else if (tab.value === 'derivations') { c.prompt = v.prompt; c.inputs = v.inputs }
    else { c.action = v.action; c.desc = v.desc }
  },
})

function addConcept() {
  const prefix = { metrics: 'metric', derivations: 'derivation', actions: 'action' }[tab.value]
  const id = `${prefix}.new_${Date.now().toString(36)}`
  const base: any = { id, name: '新概念', semantics: null, synonyms: [] }
  if (tab.value === 'metrics') base.expr = ''
  else if (tab.value === 'derivations') { base.prompt = ''; base.inputs = [] }
  else { base.action = ''; base.desc = '' }
  ;(graph.value as any)[tab.value].push(base)
  selConceptId.value = id
  isNewId.value = true
}
function onNameInput() {
  if (isNewId.value && selConcept.value) {
    const prefix = { metrics: 'metric', derivations: 'derivation', actions: 'action' }[tab.value]
    selConcept.value.id = `${prefix}.${slug(selConcept.value.name) || 'x'}`
  }
}
function deleteConcept() {
  const id = selConceptId.value
  ;(graph.value as any)[tab.value] = currentList.value.filter((x) => x.id !== id)
  selConceptId.value = null
}

// ── 导入 ──
const importOpen = ref(false)
function onImported(frag: ImportFragment) {
  const existing = new Set(graph.value.entities.map((e) => e.id))
  for (const e of frag.entities) if (!existing.has(e.id)) graph.value.entities.push(e as any)
  const relIds = new Set(graph.value.relations.map((r) => r.id))
  for (const r of frag.relations) if (!relIds.has(r.id)) graph.value.relations.push(r as any)
  syncSqlResolvers()
  ElMessage.success(`导入 ${frag.entities.length} 个实体、${frag.relations.length} 个关系`)
}

// ── 保存 / 发布 ──
async function save() {
  if (!name.value.trim()) { ElMessage.warning('请填写名称'); return }
  saving.value = true
  try {
    await saveOntology(props.ontologyId, name.value.trim(), description.value || null, graph.value)
    isNewId.value = false
    ElMessage.success('已保存')
  } catch (e: any) { ElMessage.error('保存失败：' + (e?.message || e)) }
  finally { saving.value = false }
}

const publishOpen = ref(false)
const publishing = ref(false)
const pubVis = ref('public')
const pubGrants = ref<string[]>([])
async function doPublish() {
  publishing.value = true
  try {
    await publishOntology(props.ontologyId, pubVis.value, pubGrants.value)
    if (meta.value) meta.value.visibility = pubVis.value as any
    publishOpen.value = false
    ElMessage.success('已发布')
  } catch (e: any) { ElMessage.error('发布失败：' + (e?.message || e)) }
  finally { publishing.value = false }
}

function slug(s: string) {
  return (s || '').toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '')
}
</script>

<style scoped>
.oe {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-width: 0;
  min-height: 0;
  height: 100%;
  background: #f2f6fb;
}
.oe-head {
  position: sticky;
  top: 0;
  z-index: 4;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 22px;
  background: rgba(255, 255, 255, 0.9);
  backdrop-filter: blur(6px);
  border-bottom: 1px solid #dbe4ef;
  box-shadow: 0 2px 10px rgba(16, 24, 40, 0.04);
}
.oe-back { border: 1px solid transparent; background: none; cursor: pointer; color: var(--beone-text-secondary); font-size: 13px; padding: 5px 9px; border-radius: 7px; }
.oe-back:hover { background: var(--beone-bg-panel-muted); color: var(--beone-text-primary); }
.oe-title { flex: 1; display: flex; align-items: center; gap: 10px; }
.oe-name { font-size: 16px; font-weight: 600; color: var(--beone-text-primary); }
.oe-name-in { font-size: 16px; font-weight: 600; border: 1px solid transparent; border-radius: 7px; padding: 4px 9px; background: transparent; color: var(--beone-text-primary); transition: background .15s, border-color .15s; }
.oe-name-in:hover { background: var(--beone-bg-panel-muted); }
.oe-name-in:focus { border-color: var(--beone-border-strong); background: #fff; outline: none; }
.oe-vis { font-size: 11px; padding: 2px 10px; border-radius: 20px; font-weight: 500; }
.oe-vis.private { background: #eef1f5; color: #64748b; }
.oe-vis.shared { background: #fdf0e2; color: #c2650a; }
.oe-vis.public { background: #e4f2f5; color: #0a7285; }
.oe-ro { font-size: 11px; color: var(--beone-text-secondary); background: var(--beone-bg-panel-muted); padding: 2px 8px; border-radius: 6px; }
.oe-desc { padding: 10px 22px 14px; background: transparent; }
.oe-desc.ro { color: var(--beone-text-regular); font-size: 13px; line-height: 1.6; }
.oe-desc-in { width: 100%; border: 1px solid transparent; border-radius: 8px; padding: 7px 11px; font-size: 13px; color: var(--beone-text-regular); font-family: inherit; line-height: 1.5; resize: vertical; display: block; box-sizing: border-box; background: var(--beone-bg-panel-muted); transition: background .15s, border-color .15s; }
.oe-desc-in:hover { background: #eef2f6; }
.oe-desc-in:focus { border-color: var(--beone-border-strong); background: #fff; outline: none; }
.oe-body { flex: 1; min-height: 0; display: flex; padding: 0 16px 16px; gap: 0; }
.oe-canvas {
  flex: 1;
  min-width: 0;
  border: 1px solid #dbe5f1;
  border-right: 0;
  border-radius: 14px 0 0 14px;
  overflow: hidden;
  background: #f6f9fd;
  box-shadow: 0 10px 26px rgba(18, 35, 62, 0.06);
}
.oe-splitter { width: 8px; flex: 0 0 auto; cursor: col-resize; background: #f6f9fd; border-left: 1px solid #dbe5f1; border-right: 1px solid #dbe5f1; position: relative; }
.oe-splitter::before { content: ''; position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); width: 2px; height: 26px; border-radius: 2px; background: var(--beone-border-strong); }
.oe-splitter::after { content: ''; position: absolute; inset: 0 -3px; }
.oe-splitter:hover, .oe-splitter.dragging { background: color-mix(in srgb, var(--beone-cerulean-blue) 10%, #fff); }
.oe-splitter:hover::before, .oe-splitter.dragging::before { background: var(--beone-cerulean-blue); }
.oe-side {
  flex: 0 0 auto;
  background: #ffffff;
  border: 1px solid #dbe5f1;
  border-left: 0;
  border-radius: 0 14px 14px 0;
  overflow-y: auto;
  padding: 16px 18px;
  box-shadow: 0 10px 26px rgba(18, 35, 62, 0.06);
}

.side-h { display: flex; align-items: center; justify-content: space-between; font-size: 14px; font-weight: 600; color: var(--beone-text-primary); margin-bottom: 14px; }
.side-h .x { border: 0; background: none; cursor: pointer; color: var(--beone-text-secondary); font-size: 15px; }
.side-h .x:hover { color: var(--beone-text-primary); }
.fld { margin-bottom: 11px; }
.fld label { display: block; font-size: 12px; color: var(--beone-text-secondary); margin-bottom: 5px; }
.mono :deep(.el-input__inner) { font-family: 'Cascadia Code', Consolas, monospace; }
.attr-list { margin: 12px 0; }
.al-h { display: flex; align-items: center; justify-content: space-between; gap: 8px; font-size: 12px; color: var(--beone-text-secondary); margin-bottom: 8px; }

.rsrc { margin-bottom: 14px; padding: 10px 12px; background: #f6f9fc; border: 1px solid #e4ebf3; border-radius: 10px; }
.rsrc-h { display: flex; align-items: center; justify-content: space-between; font-size: 12px; font-weight: 700; color: #55697f; margin-bottom: 8px; }
.rsrc-list { display: flex; flex-wrap: wrap; gap: 6px; }
.rsrc-chip {
  display: inline-flex; align-items: center; gap: 6px;
  font-size: 12px; color: #2f455e; background: #fff;
  border: 1px solid #d7e2ee; border-radius: 999px; padding: 3px 10px;
}
.rsrc-chip .rc-dot { width: 7px; height: 7px; border-radius: 50%; background: #5b7fa6; }
.rsrc-chip.agent .rc-dot { background: #7a5cd0; }
.rsrc-chip.action .rc-dot { background: #d0782f; }
.rc-type { font-size: 10px; color: #93a2b4; }
.rc-x { border: 0; background: none; cursor: pointer; color: #b0bccb; font-size: 11px; padding: 0; }
.rc-x:hover { color: #c24646; }
.rsrc-empty { font-size: 11px; color: #93a2b4; line-height: 1.5; }
.al-row { display: flex; align-items: center; gap: 8px; padding: 5px 0; border-bottom: 1px solid #f0f3f6; }
.al-row.off { opacity: 0.45; }
.al-caret { width: 12px; flex: 0 0 auto; font-size: 10px; color: #90a1b3; text-align: center; }
.al-name { flex: 1; font-size: 13px; color: var(--beone-text-regular); }
.al-name.clickable { cursor: pointer; }
.al-name.clickable:hover { color: var(--beone-cerulean-blue); }
.al-dtype { font-size: 10px; color: #93a2b4; font-family: 'Cascadia Code', Consolas, monospace; }
.al-role { font-size: 10px; border-radius: 4px; padding: 1px 7px; font-weight: 600; flex: 0 0 auto; }
.al-role.dimension { background: #eef1f5; color: #5b6b7f; }
.al-role.measure { background: #e7f4f1; color: #0f766e; }
.sh-actions { display: inline-flex; align-items: center; gap: 6px; }
.sh-refresh {
  border: 1px solid #d3dfec; background: #fff; cursor: pointer; color: #5f748a;
  width: 22px; height: 22px; border-radius: 6px; font-size: 13px; line-height: 1;
}
.sh-refresh:hover { background: #f1f6fb; color: #33475b; }
.al-edit {
  padding: 10px 10px 4px; margin: 2px 0 8px;
  background: #f7fafd; border: 1px solid #e6edf5; border-radius: 8px;
}

.seg3 { display: flex; gap: 6px; padding: 4px; border-radius: 10px; background: #f4f7fb; border: 1px solid #e4ebf3; margin-bottom: 14px; }
.seg3 button {
  flex: 1;
  border: 0;
  background: none;
  color: var(--beone-text-secondary);
  font-size: 13px;
  font-weight: 600;
  padding: 8px 0;
  cursor: pointer;
  border-radius: 7px;
  transition: color .15s, background .15s;
}
.seg3 button:hover { color: var(--beone-text-primary); }
.seg3 button.on { color: #fff; background: #3c82bf; box-shadow: 0 6px 12px rgba(60, 130, 191, 0.24); }
.cl-head { display: flex; align-items: center; justify-content: space-between; font-size: 13px; font-weight: 600; color: var(--beone-text-primary); margin-bottom: 10px; }
.cl-list { border: 1px solid var(--beone-border); border-radius: 10px; overflow: hidden; margin-bottom: 12px; background: #fff; }
.cl-item { display: flex; align-items: center; gap: 8px; padding: 9px 12px; cursor: pointer; border-bottom: 1px solid #f0f3f6; transition: background .12s; }
.cl-item:hover { background: var(--beone-bg-panel-muted); }
.cl-item.active { background: #f4f9fb; box-shadow: inset 3px 0 0 var(--beone-cerulean-blue); }
.cli-text { flex: 1; min-width: 0; }
.cli-caret { color: #aab4c0; font-size: 16px; width: 16px; text-align: center; flex: 0 0 auto; }
.cli-name { display: block; font-size: 13px; font-weight: 500; color: var(--beone-text-primary); }
.cli-id { display: block; font-size: 11px; color: var(--beone-text-secondary); font-family: 'Cascadia Code', Consolas, monospace; }
.cl-empty { padding: 16px; text-align: center; color: var(--beone-text-secondary); font-size: 12px; }
.cl-edit { border-bottom: 1px solid #eef2f6; background: #fbfcfe; padding: 14px 12px; }

.rel-dlg { display: flex; flex-direction: column; gap: 12px; }
.rd-card {
  position: relative;
  border: 1px solid #e2e9f2;
  border-radius: 12px;
  background: #f8fafd;
  padding: 14px 16px 16px;
}
.rd-tag {
  display: inline-block;
  font-size: 11px;
  font-weight: 700;
  color: #3f6ea5;
  background: #e5eefb;
  border-radius: 6px;
  padding: 2px 9px;
  margin-bottom: 8px;
}
.rd-tag.to { color: #2f8f74; background: #e5f5ef; }
.rd-ent {
  font-size: 14px;
  font-weight: 700;
  color: #26364d;
  margin-bottom: 10px;
  font-family: 'Cascadia Code', Consolas, monospace;
}
.rd-sel { width: 100%; }
.rd-join {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 4px;
}
.rd-line { flex: 1; height: 1px; background: #dbe3ee; }
.rd-badge {
  width: 26px; height: 26px; flex: 0 0 auto;
  display: inline-flex; align-items: center; justify-content: center;
  border-radius: 50%;
  background: #eef3fa; color: #5f748a; border: 1px solid #dbe3ee;
  font-size: 13px; font-weight: 700;
}
.rd-footer { display: flex; align-items: center; gap: 8px; }
.rd-spacer { flex: 1; }

@media (max-width: 900px) {
  .oe-body { padding: 0 10px 10px; }
  .oe-canvas { border-radius: 10px 0 0 10px; }
  .oe-side { border-radius: 0 10px 10px 0; }
}
</style>
