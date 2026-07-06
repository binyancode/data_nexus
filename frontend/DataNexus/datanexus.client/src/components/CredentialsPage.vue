<template>
  <div class="creds-page">
    <div class="cp-head">
      <div>
        <h1>凭据</h1>
        <p>集中管理数据源 / LLM 的连接凭据。敏感信息存 Key Vault，此处不展示密文。</p>
      </div>
      <el-button type="primary" @click="openCreate">＋ 新增凭据</el-button>
    </div>

    <el-table v-loading="loading" :data="items" class="cp-table" empty-text="暂无凭据">
      <el-table-column prop="credential_name" label="名称" min-width="160" />
      <el-table-column label="类型" width="150">
        <template #default="{ row }">{{ typeLabel(row.credential_type) }}</template>
      </el-table-column>
      <el-table-column prop="description" label="描述" min-width="200" show-overflow-tooltip />
      <el-table-column label="更新时间" width="180">
        <template #default="{ row }">{{ fmt(row.update_time || row.creation_time) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="150" align="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
          <el-button link type="danger" @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dlg" :title="editing ? '编辑凭据' : '新增凭据'" width="520px" @closed="reset">
      <div v-loading="detailLoading">
      <div class="fld">
        <label>名称</label>
        <el-input v-model="form.credential_name" :disabled="editing" placeholder="唯一标识，如 dwh-sql" />
      </div>
      <div class="fld">
        <label>类型</label>
        <el-select v-model="form.credential_type" :disabled="editing" style="width:100%" @change="onTypeChange">
          <el-option v-for="(t, k) in types" :key="k" :value="k" :label="t.display_name" />
        </el-select>
      </div>
      <div class="fld">
        <label>描述</label>
        <el-input v-model="form.description" placeholder="可选" />
      </div>

      <template v-if="currentSchema.length">
        <div class="sec-t">连接信息</div>
        <div v-for="f in currentSchema" :key="f.name" class="fld">
          <label>
            {{ f.name }}
            <span v-if="f.required" class="req">*</span>
            <span v-if="f.sensitive" class="sens">敏感</span>
          </label>
          <el-input
            v-model="form.data[f.name]"
            :type="f.sensitive ? 'password' : (f.type === 'number' ? 'number' : 'text')"
            :show-password="f.sensitive"
            :placeholder="placeholderFor(f)"
            @input="dirty[f.name] = true"
          />
          <div v-if="f.description" class="hint">{{ f.description }}</div>
        </div>
      </template>
      </div>

      <template #footer>
        <el-button @click="dlg = false">取消</el-button>
        <el-button type="primary" :loading="saving" :disabled="!canSubmit" @click="submit">
          {{ editing ? '保存' : '创建' }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { listCredentials, type CredentialListItem } from '../bff/Credentials.js'
import {
  getCredentialTypes, getCredentialDetail, createCredential, updateCredential, deleteCredential,
  type CredentialTypeMeta,
} from '../backend/Credentials.js'

const SENTINEL = '••••••'   // 敏感字段占位；用户必须重新输入才提交

const items = ref<CredentialListItem[]>([])
const loading = ref(false)
const types = ref<Record<string, CredentialTypeMeta>>({})

const dlg = ref(false)
const editing = ref(false)
const saving = ref(false)
const detailLoading = ref(false)
const form = reactive<{ credential_name: string; credential_type: string; description: string; data: Record<string, any> }>({
  credential_name: '', credential_type: '', description: '', data: {},
})
const dirty = reactive<Record<string, boolean>>({})

const currentSchema = computed(() => types.value[form.credential_type]?.schema ?? [])

function typeLabel(t: string) { return types.value[t]?.display_name || t }
function fmt(s: string | null) {
  if (!s) return ''
  const d = new Date(s)
  return isNaN(d.getTime()) ? s : d.toLocaleString('zh-CN', { hour12: false })
}
function placeholderFor(f: { sensitive: boolean }) {
  return editing.value && f.sensitive ? '（保密，需重新输入）' : ''
}

// 提交条件：必填字段都有值；编辑态下敏感字段必须重新填（不能留占位/空）
const canSubmit = computed(() => {
  if (!form.credential_name.trim() || !form.credential_type) return false
  for (const f of currentSchema.value) {
    const v = form.data[f.name]
    if (f.required && (v == null || String(v).trim() === '')) return false
    if (f.sensitive && (v == null || String(v).trim() === '' || v === SENTINEL)) return false
  }
  return true
})

onMounted(async () => {
  loading.value = true
  try { types.value = await getCredentialTypes() } catch (e: any) { ElMessage.error('加载类型失败：' + (e?.message || e)) }
  await load()
})

async function load() {
  loading.value = true
  try { items.value = await listCredentials() }
  catch (e: any) { ElMessage.error('加载失败：' + (e?.message || e)) }
  finally { loading.value = false }
}

function reset() {
  form.credential_name = ''; form.credential_type = ''; form.description = ''; form.data = {}
  for (const k of Object.keys(dirty)) delete dirty[k]
  editing.value = false
}

function onTypeChange() {
  form.data = {}
}

function openCreate() {
  reset()
  editing.value = false
  dlg.value = true
}

async function openEdit(row: CredentialListItem) {
  reset()
  editing.value = true
  form.credential_name = row.credential_name
  form.credential_type = row.credential_type
  form.description = row.description || ''
  dlg.value = true
  detailLoading.value = true
  try {
    const detail = await getCredentialDetail(row.credential_name)   // 仅非敏感字段
    form.data = { ...detail.data }
    // 敏感字段留空，强制重新输入
    for (const f of currentSchema.value) {
      if (f.sensitive && !(f.name in form.data)) form.data[f.name] = ''
    }
  } catch (e: any) {
    ElMessage.error('加载详情失败：' + (e?.message || e))
  } finally {
    detailLoading.value = false
  }
}

async function submit() {
  saving.value = true
  try {
    if (editing.value) {
      await updateCredential(form.credential_name, {
        credential_type: form.credential_type, data: { ...form.data }, description: form.description,
      })
      ElMessage.success('已更新')
    } else {
      await createCredential({
        credential_name: form.credential_name.trim(), credential_type: form.credential_type,
        data: { ...form.data }, description: form.description,
      })
      ElMessage.success('已创建')
    }
    dlg.value = false
    await load()
  } catch (e: any) {
    ElMessage.error('保存失败：' + (e?.message || e))
  } finally {
    saving.value = false
  }
}

async function remove(row: CredentialListItem) {
  try { await ElMessageBox.confirm(`删除凭据「${row.credential_name}」？`, '确认', { type: 'warning' }) } catch { return }
  try {
    await deleteCredential(row.credential_name)
    ElMessage.success('已删除')
    await load()
  } catch (e: any) {
    ElMessage.error('删除失败：' + (e?.message || e))
  }
}
</script>

<style scoped>
.creds-page { flex: 1; min-height: 0; overflow-y: auto; padding: 24px 28px 34px; background: #f3f6fb; }
.cp-head {
  display: flex; align-items: flex-start; justify-content: space-between;
  margin-bottom: 18px; padding: 16px 20px; border-radius: 14px;
  background: #fff; border: 1px solid #dfe6f0; box-shadow: 0 8px 22px rgba(22, 43, 77, 0.05);
}
.cp-head h1 { font-size: 20px; color: #20314c; margin: 0; }
.cp-head p { color: #667991; font-size: 13px; margin: 6px 0 0; }
.cp-table { background: transparent; }
.fld { margin-bottom: 12px; }
.fld label { display: block; font-size: 12px; color: #5a6b80; margin-bottom: 5px; }
.req { color: #d05656; margin-left: 2px; }
.sens { color: #b7791f; font-size: 10px; margin-left: 6px; background: #fdf3e3; border-radius: 4px; padding: 1px 5px; }
.sec-t { font-size: 12px; font-weight: 700; color: #55697f; margin: 10px 0 8px; }
.hint { font-size: 11px; color: #93a2b4; margin-top: 4px; }
</style>
