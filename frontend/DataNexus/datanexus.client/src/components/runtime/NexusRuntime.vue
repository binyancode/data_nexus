<template>
  <div class="runtime">
    <div class="rt-topline">
      <span class="rt-dot" :style="runtimeDotStyle(runState)"></span>
      <span class="rt-q">{{ detail?.run?.question || question || '—' }}</span>
      <span v-if="ontologyLabel" class="rt-meta" title="本体">📚 {{ ontologyLabel }}</span>
      <span
        v-if="detail?.run?.run_id"
        class="rt-meta rt-runid"
        :title="copied ? '已复制' : ('点击复制 run id：' + detail?.run?.run_id)"
        @click="copyRunId"
      >{{ copied ? '✓ 已复制' : ('#' + shortRunId) }}</span>
      <span class="rt-state">{{ stateLabel(runState) }}</span>
      <span class="rt-cost" v-if="detail?.run?.cost_ms">{{ detail?.run?.cost_ms }} ms</span>
      <span v-if="polling" class="rt-spin" title="实时更新中"></span>
    </div>

    <div v-if="error" class="rt-error">{{ error }}</div>

    <template v-else>
      <!-- 四段流水线：stage —交接物→ stage -->
      <div class="pipeline">
        <template v-for="p in pipeline" :key="p.stage.id">
          <button class="chip" :class="{ active: selected === p.stage.id, running: stOf(p.stage.id) === 'running' }" @click="pick(p.stage.id)">
            <span class="chip-top">
              <span class="chip-name">{{ p.stage.name }}</span>
              <span class="chip-state" :class="`s-${stOf(p.stage.id)}`">{{ stageMark(stOf(p.stage.id)) }}</span>
            </span>
            <span class="chip-meta">{{ metaOf(p.stage.id) }}</span>
          </button>
          <button
            v-if="p.handoff"
            class="ho"
            :class="{ active: selected === p.handoff?.id }"
            @click="pick(p.handoff?.id ?? '')"
          >
            <span class="ho-arrow">➜</span>
            <span class="ho-label">{{ p.handoff?.label }}</span>
          </button>
        </template>
      </div>

      <!-- 详情区（随选中项 / 自动跟随运行阶段） -->
      <div class="detail">
        <StageInitializer v-if="selected === 'initializer'" :stage="stageOf('initializer')" />

        <div v-else-if="selected === 'context'" class="ho-panel">
          <div class="d-title">交接物 · 本体<span>初始化器 → 编译器 · 本次选定的本体</span></div>
          <div v-if="pickedOntology" class="res-list">
            <div class="res-row">
              <span class="res-name">{{ pickedOntology.name || pickedOntology.ontology_id }}</span>
              <span class="res-src">{{ pickedOntology.ontology_id }}</span>
            </div>
          </div>
          <div v-else class="res-empty">尚未选定</div>
        </div>

        <StageCompiler v-else-if="selected === 'compiler'" :stage="stageOf('compiler')" />

        <div v-else-if="selected === 'sqg'" class="ho-panel">
          <div class="d-title">交接物 · 语义查询图（SQG）<span>编译器 → 优化器 · 点击节点看详情</span></div>
          <SqgDag :sqg="sqg" />
        </div>

        <StageOptimizer v-else-if="selected === 'optimizer'" :stage="stageOf('optimizer')" />

        <div v-else-if="selected === 'exec'" class="ho-panel">
          <div class="d-title">交接物 · 执行计划 DAG<span>优化器 → 协调器 · 颜色=状态 · 点击节点看详情</span></div>
          <div v-if="runningNode" class="run-banner">
            <span class="rb-pulse"></span>正在执行：<b>{{ runningNode.node_id }}</b>
            <span v-if="runningNode.resolver">· {{ runningNode.resolver }}</span>
          </div>
          <CoordinatorDag :plan="plan" :node-states="nodeStates" />
        </div>

        <StageCoordinator v-else-if="selected === 'coordinator'" :stage="stageOf('coordinator')" :nodes="detail?.nodes ?? []" />

        <div v-else-if="selected === 'result'" class="ho-panel">
          <div class="d-title">交接物 · 节点结果<span>协调器 → 生成器</span></div>
          <div v-if="resultNodes.length" class="res-list">
            <div v-for="n in resultNodes" :key="n.node_id" class="res-row">
              <span class="res-dot" :style="{ background: stateColor(n.state) }"></span>
              <span class="res-name">{{ n.node_id }}</span>
              <span class="res-val">{{ n.value ?? '—' }}</span>
              <span class="res-src">{{ n.source }}</span>
            </div>
          </div>
          <div v-else class="res-empty">尚无结果</div>
        </div>

        <StageGenerator v-else-if="selected === 'generator'" :stage="stageOf('generator')" />
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { getRun, type RunDetail, type RunNode } from '../../bff/Runs'
import { listOntologies, type OntologyMeta } from '../../bff/Ontology'
import { stateColor, safeParse, type RuntimeAnswer } from './dag'
import StageCompiler from './StageCompiler.vue'
import StageOptimizer from './StageOptimizer.vue'
import StageCoordinator from './StageCoordinator.vue'
import StageGenerator from './StageGenerator.vue'
import StageInitializer from './StageInitializer.vue'
import SqgDag from './SqgDag.vue'
import CoordinatorDag from './CoordinatorDag.vue'

