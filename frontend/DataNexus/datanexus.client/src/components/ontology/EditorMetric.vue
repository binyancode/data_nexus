<template>
  <div class="metric-editor">
    <div class="note">指标保存为强类型表达式，不保存或解析 SQL 字符串。物理列和 JOIN 由本体绑定与关系自动解析。</div>
    <div class="grid">
      <label>统计函数
        <el-select v-model="fn">
          <el-option v-for="value in functions" :key="value" :value="value" :label="value" />
        </el-select>
      </label>
      <label>结果类型
        <el-select v-model="resultType"><el-option value="decimal" label="decimal" /><el-option value="integer" label="integer" /></el-select>
      </label>
      <label>单位<el-input v-model="unit" placeholder="CNY / % / 件" /></label>
    </div>

    <div v-if="fn === 'PERCENTILE'" class="grid">
      <label>百分位<el-input-number v-model="percentile" :min="0" :max="1" :step="0.05" /></label>
      <label>方法<el-select v-model="method"><el-option value="CONTINUOUS" label="连续" /><el-option value="DISCRETE" label="离散" /></el-select></label>
      <label>精度<el-select v-model="accuracy"><el-option value="EXACT" label="精确" /><el-option value="APPROXIMATE" label="近似" /></el-select></label>
    </div>

    <div class="expression">
      <div class="expr-head"><b>被统计表达式</b><el-button size="small" @click="addTerm">＋ 添加项</el-button></div>
      <div v-if="terms.length" class="terms">
        <div v-for="(term, index) in terms" :key="index" class="term">
          <el-select v-if="index > 0" v-model="term.operator" class="operator">
            <el-option value="ADD" label="＋" /><el-option value="SUBTRACT" label="－" />
            <el-option value="MULTIPLY" label="×" /><el-option value="DIVIDE" label="÷" />
          </el-select>
          <span v-else class="first">起始</span>
          <el-select v-model="term.attribute" filterable class="attribute" placeholder="选择属性">
            <el-option-group v-for="group in attrGroups" :key="group.entity" :label="group.name">
              <el-option v-for="attribute in group.attributes" :key="attribute.id" :value="attribute.id" :label="attribute.name" />
            </el-option-group>
          </el-select>
          <el-button text type="danger" @click="terms.splice(index, 1)">删除</el-button>
        </div>
      </div>
      <div v-else class="empty">COUNT(*) 可以留空；其它统计函数请选择至少一个属性。</div>
    </div>

    <div class="preview">
      <span>Typed Expression</span>
      <pre>{{ JSON.stringify(expression, null, 2) }}</pre>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { Concept } from '../../bff/Ontology'

const attrs = defineModel<Record<string, any>>('attrs', { default: () => ({}) })
const props = defineProps<{ concepts: Concept[] }>()
type Term = { operator: 'ADD' | 'SUBTRACT' | 'MULTIPLY' | 'DIVIDE'; attribute: string }

const functions = ['SUM', 'COUNT', 'COUNT_DISTINCT', 'AVG', 'MIN', 'MAX', 'MEDIAN', 'PERCENTILE', 'VARIANCE', 'STDDEV']
const fn = ref('SUM'), resultType = ref('decimal'), unit = ref(''), percentile = ref(0.5)
const method = ref<'CONTINUOUS' | 'DISCRETE'>('CONTINUOUS')
const accuracy = ref<'EXACT' | 'APPROXIMATE'>('EXACT')
const terms = ref<Term[]>([])
let loading = false

const attributes = computed(() => props.concepts.filter((concept) => concept.kind === 'attribute'))
function entityOf(concept: Concept) { try { return JSON.parse(concept.attrs || '{}').entity || '' } catch { return '' } }
const attrGroups = computed(() => {
  const groups = new Map<string, { entity: string; name: string; attributes: Concept[] }>()
  for (const attribute of attributes.value) {
    const entity = entityOf(attribute)
    if (!groups.has(entity)) groups.set(entity, { entity, name: props.concepts.find((c) => c.id === entity)?.name || entity, attributes: [] })
    groups.get(entity)!.attributes.push(attribute)
  }
  return [...groups.values()]
})

function valueExpression() {
  if (!terms.value.length) return null
  let value: any = { kind: 'attribute', concept: terms.value[0]!.attribute }
  for (const term of terms.value.slice(1)) {
    value = { kind: 'binary', operator: term.operator, left: value, right: { kind: 'attribute', concept: term.attribute }, zero_division: 'NULL' }
  }
  return value
}
const expression = computed(() => ({
  kind: 'aggregate', function: fn.value, value: valueExpression(), distinct: false,
  ...(fn.value === 'PERCENTILE' ? { percentile: percentile.value, method: method.value, accuracy: accuracy.value } : {}),
  nulls: 'IGNORE',
}))

function flatten(value: any): Term[] {
  if (!value) return []
  if (value.kind === 'attribute') return [{ operator: 'ADD', attribute: value.concept }]
  if (value.kind === 'binary') {
    const left = flatten(value.left), right = flatten(value.right)
    if (right.length) right[0]!.operator = value.operator
    return [...left, ...right]
  }
  return []
}
function load() {
  loading = true
  const expressionValue = attrs.value.expression || {}
  fn.value = expressionValue.function || 'SUM'
  percentile.value = expressionValue.percentile ?? 0.5
  method.value = expressionValue.method || 'CONTINUOUS'
  accuracy.value = expressionValue.accuracy || 'EXACT'
  terms.value = flatten(expressionValue.value)
  resultType.value = attrs.value.result_type || 'decimal'
  unit.value = attrs.value.unit || ''
  loading = false
}
watch(() => attrs.value, load, { immediate: true })
watch([fn, resultType, unit, percentile, method, accuracy, terms], () => {
  if (loading) return
  const next = { ...attrs.value, expression: expression.value, result_type: resultType.value, unit: unit.value || null }
  if (JSON.stringify(next) !== JSON.stringify(attrs.value)) attrs.value = next
}, { deep: true })
function addTerm() { terms.value.push({ operator: terms.value.length ? 'ADD' : 'ADD', attribute: '' }) }
</script>

<style scoped>
.metric-editor { display:flex; flex-direction:column; gap:12px; }.note { font-size:12px; line-height:1.55; background:#eef7fa; border-left:3px solid #27a8b1; padding:9px 11px; border-radius:7px; color:#3a5268; }
.grid { display:grid; grid-template-columns:repeat(3,1fr); gap:9px; }.grid label { font-size:11px; color:#6c8298; display:flex; flex-direction:column; gap:4px; }
.expression,.preview { border:1px solid #dbe5f2; background:#f8fbff; border-radius:9px; padding:10px; }.expr-head { display:flex; justify-content:space-between; align-items:center; color:#29475f; font-size:12px; }
.terms { display:flex; flex-direction:column; gap:7px; margin-top:8px; }.term { display:flex; align-items:center; gap:7px; }.operator { width:70px; }.attribute { flex:1; }.first { width:70px; color:#8497aa; font-size:11px; text-align:center; }.empty { color:#8497aa; font-size:11px; padding-top:8px; }
.preview span { color:#6c8298; font-size:11px; }.preview pre { max-height:180px; overflow:auto; font:10px/1.45 'Cascadia Code',Consolas,monospace; color:#35516c; white-space:pre-wrap; }
</style>
