<template>
  <StageShell :seq="1" title="初始化器" subtitle="选定本体（显式指定 or LLM 路由）· 准备编译上下文" :state="stage?.state" :cost="stage?.cost_ms ?? null">
    <div class="flow">
      <div class="col in-col">
        <div class="col-h">输入 · 问题</div>
        <div class="q-box">{{ question || '—' }}</div>
        <div class="hint" v-if="requested">已指定：{{ requested }}</div>
      </div>
      <div class="col-arrow">➜</div>
      <div class="col grow">
        <div class="col-h">输出 · 选中本体</div>
        <div v-if="picked" class="node">
          <span class="op" :class="mode === 'explicit' ? 'm-exp' : 'm-auto'">
            {{ mode === 'explicit' ? '显式指定' : 'LLM 路由' }}
          </span>
          <span class="nm">{{ picked.name || picked.ontology_id }}</span>
          <span class="cc">{{ picked.ontology_id }}</span>
        </div>
        <div v-else class="muted">尚未选择</div>

        <div class="col-h" v-if="candidates.length" style="margin-top: 8px">候选本体（{{ candidates.length }}）</div>
        <div v-if="candidates.length" class="cands">
          <span v-for="c in candidates" :key="c" class="cand" :class="{ hit: picked && c === picked.ontology_id }">{{ c }}</span>
        </div>
      </div>
    </div>
    <div v-if="stage?.error" class="err">{{ stage.error }}</div>
  </StageShell>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import StageShell from './StageShell.vue'
import { safeParse } from './dag'
import type { RunStage } from '../../bff/Runs'

const props = defineProps<{ stage: RunStage | null }>()

const input = computed(() => safeParse<{ question?: string; requested_ontology_id?: string | null }>(props.stage?.input))
const question = computed(() => input.value?.question)
const requested = computed(() => input.value?.requested_ontology_id || '')

const output = computed(() =>
  safeParse<{ ontology_id: string; name?: string; selection?: { mode?: string; candidates?: string[] } }>(props.stage?.output),
)
const picked = computed(() => (output.value?.ontology_id ? output.value : null))
const mode = computed(() => output.value?.selection?.mode || 'auto')
const candidates = computed(() => output.value?.selection?.candidates ?? [])
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
.node { display: flex; align-items: center; gap: 8px; padding: 8px 10px; background: var(--tech-panel-2); border: 1px solid var(--tech-border); border-radius: 8px; }
.op { color: #fff; font-size: 10px; padding: 2px 7px; border-radius: 4px; font-weight: 600; letter-spacing: 0.02em; }
.op.m-exp { background: #3a8f5f; }
.op.m-auto { background: #6a5cff; }
.nm { font-size: 13px; font-weight: 600; color: var(--tech-text); }
.cc { margin-left: auto; font-size: 11px; color: var(--tech-cyan-dim); font-family: 'Cascadia Code', Consolas, monospace; }
.cands { display: flex; flex-wrap: wrap; gap: 6px; }
.cand { font-size: 11px; color: var(--tech-dim); border: 1px solid var(--tech-border); border-radius: 6px; padding: 1px 7px; font-family: 'Cascadia Code', Consolas, monospace; }
.cand.hit { color: var(--tech-text); border-color: var(--tech-cyan); }
.muted { color: var(--tech-dim); }
.err { margin-top: 8px; color: #ffd5d0; white-space: pre-wrap; font-size: 12px; }
</style>
