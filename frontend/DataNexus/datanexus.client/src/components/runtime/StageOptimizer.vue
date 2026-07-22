<template>
  <StageShell :seq="3" title="优化器" subtitle="语义绑定 → 逻辑计划 IR → 物理执行计划 PEP" :state="stage?.state" :cost="stage?.cost_ms ?? null" :logs="stage?.logs">
    <el-tabs v-model="tab" class="artifacts">
      <el-tab-pane label="语义绑定" name="binding">
        <div v-if="binding?.tasks?.length" class="cards">
          <div v-for="task in binding.tasks" :key="task.logical_node" class="card">
            <b>{{ task.logical_node }}</b>
            <span>{{ task.entities?.map((e:any) => e.concept).join(' → ') || '无结构化绑定' }}</span>
            <small>源：{{ task.source_instances?.join('、') || '—' }}</small>
            <small v-if="task.relations?.length">关系：{{ task.relations.map((r:any) => r.concept).join('、') }}</small>
          </div>
        </div>
        <div v-else class="muted">尚无语义绑定产物</div>
      </el-tab-pane>
      <el-tab-pane label="逻辑计划（IR）" name="logical">
        <div class="help">IR = Intermediate Representation（中间表示）：已解析业务概念和关系，但尚未决定执行位置与 SQL 方言。</div>
        <div v-if="logical?.nodes?.length" class="tree">
          <div v-for="node in logical.nodes" :key="node.id" class="op-row">
            <span class="op">{{ node.kind }}</span><b>{{ node.name || node.id }}</b>
            <span class="origin">{{ node.origin_sqg_nodes?.join(', ') }}</span>
            <small v-if="node.grain?.length">grain: {{ node.grain.join(', ') }}</small>
          </div>
        </div>
        <div v-else class="muted">尚无 Bound Logical Plan</div>
      </el-tab-pane>
      <el-tab-pane label="物理计划（PEP）" name="physical">
        <div class="summary"><span>{{ pepNodes.length }} Fragment</span><span>{{ maxWave }} 波</span><span>{{ fusedCount }} 个融合 Fragment</span></div>
        <div class="cards">
          <div v-for="node in pepNodes" :key="node.id" class="card">
            <div class="card-head"><span class="wave">W{{ node.wave }}</span><b>{{ node.name || node.id }}</b><span class="op">{{ node.kind }}</span></div>
            <small>{{ node.source_instance || node.engine || node.resolver || '—' }}</small>
            <div v-if="node.realizes?.length" class="realizes">实现：{{ node.realizes.map((r:any) => r.logical_node).join('、') }}</div>
            <pre v-if="node.call?.sql">{{ node.call.sql }}</pre>
          </div>
        </div>
      </el-tab-pane>
      <el-tab-pane label="优化过程" name="trace">
        <div v-if="trace?.rules?.length" class="rules">
          <div v-for="(rule, index) in trace.rules" :key="index" class="rule" :class="rule.outcome">
            <span>{{ rule.outcome === 'applied' ? '✓' : '—' }}</span>
            <b>{{ rule.rule }}</b><p>{{ rule.reason }}</p>
            <small>{{ rule.logical_nodes?.join(', ') }}</small>
          </div>
        </div>
        <div v-else class="muted">尚无优化规则记录</div>
      </el-tab-pane>
    </el-tabs>
    <details v-if="activeArtifact"><summary>查看原始 JSON</summary><pre class="json">{{ pretty(activeArtifact) }}</pre></details>
    <div v-if="stage?.error" class="err">{{ stage.error }}</div>
  </StageShell>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import StageShell from './StageShell.vue'
import { safeParse } from './dag'
import type { RunStage } from '../../bff/Runs'

const props = defineProps<{ stage: RunStage | null }>()
const tab = ref('binding')
const logs = computed(() => safeParse<any>(props.stage?.logs))
const artifacts = computed(() => logs.value?.artifacts || {})
const binding = computed(() => artifacts.value.semantic_binding)
const logical = computed(() => artifacts.value.bound_logical_plan)
const pep = computed(() => artifacts.value.physical_execution_plan || safeParse<any>(props.stage?.output))
const trace = computed(() => artifacts.value.optimization_trace)
const pepNodes = computed<any[]>(() => pep.value?.nodes || [])
const maxWave = computed(() => pep.value?.context?.max_wave || Math.max(0, ...pepNodes.value.map((n:any) => n.wave || 0)))
const fusedCount = computed(() => pepNodes.value.filter((n:any) => (n.realizes?.length || 0) > 1).length)
const activeArtifact = computed(() => ({ binding: binding.value, logical: logical.value, physical: pep.value, trace: trace.value } as any)[tab.value])
function pretty(value: unknown) { return JSON.stringify(value, null, 2) }
</script>

<style scoped>
.artifacts { margin-top:-4px; }.cards,.tree,.rules { display:flex; flex-direction:column; gap:7px; }.card,.op-row,.rule { border:1px solid #dbe5f2; border-radius:8px; background:#f8fbff; padding:9px 11px; display:flex; flex-direction:column; gap:4px; color:#35516c; }
.card-head,.summary { display:flex; align-items:center; gap:8px; }.summary { margin-bottom:8px; flex-wrap:wrap; }.summary span { padding:3px 8px; border:1px solid #d7e1ee; border-radius:12px; font-size:11px; color:#647b91; }
.op,.wave { display:inline-flex; width:max-content; padding:2px 6px; border-radius:4px; background:#e5f3f5; color:#16717c; font-size:10px; }.origin { margin-left:auto; color:#8c9eb0; font-size:10px; }.op-row { display:grid; grid-template-columns:90px 1fr auto; align-items:center; }.op-row small { grid-column:2/4; }
.realizes { font-size:11px; color:#7658c8; }.card pre,.json { white-space:pre-wrap; overflow:auto; max-height:220px; background:#eef3f8; border-radius:6px; padding:7px; font:10px/1.45 'Cascadia Code',Consolas,monospace; }
.help { font-size:11px; color:#60788f; background:#eef8fa; border-left:3px solid #27a8b1; padding:8px 10px; margin-bottom:8px; }.rule { display:grid; grid-template-columns:20px 190px 1fr auto; align-items:center; }.rule p { margin:0; font-size:11px; }.rule.rejected { border-color:#ead3a7; background:#fffaf1; }
details { margin-top:10px; } summary { cursor:pointer; color:#61798f; font-size:11px; }.muted { color:#8b9bad; font-size:12px; }.err { margin-top:8px; color:#b94444; white-space:pre-wrap; }
</style>
