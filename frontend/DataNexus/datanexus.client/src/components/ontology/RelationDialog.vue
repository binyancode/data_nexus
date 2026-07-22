<template>
  <el-dialog :model-value="modelValue" :title="editing ? '编辑实体关系' : '新建实体关系'" width="760px"
             @update:model-value="emit('update:modelValue', $event)">
    <div v-if="form" class="relation-form">
      <section class="section">
        <h4>1 · 关联端点</h4>
        <div class="endpoints">
          <div class="endpoint">
            <span class="tag">从</span><b>{{ entityName(form.from.entity) }}</b>
            <el-select v-model="form.from.attribute" multiple placeholder="选择关联属性" style="width:100%">
              <el-option v-for="a in attributes(form.from.entity)" :key="a.id" :value="a.id"
                         :label="attributeLabel(a)" />
            </el-select>
          </div>
          <span class="equals">＝</span>
          <div class="endpoint">
            <span class="tag to">到</span><b>{{ entityName(form.to.entity) }}</b>
            <el-select v-model="form.to.attribute" multiple placeholder="选择关联属性" style="width:100%">
              <el-option v-for="a in attributes(form.to.entity)" :key="a.id" :value="a.id"
                         :label="attributeLabel(a)" />
            </el-select>
          </div>
        </div>
        <el-input v-model="form.name" placeholder="关系名称" />
      </section>

      <section class="section">
        <h4>2 · 关系类型 <em>必选</em></h4>
        <div class="card-options">
          <button v-for="option in cardinalities" :key="option.value" type="button"
                  :class="{ selected: cardinality === option.value }" @click="cardinality = option.value">
            <b>{{ option.label }}</b><span>{{ option.help }}</span>
          </button>
        </div>
        <el-alert v-if="cardinality === 'N:M'" type="warning" :closable="false"
                  title="多对多关系容易造成指标重复计算，推荐显式建立桥实体。" />
      </section>

      <section class="section">
        <h4>3 · 可选性 <em>两个方向均必答</em></h4>
        <label>每条「{{ entityName(form.from.entity) }}」记录是否必须匹配至少一条「{{ entityName(form.to.entity) }}」记录？</label>
        <el-radio-group v-model="form.multiplicity.from_to.min">
          <el-radio :value="1">必须</el-radio><el-radio :value="0">可以没有</el-radio><el-radio value="unknown">未知</el-radio>
        </el-radio-group>
        <label>每条「{{ entityName(form.to.entity) }}」记录是否必须被至少一条「{{ entityName(form.from.entity) }}」记录匹配？</label>
        <el-radio-group v-model="form.multiplicity.to_from.min">
          <el-radio :value="1">必须</el-radio><el-radio :value="0">可以没有</el-radio><el-radio value="unknown">未知</el-radio>
        </el-radio-group>
      </section>

      <section class="section">
        <h4>4 · 完整性来源</h4>
        <el-select v-model="form.integrity.mode" style="width:100%">
          <el-option value="ENFORCED" label="数据库约束（源系统强制）" />
          <el-option value="DECLARED" label="业务声明（人工确认）" />
          <el-option value="INFERRED" label="系统推断（未受源约束）" />
          <el-option value="UNKNOWN" label="未知" />
        </el-select>
        <div class="grid2">
          <label>约束名称
            <el-input v-model="form.integrity.constraint_name" placeholder="仅数据库约束（ENFORCED）必填" />
          </label>
          <label>可信度（0–1）
            <el-input-number v-model="form.integrity.confidence" :min="0" :max="1" :step="0.05" :precision="2" />
          </label>
        </div>
        <div class="field-help">0 表示不能依赖该关系做基数优化，1 表示完全可信；它不是记录数量，也不会修改数据源约束。</div>
      </section>

      <section class="preview">
        <h4>保存后的业务含义</h4>
        <p>{{ preview }}</p>
        <el-alert v-if="hasUnknown" type="warning" :closable="false"
                  title="存在未知基数或可选性：仍可执行保守 JOIN，但会禁用依赖基数的预聚合和 JOIN 重排。" />
      </section>
    </div>
    <template #footer>
      <el-button v-if="editing" type="danger" plain @click="emit('delete')">删除</el-button>
      <span class="spacer"></span>
      <el-button @click="emit('update:modelValue', false)">取消</el-button>
      <el-button type="primary" @click="save">确认语义并保存</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import type { AttributeNode, EntityNodeData, RelationEdge } from '../../bff/Ontology'

