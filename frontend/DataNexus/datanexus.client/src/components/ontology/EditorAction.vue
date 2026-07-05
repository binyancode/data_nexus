<template>
  <div class="ked">
    <div class="note">
      <el-icon><InfoFilled /></el-icon>
      动作：由 <b>action resolver</b> 执行（ACT 算子），通常依赖某个分析结论。动作的<b>端点/名称</b>在下方「绑定」里 kind=<code>endpoint</code> 指定。
    </div>

    <div class="ef">
      <label>动作标识</label>
      <el-input v-model="action" class="mono" placeholder="如 create_task" />
      <div class="hint">动作的逻辑名（与绑定里的 expr 对应）。</div>
    </div>

    <div class="ef">
      <label>默认描述模板</label>
      <el-input v-model="desc" type="textarea" :rows="2"
                placeholder="如：{n5} 的复盘任务。（{nX} 运行时回填上游结论）" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { attrField } from './attrs'
import type { Concept } from '../../bff/Ontology'

const attrs = defineModel<Record<string, any>>('attrs', { default: () => ({}) })
defineProps<{ concepts: Concept[] }>()
const action = attrField<string>(attrs, 'action')
const desc = attrField<string>(attrs, 'desc')
</script>

<style scoped>
.ked { display: flex; flex-direction: column; gap: 14px; }
.ef label { display: block; font-size: 12px; color: var(--beone-text-secondary); margin-bottom: 4px; }
.hint { font-size: 11px; color: var(--beone-text-secondary); margin-top: 4px; }
.mono :deep(.el-input__inner) { font-family: 'Cascadia Code', Consolas, monospace; }
.note {
  display: block; font-size: 12px;
  color: var(--beone-text-regular); background: var(--beone-bg-midnight-soft);
  border-radius: 8px; padding: 10px 12px; line-height: 1.6;
}
.note :deep(.el-icon) { margin-right: 6px; vertical-align: -0.15em; color: var(--beone-cerulean-blue); }
.note b { color: var(--beone-text-primary); }
.note code { font-family: 'Cascadia Code', Consolas, monospace; color: var(--beone-cerulean-blue); }
</style>