const props = defineProps<{ runId: string | null; question?: string }>()
const emit = defineEmits<{ (e: 'done', answer: RuntimeAnswer): void }>()

const detail = ref<RunDetail | null>(null)
const error = ref('')
const polling = ref(false)
const selected = ref<string>('initializer')
const autoFollow = ref(true)
let timer: ReturnType<typeof setTimeout> | null = null
let tries = 0
let emitted = false

// 本体 id → 名称映射（用于在标题栏显示选中的本体名，取不到则回退 id）
const ontoNames = ref<Record<string, string>>({})
listOntologies()
  .then((list: OntologyMeta[]) => {
    ontoNames.value = Object.fromEntries(list.map((o) => [o.ontologyId, o.name]))
  })
  .catch(() => {})
const ontologyLabel = computed(() => {
  const id = detail.value?.run?.ontology_id
  if (!id) return ''
  return ontoNames.value[id] || id
})

// 初始化器交接物「本体」：本次选定的本体（读初始化器段 output）
const pickedOntology = computed(() =>
  safeParse<{ ontology_id: string; name?: string }>(stageOf('initializer')?.output),
)

// run id：太长 → 显示短前缀，点击复制完整 id，hover 看全量
const shortRunId = computed(() => (detail.value?.run?.run_id || '').slice(0, 8))
const copied = ref(false)
async function copyRunId() {
  const id = detail.value?.run?.run_id
  if (!id) return
  try {
    await navigator.clipboard.writeText(id)
  } catch {
    /* 剪贴板不可用时静默忽略 */
  }
  copied.value = true
  setTimeout(() => (copied.value = false), 1200)
}

const segments = [
  { id: 'initializer', name: '初始化器' },
  { id: 'compiler', name: '编译器' },
  { id: 'optimizer', name: '优化器' },
  { id: 'coordinator', name: '协调器' },
  { id: 'generator', name: '生成器' },
]
const handoffs: ({ id: string; label: string } | null)[] = [
  { id: 'context', label: '本体' },
  { id: 'sqg', label: 'SQG' },
  { id: 'exec', label: '执行计划' },
  { id: 'result', label: '结果' },
  null,
]
const pipeline = segments.map((stage, i) => ({ stage, handoff: handoffs[i] }))

const runState = computed(() => detail.value?.run?.state ?? 'pending')
function stateLabel(s?: string | null) {
  return { pending: '待执行', running: '执行中', done: '完成', failed: '失败' }[s ?? 'pending'] ?? s ?? ''
}
function stageOf(name: string) {
  return detail.value?.stages?.find((s) => s.stage === name) ?? null
}function stOf(name: string) {
  return stageOf(name)?.state ?? 'pending'
}
function metaOf(name: string) {
  const st = stageOf(name)
  if (!st || st.state === 'pending') return '待执行'
  if (st.state === 'running') return '执行中…'
  return st.cost_ms != null ? st.cost_ms + ' ms' : stateLabel(st.state)
}

function stageMark(state?: string | null) {
  const s = state ?? 'pending'
  if (s === 'done') return '✓'
  if (s === 'running') return '⋯'
  if (s === 'failed') return '×'
  return '○'
}

function runtimeDotStyle(state?: string | null) {
  const s = state ?? 'pending'
  const c = stateColor(s)
  const halo = {
    done: 'rgba(79, 159, 137, 0.22)',
    running: 'rgba(90, 149, 187, 0.22)',
    pending: 'rgba(157, 170, 186, 0.2)',
    failed: 'rgba(198, 120, 120, 0.22)',
  }[s] ?? 'rgba(157, 170, 186, 0.2)'
  return {
    background: '#f8fbff',
    borderColor: c,
    boxShadow: `0 0 0 2px ${halo}`,
  }
}