const props = defineProps<{
  modelValue: boolean
  editing: boolean
  relation: RelationEdge | null
  entities: EntityNodeData[]
}>()
const emit = defineEmits<{
  (e: 'update:modelValue', value: boolean): void
  (e: 'save', relation: RelationEdge): void
  (e: 'delete'): void
}>()

const form = ref<RelationEdge | null>(null)
const cardinality = ref<'N:1' | '1:N' | '1:1' | 'N:M' | 'UNKNOWN'>('UNKNOWN')
const cardinalities = [
  { value: 'N:1', label: 'N : 1', help: '多个 From 对应一个 To' },
  { value: '1:N', label: '1 : N', help: '一个 From 对应多个 To' },
  { value: '1:1', label: '1 : 1', help: '两侧最多各一条' },
  { value: 'N:M', label: 'N : M', help: '两侧都可能多条' },
  { value: 'UNKNOWN', label: '? : ?', help: '无法保证基数' },
] as const

watch(() => props.relation, (value) => {
  form.value = value ? JSON.parse(JSON.stringify(value)) : null
  if (form.value) {
    form.value.from.attribute = asArray(form.value.from.attribute)
    form.value.to.attribute = asArray(form.value.to.attribute)
  }
  cardinality.value = value ? cardinalityOf(value) : 'UNKNOWN'
}, { immediate: true, deep: true })

watch(cardinality, (value) => {
  if (!form.value) return
  const [left, right] = ({
    'N:1': ['many', 1], '1:N': [1, 'many'], '1:1': [1, 1], 'N:M': ['many', 'many'],
    UNKNOWN: ['unknown', 'unknown'],
  } as any)[value]
  // Label is from:to. to_from describes the number of From rows for one To.
  form.value.multiplicity.to_from.max = left
  form.value.multiplicity.from_to.max = right
})

watch(() => form.value?.integrity.mode, (mode, previous) => {
  if (!form.value || !mode || mode === previous) return
  if (mode === 'ENFORCED' || mode === 'DECLARED') form.value.integrity.confidence = 1
  else if (mode === 'INFERRED') form.value.integrity.confidence = 0.5
  else form.value.integrity.confidence = 0
})

function cardinalityOf(value: RelationEdge): typeof cardinality.value {
  const left = value.multiplicity.to_from.max
  const right = value.multiplicity.from_to.max
  if (left === 'many' && right === 1) return 'N:1'
  if (left === 1 && right === 'many') return '1:N'
  if (left === 1 && right === 1) return '1:1'
  if (left === 'many' && right === 'many') return 'N:M'
  return 'UNKNOWN'
}
function entityName(id: string) { return props.entities.find((entity) => entity.id === id)?.name || id }
function attributes(entity: string) { return props.entities.find((item) => item.id === entity)?.attributes || [] }
function asArray(value: string | string[]) { return Array.isArray(value) ? value : value ? [value] : [] }
function attributeLabel(attribute: AttributeNode) {
  const flags = [attribute.constraints?.primary_key ? 'PK' : '', attribute.constraints?.unique ? 'UNIQUE' : '',
    attribute.constraints?.nullable === false ? 'NOT NULL' : ''].filter(Boolean).join(' · ')
  return `${attribute.name}${flags ? `（${flags}）` : ''}`
}
function minText(value: 0 | 1 | 'unknown', subject: string) {
  if (value === 1) return `${subject}必须至少匹配一条记录`
  if (value === 0) return `${subject}可以没有匹配记录`
  return `${subject}是否必须匹配未知`
}
const preview = computed(() => {
  if (!form.value) return ''
  const from = entityName(form.value.from.entity), to = entityName(form.value.to.entity)
  const right = form.value.multiplicity.from_to.max === 1 ? '最多一个' : form.value.multiplicity.from_to.max === 'many' ? '多个' : '未知数量的'
  const left = form.value.multiplicity.to_from.max === 1 ? '最多一个' : form.value.multiplicity.to_from.max === 'many' ? '多个' : '未知数量的'
  return `每条${from}对应${right}${to}；每条${to}对应${left}${from}。${minText(form.value.multiplicity.from_to.min, from)}；${minText(form.value.multiplicity.to_from.min, to)}。`
})
const hasUnknown = computed(() => !!form.value && [form.value.multiplicity.from_to.min, form.value.multiplicity.from_to.max,
  form.value.multiplicity.to_from.min, form.value.multiplicity.to_from.max].includes('unknown'))

