<template>
  <div class="op">
    <OntologyEditor v-if="openId" :ontology-id="openId" @back="openId = null; load()" />

    <div v-else class="op-list">
      <div class="op-head">
        <div>
          <h1>本体</h1>
          <p>把数据源建成语义本体，供自然语言查询使用。</p>
        </div>
        <el-button type="primary" @click="createOpen = true">＋ 新建空白本体</el-button>
      </div>

      <div v-loading="loading" class="op-sections">
        <section v-for="sec in sections" :key="sec.key" v-show="sec.items.length">
          <div class="sec-h">{{ sec.label }} <span class="sec-n">{{ sec.items.length }}</span></div>
          <div class="cards">
            <div v-for="o in sec.items" :key="o.ontologyId" class="card" @click="openId = o.ontologyId">
              <div class="c-top">
                <span class="c-name">{{ o.name }}</span>
                <span class="c-vis" :class="o.visibility">{{ visLabel(o.visibility) }}</span>
              </div>
              <p class="c-desc">{{ o.description || '（无描述）' }}</p>
              <div class="c-foot">
                <span class="c-owner">{{ o.owner }}</span>
                <span v-if="!o.canEdit" class="c-ro">只读</span>
                <button v-if="o.canEdit" class="c-del" @click.stop="remove(o)">删除</button>
              </div>
            </div>
          </div>
        </section>
        <div v-if="!loading && !ontologies.length" class="op-empty">还没有本体，点右上角新建。</div>
      </div>
    </div>

    <el-dialog v-model="createOpen" title="新建空白本体" width="460px">
      <div class="fld"><label>名称</label><el-input v-model="newName" placeholder="如：销售数仓" /></div>
      <div class="fld"><label>描述（给大模型理解能回答什么）</label>
        <el-input v-model="newDesc" type="textarea" :rows="3" placeholder="可回答销售额、毛利、按地区/期间的聚合与对比…" />
      </div>
      <template #footer>
        <el-button @click="createOpen = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="doCreate">创建并编辑</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import OntologyEditor from './OntologyEditor.vue'
import { listOntologies, createOntology, deleteOntology, type OntologyMeta } from '../bff/Ontology.js'
import { authState } from '../common/authState.js'

const ontologies = ref<OntologyMeta[]>([])
const loading = ref(false)
const openId = ref<string | null>(null)

function visLabel(v: string) { return ({ private: '私有', shared: '共享', public: '公开' } as any)[v] || v }

const sections = computed(() => {
  const me = authState.userName
  return [
    { key: 'mine', label: '我的', items: ontologies.value.filter((o) => o.owner === me) },
    { key: 'shared', label: '共享给我', items: ontologies.value.filter((o) => o.owner !== me && o.visibility === 'shared') },
    { key: 'public', label: '公开', items: ontologies.value.filter((o) => o.owner !== me && o.visibility === 'public') },
  ]
})

onMounted(load)
async function load() {
  loading.value = true
  try { ontologies.value = await listOntologies() }
  catch (e: any) { ElMessage.error('加载失败：' + (e?.message || e)) }
  finally { loading.value = false }
}

const createOpen = ref(false)
const creating = ref(false)
const newName = ref('')
const newDesc = ref('')
async function doCreate() {
  if (!newName.value.trim()) { ElMessage.warning('请填写名称'); return }
  creating.value = true
  try {
    const { ontologyId } = await createOntology(newName.value.trim(), newDesc.value || undefined)
    createOpen.value = false
    newName.value = ''; newDesc.value = ''
    openId.value = ontologyId
  } catch (e: any) { ElMessage.error('创建失败：' + (e?.message || e)) }
  finally { creating.value = false }
}

async function remove(o: OntologyMeta) {
  try { await ElMessageBox.confirm(`删除本体「${o.name}」？`, '确认', { type: 'warning' }) } catch { return }
  try { await deleteOntology(o.ontologyId); ElMessage.success('已删除'); await load() }
  catch (e: any) { ElMessage.error('删除失败：' + (e?.message || e)) }
}
</script>

<style scoped>
.op { flex: 1; min-width: 0; min-height: 0; display: flex; flex-direction: column; overflow: hidden; }
.op-list {
  flex: 1;
  overflow-y: auto;
  padding: 24px 28px 34px;
  background: #f3f6fb;
}
.op-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 22px;
  padding: 18px 20px;
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.86);
  border: 1px solid #dfe6f0;
  box-shadow: 0 10px 30px rgba(22, 43, 77, 0.06);
}
.op-head h1 {
  font-size: 20px;
  letter-spacing: 0.2px;
  color: #20314c;
  margin: 0;
}
.op-head p { color: #667991; font-size: 13px; margin: 6px 0 0; }
.op-sections { display: flex; flex-direction: column; gap: 22px; }
.sec-h { font-size: 12px; font-weight: 700; color: #55697f; margin-bottom: 10px; }
.sec-n { color: var(--beone-slate); }
.cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 14px; }
.card {
  position: relative;
  background: #ffffff;
  border: 1px solid #dfe7f2;
  border-radius: 14px;
  padding: 16px 16px;
  cursor: pointer;
  transition: transform .15s ease, box-shadow .15s ease, border-color .15s;
  box-shadow: 0 4px 14px rgba(20, 40, 70, 0.06);
}
.card::before {
  content: '';
  position: absolute;
  inset: 0 0 auto 0;
  height: 3px;
  background: #5f87b0;
  opacity: 0.85;
}
.card:hover {
  transform: translateY(-2px);
  border-color: #b7c8de;
  box-shadow: 0 14px 26px rgba(20, 40, 70, 0.12);
}
.c-top { display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px; }
.c-name { font-size: 17px; font-weight: 700; line-height: 1.25; color: #233956; }
.c-vis { font-size: 11px; padding: 1px 8px; border-radius: 9px; color: #fff; }
.c-vis.private { background: #64748b; }
.c-vis.shared { background: #e97600; }
.c-vis.public { background: #00859b; }
.c-desc { font-size: 13px; color: #60748a; line-height: 1.5; min-height: 42px; margin: 0 0 12px;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.c-foot { display: flex; align-items: center; gap: 10px; font-size: 11px; color: #71859a; }
.c-owner { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.c-ro { color: var(--beone-slate); }
.c-del { border: 0; background: none; color: #c24646; cursor: pointer; font-size: 12px; }
.op-empty { color: var(--beone-text-secondary); font-size: 13px; padding: 40px; text-align: center; }
.fld { margin-bottom: 12px; }
.fld label { display: block; font-size: 12px; color: var(--beone-text-secondary); margin-bottom: 4px; }

:deep(.op-head .el-button--primary) {
  border: none;
  background: #2f7dbc;
  box-shadow: 0 8px 16px rgba(47, 125, 188, 0.24);
}

@media (max-width: 900px) {
  .op-list { padding: 16px; }
  .op-head { flex-direction: column; gap: 12px; }
  .c-name { font-size: 16px; }
}
</style>