const sqg = computed(() => safeParse(stageOf('compiler')?.output ?? null))
const plan = computed(() => safeParse(stageOf('optimizer')?.output ?? null))
const nodeStates = computed<Record<string, RunNode>>(() => {
  const m: Record<string, RunNode> = {}
  for (const n of detail.value?.nodes ?? []) m[n.node_id] = n
  return m
})
const resultNodes = computed(() => detail.value?.nodes ?? [])
const runningNode = computed(() => (detail.value?.nodes ?? []).find((n) => n.state === 'running') ?? null)

// 自动跟随当前正在执行的阶段（无正在运行时停在最靠后的已开始阶段，避免闪回）
const autoTarget = computed(() => {
  const rs = runState.value
  if (rs === 'done' || rs === 'failed') return 'generator'
  const order = ['compiler', 'optimizer', 'coordinator', 'generator']
  let running: string | null = null
  let lastStarted: string | null = null
  for (const s of order) {
    const st = stOf(s)
    if (st === 'running') running = s
    if (st === 'running' || st === 'done') lastStarted = s
  }
  const cur = running ?? lastStarted ?? 'compiler'
  return cur === 'coordinator' ? 'exec' : cur
})

function pick(id: string) {
  selected.value = id
  autoFollow.value = false // 用户手动选择后停止自动跟随
}

watch(runState, (s) => {
  if ((s === 'done' || s === 'failed') && !emitted) {
    emitted = true
    const ans = safeParse<{ text?: string; lineage?: RuntimeAnswer['lineage'] }>(detail.value?.run?.answer ?? null)
    if (ans) emit('done', { text: ans.text ?? '', lineage: ans.lineage ?? [] })
  }
})

async function load(poll = false) {
  const id = props.runId
  if (!id) return
  polling.value = true
  try {
    detail.value = await getRun(id)
    error.value = ''
    tries = 0
    if (autoFollow.value) selected.value = autoTarget.value  // 自动跟随当前执行阶段
    if (detail.value?.run?.state === 'running') {
      timer = setTimeout(() => load(true), 800)
    } else {
      polling.value = false
    }
  } catch (e: any) {
    // run 行可能尚未写入（异步刚启动）→ 短暂重试
    if (tries++ < 12) {
      timer = setTimeout(() => load(true), 500)
    } else {
      error.value = '加载运行记录失败：' + (e?.message || e)
      polling.value = false
    }
  }
}

function reset() {
  if (timer) { clearTimeout(timer); timer = null }
  detail.value = null
  error.value = ''
  polling.value = false
  selected.value = 'compiler'
  autoFollow.value = true
  tries = 0
  emitted = false
}

watch(() => props.runId, () => { reset(); if (props.runId) load() }, { immediate: true })
onUnmounted(() => { if (timer) clearTimeout(timer) })
</script>

