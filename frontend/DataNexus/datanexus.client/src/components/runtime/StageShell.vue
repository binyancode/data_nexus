<template>
  <div class="stage-shell" :class="{ open }">
    <button type="button" class="ss-head" @click="open = !open">
      <span class="ss-seq">{{ seq }}</span>
      <span class="ss-titles">
        <span class="ss-title">{{ title }}</span>
        <span class="ss-sub" v-if="subtitle">{{ subtitle }}</span>
      </span>
      <span class="ss-state" :style="{ color: stateColor(state) }">{{ label }}</span>
      <span class="ss-cost" v-if="cost != null">{{ cost }} ms</span>
      <span class="ss-caret">{{ open ? '▾' : '▸' }}</span>
    </button>
    <div v-show="open" class="ss-body"><slot /></div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { stateColor } from './dag'

const props = defineProps<{
  seq: number
  title: string
  subtitle?: string
  state?: string | null
  cost?: number | null
}>()

const open = ref(true)
const label = computed(
  () => ({ pending: '待执行', running: '执行中', done: '完成', failed: '失败' }[props.state ?? 'pending'] ?? props.state ?? ''),
)
</script>

<style scoped>
.stage-shell {
  border: 1px solid var(--tech-border);
  border-radius: 11px;
  background: var(--tech-panel-2);
  overflow: hidden;
  transition: border-color 0.15s;
}
.stage-shell.open { border-color: var(--tech-border-strong); }
.ss-head {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 12px;
  background: none;
  border: 0;
  cursor: pointer;
  font-family: var(--beone-font-family);
}
.ss-seq {
  width: 22px;
  height: 22px;
  border-radius: 7px;
  background: #dce9fb;
  border: 1px solid #bfd5f2;
  color: #1e4a76;
  font-size: 12px;
  font-weight: 700;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 auto;
  box-shadow: none;
}
.ss-titles { display: flex; flex-direction: column; align-items: flex-start; line-height: 1.25; }
.ss-title { font-size: 13px; font-weight: 700; color: var(--tech-text); }
.ss-sub { font-size: 11px; color: var(--tech-dim); }
.ss-state { font-size: 12px; margin-left: 6px; font-weight: 600; }
.ss-cost { margin-left: auto; font-size: 11px; color: var(--tech-dim); font-variant-numeric: tabular-nums; }
.ss-caret { color: var(--tech-dim); font-size: 11px; }
.ss-body {
  padding: 10px 12px 12px;
  font-size: 12px;
  color: var(--tech-dim);
  border-top: 1px solid var(--tech-border);
}
</style>
