<template>
  <div class="ked">
    <div class="note">
      <el-icon><InfoFilled /></el-icon>
      派生 / 分析能力：由 <b>Agent（LLM）</b>执行（ASK 算子）。提问时会把上游节点的数值回填进提示词。
    </div>

    <div class="ef">
      <label>默认提示词模板</label>
      <el-input v-model="prompt" type="textarea" :rows="3"
                placeholder="如：对比 {n1} 与 {n2}，分析差异的主要原因并给一句结论。（{nX} 会在运行时回填上游结果）" />
      <div class="hint">用 <code>{nX}</code> 占位引用上游节点结果；留空则由编译器按问题即时生成提示词。</div>
    </div>

    <div class="ef">
      <label>典型输入（可选）</label>
      <el-select v-model="inputs" multiple filterable clearable placeholder="选择常用作输入的指标" style="width: 100%">
        <el-option v-for="m in metrics" :key="m.id" :value="m.id" :label="`${m.name}（${m.id}）`" />
      </el-select>
      <div class="hint">仅作提示/文档，帮助理解这个分析通常消费哪些指标。</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { attrField } from './attrs'
import type { Concept } from '../../bff/Ontology'

const attrs = defineModel<Record<string, any>>('attrs', { default: () => ({}) })
const props = defineProps<{ concepts: Concept[] }>()
const metrics = computed(() => props.concepts.filter((c) => c.kind === 'metric'))
const prompt = attrField<string>(attrs, 'prompt')
const inputs = attrField<string[]>(attrs, 'inputs')
</script>

<style scoped>
.ked { display: flex; flex-direction: column; gap: 14px; }
.ef label { display: block; font-size: 12px; color: var(--beone-text-secondary); margin-bottom: 4px; }
.hint { font-size: 11px; color: var(--beone-text-secondary); margin-top: 4px; }
.hint code { font-family: 'Cascadia Code', Consolas, monospace; color: var(--beone-cerulean-blue); }
.note {
  display: block; font-size: 12px;
  color: var(--beone-text-regular); background: var(--beone-bg-midnight-soft);
  border-radius: 8px; padding: 10px 12px; line-height: 1.6;
}
.note :deep(.el-icon) { margin-right: 6px; vertical-align: -0.15em; color: var(--beone-cerulean-blue); }
.note b { color: var(--beone-text-primary); }
</style>
