<template>
  <el-dialog :model-value="modelValue" title="从数据源导入实体" width="620px"
             @update:model-value="$emit('update:modelValue', $event)" @open="onOpen">
    <div class="iw">
      <div class="iw-row">
        <label>数据源（Resolver）</label>
        <el-select v-model="resolver" placeholder="选择 SQL 数据源" style="width: 100%" @change="loadSchema">
          <el-option v-for="r in resolvers" :key="r.name" :value="r.name"
                     :label="`${r.name}（${r.type}）`" :disabled="r.type !== 'sql'" />
        </el-select>
      </div>

      <div class="iw-tables" v-loading="loading">
        <div class="iwt-head" v-if="tableNames.length">
          <span>选择表（{{ selected.length }}/{{ tableNames.length }}）</span>
          <button class="lnk" @click="toggleAll">{{ allChecked ? '全不选' : '全选' }}</button>
        </div>
        <div v-if="tableNames.length" class="iwt-list">
          <label v-for="t in tableNames" :key="t" class="iwt-item">
            <el-checkbox :model-value="selected.includes(t)" @change="toggle(t)" />
            <span class="iwt-name">{{ t }}</span>
            <span class="iwt-cols">{{ schema[t]?.length || 0 }} 列</span>
          </label>
        </div>
        <div v-else-if="resolver && !loading" class="iw-empty">该数据源没有可用的表。</div>
        <div v-else-if="!resolver" class="iw-empty">先选择一个数据源。</div>
      </div>
    </div>

    <template #footer>
      <el-button @click="$emit('update:modelValue', false)">取消</el-button>
      <el-button type="primary" :disabled="!selected.length" :loading="importing" @click="doImport">
        导入 {{ selected.length || '' }} 张表
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { listResolvers, resolverSchema, importPreview,
         type ResolverInfo, type ImportFragment } from '../../backend/Resolvers.js'

defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{
  (e: 'update:modelValue', v: boolean): void
  (e: 'imported', frag: ImportFragment): void
}>()

const resolvers = ref<ResolverInfo[]>([])
const resolver = ref('')
const schema = ref<Record<string, { column: string; type: string }[]>>({})
const selected = ref<string[]>([])
const loading = ref(false)
const importing = ref(false)

const tableNames = computed(() => Object.keys(schema.value))
const allChecked = computed(() => tableNames.value.length > 0 && selected.value.length === tableNames.value.length)

async function onOpen() {
  selected.value = []
  schema.value = {}
  resolver.value = ''
  try {
    resolvers.value = (await listResolvers()).filter((r) => r.type === 'sql')
    const first = resolvers.value[0]
    if (resolvers.value.length === 1 && first) { resolver.value = first.name; await loadSchema() }
  } catch (e: any) { ElMessage.error('加载数据源失败：' + (e?.message || e)) }
}

async function loadSchema() {
  if (!resolver.value) return
  loading.value = true
  selected.value = []
  try {
    const s = await resolverSchema(resolver.value)
    schema.value = s.tables || {}
  } catch (e: any) {
    ElMessage.error('探测失败：' + (e?.message || e))
    schema.value = {}
  } finally { loading.value = false }
}

function toggle(t: string) {
  const i = selected.value.indexOf(t)
  if (i >= 0) selected.value.splice(i, 1)
  else selected.value.push(t)
}
function toggleAll() {
  selected.value = allChecked.value ? [] : [...tableNames.value]
}

async function doImport() {
  importing.value = true
  try {
    const frag = await importPreview(resolver.value, selected.value)
    emit('imported', frag)
    emit('update:modelValue', false)
  } catch (e: any) {
    ElMessage.error('导入失败：' + (e?.message || e))
  } finally { importing.value = false }
}
</script>

<style scoped>
.iw { display: flex; flex-direction: column; gap: 14px; }
.iw-row label { display: block; font-size: 12px; color: var(--beone-text-secondary); margin-bottom: 4px; }
.iw-tables { min-height: 180px; }
.iwt-head { display: flex; align-items: center; justify-content: space-between; font-size: 12px; color: var(--beone-text-secondary); margin-bottom: 6px; }
.lnk { border: 0; background: none; color: var(--beone-cerulean-blue); cursor: pointer; font-size: 12px; }
.iwt-list { max-height: 300px; overflow-y: auto; border: 1px solid var(--beone-border); border-radius: 8px; }
.iwt-item { display: flex; align-items: center; gap: 8px; padding: 7px 12px; border-bottom: 1px solid var(--beone-bg-midnight-soft); cursor: pointer; }
.iwt-item:last-child { border-bottom: 0; }
.iwt-name { flex: 1; font-family: 'Cascadia Code', Consolas, monospace; font-size: 13px; color: var(--beone-text-primary); }
.iwt-cols { font-size: 11px; color: var(--beone-text-secondary); }
.iw-empty { padding: 30px; text-align: center; color: var(--beone-text-secondary); font-size: 13px; }
</style>