function save() {
  const value = form.value
  if (!value) return
  const fromAttrs = asArray(value.from.attribute), toAttrs = asArray(value.to.attribute)
  if (!fromAttrs.length || !toAttrs.length) return void ElMessage.warning('请选择两侧关联属性')
  if (fromAttrs.length !== toAttrs.length) return void ElMessage.warning('复合关系两侧属性数量必须一致')
  if (!cardinality.value) return void ElMessage.warning('请选择关系类型')
  if (value.multiplicity.from_to.min == null || value.multiplicity.to_from.min == null) return void ElMessage.warning('请回答两个方向的可选性')
  if (value.integrity.mode === 'ENFORCED' && !value.integrity.constraint_name) return void ElMessage.warning('数据库约束必须填写约束名称')
  value.from.attribute = fromAttrs.length === 1 ? fromAttrs[0]! : fromAttrs
  value.to.attribute = toAttrs.length === 1 ? toAttrs[0]! : toAttrs
  value.confirmation = { required: false, confirmed: true }
  emit('save', value)
}
</script>

<style scoped>
.relation-form { display:flex; flex-direction:column; gap:14px; }
.section { border:1px solid #dbe5f2; background:#f8fbff; border-radius:12px; padding:13px; display:flex; flex-direction:column; gap:9px; }
h4 { margin:0; color:#17354f; font-size:13px; } h4 em { color:#c45d48; font-style:normal; font-size:11px; }
.endpoints { display:grid; grid-template-columns:1fr 30px 1fr; align-items:center; gap:10px; }
.endpoint { display:flex; flex-direction:column; gap:7px; }.tag { color:#178aa0; font-size:11px; }.tag.to { color:#7b62c8; }.equals { text-align:center; font-size:20px; color:#8193a6; }
.card-options { display:grid; grid-template-columns:repeat(5,1fr); gap:7px; }
.card-options button { border:1px solid #d7e1ee; border-radius:9px; background:white; padding:9px 6px; cursor:pointer; color:#52687e; }
.card-options button b,.card-options button span { display:block; }.card-options button span { margin-top:3px; font-size:10px; }
.card-options button.selected { border-color:#27a8b1; box-shadow:0 0 0 2px rgba(39,168,177,.14); color:#126d78; }
.section label { font-size:12px; color:#52687e; }.grid2 { display:grid; grid-template-columns:1fr 190px; gap:9px; }
.grid2 label { display:flex; flex-direction:column; gap:5px; }.grid2 :deep(.el-input-number) { width:100%; }.field-help { font-size:11px; color:#7b8da0; line-height:1.5; }
.preview { border-left:4px solid #27a8b1; background:#eef8fa; border-radius:9px; padding:12px; }.preview p { color:#29475f; line-height:1.65; }
.spacer { flex:1; }
:deep(.el-dialog__footer) > span { display:flex; width:100%; align-items:center; }
</style>
