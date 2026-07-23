<template>
  <div class="ent-node" :class="{ sel: data.selected, fact: data.isFact }">
    <Handle type="target" :position="Position.Left" />
    <Handle type="source" :position="Position.Right" />

    <div class="en-head">
      <span class="en-dot"></span>
      <div class="en-title">
        <span class="en-name">{{ data.name }}</span>
        <span v-if="data.table" class="en-table">{{ data.table }}</span>
      </div>
      <button v-if="data.canPreview" type="button" class="en-preview nodrag nopan"
              title="预览样例数据" aria-label="预览样例数据"
              @pointerdown.stop @click.stop="data.onPreview?.()">
        <el-icon><View /></el-icon>
      </button>
      <span class="en-kind">{{ data.isFact ? '事实' : '维度' }}</span>
    </div>
    <div class="en-body">
      <div class="en-subhead">字段</div>
      <div v-for="a in data.attributes" :key="a.id" class="en-attr">
        <span class="ea-name" :class="{ pk: a.isKey }">{{ a.name }}</span>
        <span v-if="a.isKey" class="ea-tag key">PK</span>
        <span v-else-if="!a.role" class="ea-tag measure">度量</span>
        <span v-else class="ea-tag dim">维度</span>
      </div>
      <div v-if="!data.attributes.length" class="en-empty">（无字段）</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { Handle, Position } from '@vue-flow/core'
import { View } from '@element-plus/icons-vue'

defineProps<{
  data: {
    name: string
    table?: string | null
    selected?: boolean
    isFact?: boolean
    canPreview?: boolean
    onPreview?: () => void
    attributes: { id: string; name: string; role?: string | null; isKey?: boolean }[]
  }
}>()
</script>

<style scoped>
.ent-node {
  width: 246px;
  background: #f9fbfe;
  border: 1px solid #dde6f0;
  border-radius: 14px;
  box-shadow: 0 2px 6px rgba(16, 24, 40, 0.05), 0 12px 22px rgba(16, 24, 40, 0.08);
  overflow: hidden;
  font-family: var(--beone-font-family);
  transition: box-shadow 0.15s, border-color 0.15s;
  --node-accent: #5b7fa6;
}
.ent-node.fact { --node-accent: #2f8f83; }
.ent-node:hover { box-shadow: 0 4px 10px rgba(16, 24, 40, 0.07), 0 14px 26px rgba(16, 24, 40, 0.12); }
.ent-node.sel {
  border-color: var(--node-accent);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--node-accent) 18%, transparent), 0 10px 22px rgba(16, 24, 40, 0.12);
}

.en-head {
  display: flex; align-items: center; gap: 8px;
  padding: 10px 12px;
  background: #dfe8f3;
  border-bottom: 1px solid #c9d6e4;
}
.en-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--node-accent); flex: 0 0 auto; }
.en-title { flex: 1; min-width: 0; }
.en-name { display: block; font-size: 14px; font-weight: 700; color: #1f2a3d; line-height: 1.25; }
.en-table { display: block; font-size: 10.5px; color: #7f91a6; font-family: 'Cascadia Code', Consolas, monospace; }
.en-kind {
  flex: 0 0 auto; font-size: 10px; color: var(--node-accent);
  background: color-mix(in srgb, var(--node-accent) 15%, #fff);
  border-radius: 999px;
  padding: 2px 8px;
  font-weight: 600;
}
.en-preview {
  width:24px; height:24px; display:inline-flex; align-items:center; justify-content:center;
  flex:0 0 auto; padding:0; border:1px solid transparent; border-radius:6px;
  background:transparent; color:#698097; cursor:pointer;
  transition:color .14s, background .14s, border-color .14s;
}
.en-preview:hover { color:#176f87; background:#f4fbfd; border-color:#a9ccd7; }
.en-preview .el-icon { font-size:15px; }

.en-body { padding: 3px 0; max-height: 260px; overflow-y: auto; }
.en-body {
  background: #ffffff;
}
.en-subhead {
  height: 24px;
  display: flex;
  align-items: center;
  padding: 0 12px;
  font-size: 10.5px;
  font-weight: 700;
  color: #74879c;
  letter-spacing: 0.6px;
  border-bottom: 1px solid #e4ecf5;
  background: #f4f8fc;
}
.en-attr {
  display: flex; align-items: center; gap: 8px; padding: 5px 12px;
  font-size: 12px; color: #4a5568;
  border-bottom: 1px solid #edf2f7;
}
.en-attr:nth-child(even) { background: #f6f9fd; }
.ea-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ea-name.pk { font-weight: 600; color: #2d3748; }
.ea-tag { font-size: 9.5px; border-radius: 4px; padding: 1px 6px; line-height: 15px; font-weight: 500; letter-spacing: .2px; }
.ea-tag.key { background: #fdf3e3; color: #b7791f; }
.ea-tag.measure { background: #e7f4f1; color: #0f766e; }
.ea-tag.dim { background: #eef1f5; color: #6b7889; }
.en-empty { padding: 8px 12px; font-size: 12px; color: #9aa6b4; }

.en-body::-webkit-scrollbar { width: 6px; }
.en-body::-webkit-scrollbar-thumb { background: #e2e8f0; border-radius: 3px; }
:deep(.vue-flow__handle) {
  width: 10px; height: 10px; background: #fff; border: 2px solid var(--node-accent);
}
</style>
