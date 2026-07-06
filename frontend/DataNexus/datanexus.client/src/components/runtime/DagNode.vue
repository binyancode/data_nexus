<script setup lang="ts">
import { Handle, Position } from '@vue-flow/core'

defineProps<{
  data: {
    name: string
    badge?: string
    value?: string
    color: string
    selected?: boolean
    fuseTag?: string        // 优化标记（合并执行 / 拆分），高亮显示
  }
}>()
</script>

<template>
  <div class="dnode" :class="{ sel: data.selected, fuse: !!data.fuseTag }" :style="{ '--c': data.color }">
    <Handle type="target" :position="Position.Left" class="dh" />
    <span class="accent"></span>
    <div class="inner">
      <div class="name" :title="data.name">
        <span v-if="data.fuseTag" class="ftag">⚡ {{ data.fuseTag }}</span>{{ data.name }}
      </div>
      <div class="row">
        <span v-if="data.badge" class="badge">{{ data.badge }}</span>
        <span v-if="data.value" class="val" :title="data.value">{{ data.value }}</span>
      </div>
    </div>
    <Handle type="source" :position="Position.Right" class="dh" />
  </div>
</template>

<style scoped>
.dnode {
  width: 178px;
  display: flex;
  align-items: stretch;
  background: #f9fbfe;
  border: 1px solid #dbe5f0;
  border-radius: 12px;
  overflow: hidden;
  box-shadow: 0 2px 6px rgba(16, 24, 40, 0.05), 0 10px 20px rgba(16, 24, 40, 0.08);
  font-family: var(--beone-font-family);
  transition: box-shadow 0.15s, border-color 0.15s;
}
.dnode.sel {
  border-color: var(--c);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--c) 18%, transparent), 0 10px 22px rgba(16, 24, 40, 0.12);
}
.dnode.fuse { border-color: #7c5cff; }
.ftag {
  display: inline-block; margin-right: 5px; vertical-align: 1px;
  font-size: 9px; font-weight: 700; letter-spacing: 0.02em;
  color: #ffffff; background: #7c5cff; border-radius: 4px; padding: 0 5px; line-height: 15px;
}
.accent { width: 4px; flex: 0 0 auto; background: color-mix(in srgb, var(--c) 78%, #ffffff); }
.inner {
  padding: 8px 11px;
  min-width: 0;
  flex: 1;
  background: linear-gradient(180deg, #e9f0f8 0%, #f9fbfe 38%);
}
.name {
  font-size: 12.5px; font-weight: 700; color: #1f2f43;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.row { display: flex; align-items: center; gap: 6px; margin-top: 4px; }
.badge {
  font-size: 9px; color: var(--c); flex: 0 0 auto;
  border: 1px solid color-mix(in srgb, var(--c) 38%, #ffffff);
  background: color-mix(in srgb, var(--c) 12%, #ffffff);
  border-radius: 4px; padding: 0 5px; line-height: 15px; letter-spacing: 0.02em; font-weight: 600;
}
.val {
  font-size: 11px; color: #546b82; font-variant-numeric: tabular-nums;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.dh {
  width: 10px; height: 10px; min-width: 10px; min-height: 10px;
  background: #ffffff; border: 2px solid var(--c);
}
</style>