<style scoped>
.runtime {
  display: flex; flex-direction: column; gap: 14px;
  position: relative;
  width: min(100%, 980px);
  background: transparent;
  border: 0;
  border-radius: 0;
  padding: 0;
  box-shadow: none;
  --tech-panel: #ffffff;
  --tech-panel-2: #f8fbff;
  --tech-border: #d7e1ee;
  --tech-border-strong: #96c7d2;
  --tech-text: #12324d;
  --tech-dim: #6c8298;
  --tech-cyan: #27a8b1;
  --tech-cyan-dim: #4da7af;
  --tech-green: #34b67a;
  --tech-amber: #d08a2f;
  --tech-glow: rgba(39, 168, 177, 0.28);
}
.runtime::before {
  content: none;
}
.runtime > * { position: relative; z-index: 1; }
.rt-topline {
  display: flex; align-items: center; gap: 10px;
  padding: 10px 14px; background: var(--tech-panel);
  border: 1px solid var(--tech-border); border-radius: 11px;
}
.rt-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex: 0 0 auto;
  border: 1.5px solid #a9b9cc;
  box-shadow: none;
}
.rt-q { font-weight: 600; color: var(--tech-text); flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; letter-spacing: 0.02em; }
.rt-state, .rt-cost { font-size: 12px; color: var(--tech-dim); font-variant-numeric: tabular-nums; }
.rt-meta {
  flex: 0 0 auto; font-size: 11.5px; color: var(--tech-dim);
  background: transparent; border: 1px solid var(--tech-border);
  border-radius: 6px; padding: 2px 8px; max-width: 220px;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.rt-runid {
  font-variant-numeric: tabular-nums;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  cursor: pointer; transition: color 0.15s, border-color 0.15s;
}
.rt-runid:hover { color: var(--tech-text); border-color: var(--tech-cyan); }
.rt-spin {
  width: 14px; height: 14px; border-radius: 50%;
  border: 2px solid rgba(120, 200, 230, 0.2); border-top-color: var(--tech-cyan);
  animation: spin 0.8s linear infinite; box-shadow: 0 0 8px var(--tech-glow);
}
@keyframes spin { to { transform: rotate(360deg); } }
.rt-error { padding: 12px; color: #9b2f2f; background: #fff2f2; border: 1px solid #f1c8c8; border-radius: 8px; }

/* pipeline */
.pipeline {
  display: flex; align-items: stretch; gap: 4px; flex-wrap: wrap;
  padding: 9px; background: var(--tech-panel);
  border: 1px solid var(--tech-border); border-radius: 11px;
}
.chip {
  display: flex; flex-direction: column; align-items: flex-start; gap: 4px;
  min-width: 108px; padding: 8px 12px; border-radius: 9px;
  border: 1.5px solid var(--tech-border); background: #ffffff;
  cursor: pointer; font-family: var(--beone-font-family); transition: all 0.15s;
}
.chip:hover { border-color: var(--tech-border-strong); background: #f0f9fb; }
.chip.active {
  border-color: var(--tech-cyan);
  background: #d9f3f4;
  box-shadow: 0 0 0 1px var(--tech-cyan), 0 0 12px var(--tech-glow);
}
.chip.running { border-color: var(--tech-cyan); animation: chippulse 1.3s ease-in-out infinite; }
@keyframes chippulse { 0%, 100% { box-shadow: 0 0 0 0 rgba(76, 201, 240, 0); } 50% { box-shadow: 0 0 16px 1px var(--tech-glow); } }
.chip-top { width: 100%; display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.chip-name { font-size: 13px; font-weight: 700; color: var(--tech-text); }
.chip-state {
  width: 18px;
  height: 18px;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: 700;
  line-height: 1;
  border: 1px solid #c7d3e1;
  color: #7a8da3;
  background: #f5f8fc;
}
.chip-state.s-done { color: #2f8f74; border-color: #9fcdbd; background: #ecf7f2; }
.chip-state.s-running { color: #2f86b3; border-color: #a7c8df; background: #ecf5fb; }
.chip-state.s-failed { color: #b15f5f; border-color: #debbbb; background: #fbf0f0; }
.chip-meta { font-size: 11px; color: var(--tech-dim); font-variant-numeric: tabular-nums; }

.ho {
  display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 2px;
  padding: 4px 6px; border: 0; background: none; cursor: pointer;
  color: var(--tech-dim); font-family: var(--beone-font-family);
}
.ho-arrow { font-size: 15px; color: var(--tech-cyan-dim); }
.ho-label {
  font-size: 10px; padding: 2px 8px; border-radius: 9px;
  background: #f1f6fb; color: var(--tech-dim);
  border: 1px solid transparent; letter-spacing: 0.02em; white-space: nowrap;
}
.ho.active .ho-label { background: #def3f4; border-color: var(--tech-cyan); color: var(--tech-cyan); }

/* detail */
.detail {
  background: var(--tech-panel);
  border: 1px solid var(--tech-border);
  border-radius: 11px;
  padding: 12px;
}
.d-title { font-size: 13px; font-weight: 600; color: #eaf3fa; margin-bottom: 12px; display: flex; align-items: baseline; gap: 8px; }
.d-title { color: var(--tech-text); }
.d-title span { font-size: 11px; font-weight: 400; color: var(--tech-dim); }
.run-banner {
  display: flex; align-items: center; gap: 8px; margin-bottom: 12px;
  font-size: 12px; color: var(--tech-cyan);
  background: #e6f6f6; border: 1px solid #bfe5e7;
  padding: 6px 10px; border-radius: 7px;
}
.run-banner b { color: var(--tech-text); }
.rb-pulse { width: 9px; height: 9px; border-radius: 50%; background: var(--tech-cyan); box-shadow: 0 0 10px var(--tech-cyan); animation: chippulse 1s infinite; }
.res-list { display: flex; flex-direction: column; gap: 6px; }
.res-row { display: flex; align-items: center; gap: 10px; padding: 8px 11px; background: var(--tech-panel-2); border: 1px solid var(--tech-border); border-radius: 7px; font-size: 12px; }
.res-dot { width: 9px; height: 9px; border-radius: 50%; box-shadow: 0 0 6px currentColor; }
.res-name { min-width: 36px; color: var(--tech-text); font-weight: 600; }
.res-val { font-weight: 700; color: var(--tech-text); }
.res-src { margin-left: auto; font-size: 11px; color: var(--tech-cyan-dim); }
.res-empty { color: var(--tech-dim); font-size: 13px; padding: 12px; }
</style>
