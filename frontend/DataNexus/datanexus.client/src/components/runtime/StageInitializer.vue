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
        <div class="col-h">输出 · 选中本体（{{ picked.length }}）
          <span v-if="reused" class="reuse" :title="reuseText">♻ 本体复用</span>
        </div>
        <div v-if="picked.length" class="strip">
          <button v-if="picked.length > 3" class="pg" title="左" @click="scroll(selTrack, -1)">‹</button>
          <div ref="selTrack" class="track">
            <div v-for="p in picked" :key="p.ontology_id" class="node">
              <span class="op" :class="mode === 'explicit' ? 'm-exp' : 'm-auto'">
                {{ mode === 'explicit' ? '显式指定' : 'LLM 路由' }}
              </span>
              <span class="nm">{{ p.name || p.ontology_id }}</span>
              <span class="cc">{{ p.ontology_id }}</span>
            </div>
          </div>
          <button v-if="picked.length > 3" class="pg" title="右" @click="scroll(selTrack, 1)">›</button>
        </div>
        <div v-else class="muted">尚未选择</div>

        <div class="col-h" v-if="candidates.length" style="margin-top: 8px">候选本体（{{ candidates.length }}）</div>
        <div v-if="candidates.length" class="strip">
          <button v-if="candidates.length > 6" class="pg" title="左" @click="scroll(candTrack, -1)">‹</button>
          <div ref="candTrack" class="track">
            <span v-for="c in candidates" :key="c" class="cand" :class="{ hit: pickedIds.includes(c) }">{{ c }}</span>
          </div>
          <button v-if="candidates.length > 6" class="pg" title="右" @click="scroll(candTrack, 1)">›</button>
        </div>
      </div>
    </div>
    <div v-if="stage?.error" class="err">{{ stage.error }}</div>
  </StageShell>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import StageShell from './StageShell.vue'
import { safeParse } from './dag'
import type { RunStage } from '../../bff/Runs'

const props = defineProps<{ stage: RunStage | null }>()

const selTrack = ref<HTMLElement | null>(null)
const candTrack = ref<HTMLElement | null>(null)
function scroll(el: HTMLElement | null, dir: number) {
  el?.scrollBy({ left: dir * 220, behavior: 'smooth' })
}

const input = computed(() => safeParse<{ question?: string; requested_ontology_id?: string | null }>(props.stage?.input))
const question = computed(() => input.value?.question)
const requested = computed(() => input.value?.requested_ontology_id || '')

const output = computed(() =>
  safeParse<{ ontology_ids?: string[]; names?: string[]; selection?: { mode?: string; candidates?: string[]; reused?: boolean; cache_age_s?: number } }>(props.stage?.output),
)
const picked = computed(() => {
  const ids = output.value?.ontology_ids ?? []
  const names = output.value?.names ?? []
  return ids.map((id, i) => ({ ontology_id: id, name: names[i] || id }))
})
const pickedIds = computed(() => picked.value.map((p) => p.ontology_id))
const mode = computed(() => output.value?.selection?.mode || 'auto')
const candidates = computed(() => output.value?.selection?.candidates ?? [])
const reused = computed(() => output.value?.selection?.reused === true)
const reuseText = computed(() => {
  const s = output.value?.selection?.cache_age_s ?? 0
  const m = Math.floor(s / 60)
  return m >= 1 ? `命中路由缓存：复用 ${m} 分钟前的本体选择` : `命中路由缓存：复用 ${s} 秒前的本体选择`
})
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
.node { display: flex; align-items: center; gap: 8px; padding: 8px 10px; background: var(--tech-panel-2); border: 1px solid var(--tech-border); border-radius: 8px; flex: 0 0 auto; max-width: 300px; }
.op { color: #fff; font-size: 10px; padding: 2px 7px; border-radius: 4px; font-weight: 600; letter-spacing: 0.02em; flex: 0 0 auto; }
.op.m-exp { background: #3a8f5f; }
.op.m-auto { background: #6a5cff; }
.nm { font-size: 13px; font-weight: 600; color: var(--tech-text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.cc { margin-left: auto; font-size: 11px; color: var(--tech-cyan-dim); font-family: 'Cascadia Code', Consolas, monospace; flex: 0 0 auto; }
/* 横向翻页条：多本体时溢出可滚动，左右小箭头翻页 */
.strip { display: flex; align-items: center; gap: 4px; }
.track { display: flex; gap: 6px; overflow-x: auto; flex: 1 1 auto; min-width: 0; scroll-behavior: smooth; padding-bottom: 3px; }
.track::-webkit-scrollbar { height: 5px; }
.track::-webkit-scrollbar-thumb { background: var(--tech-border); border-radius: 3px; }
.pg { flex: 0 0 auto; width: 20px; height: 26px; border: 1px solid var(--tech-border); background: var(--tech-panel-2); color: var(--tech-dim); border-radius: 6px; cursor: pointer; font-size: 14px; line-height: 1; padding: 0; transition: color .15s, border-color .15s; }
.pg:hover { color: var(--tech-text); border-color: var(--tech-cyan); }
.cand { flex: 0 0 auto; font-size: 11px; color: var(--tech-dim); border: 1px solid var(--tech-border); border-radius: 6px; padding: 1px 7px; font-family: 'Cascadia Code', Consolas, monospace; white-space: nowrap; }
.cand.hit { color: var(--tech-text); border-color: var(--tech-cyan); }
.muted { color: var(--tech-dim); }
.reuse { margin-left: 8px; font-size: 10px; font-weight: 600; color: #0b7f8c; border: 1px solid #7fd6df; background: #e6f9fb; border-radius: 5px; padding: 1px 6px; cursor: help; }
.err { margin-top: 8px; color: #ffd5d0; white-space: pre-wrap; font-size: 12px; }
</style>
