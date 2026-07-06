<template>
  <div class="res-page">
    <div class="rp-head">
      <div>
        <h1>源管理</h1>
        <p>管理数据源 / Agent / 动作（Resolver）。每个源引用一个兼容类型的凭据；保存后即时生效。</p>
      </div>
      <el-button type="primary" @click="openCreate">＋ 新增源</el-button>
    </div>

    <el-table v-loading="loading" :data="items" class="rp-table" empty-text="暂无源">
      <el-table-column prop="resolver_name" label="名称" min-width="150" />
      <el-table-column label="类型" width="120">
        <template #default="{ row }">{{ typeLabel(row.resolver_type) }}</template>
      </el-table-column>
      <el-table-column prop="credential_name" label="凭据" min-width="150">
        <template #default="{ row }">{{ row.credential_name || '—' }}</template>
      </el-table-column>
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag :type="row.is_active ? 'success' : 'info'" size="small" effect="plain">
            {{ row.is_active ? '启用' : '停用' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="150" align="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
          <el-button link type="danger" @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dlg" :title="editing ? '编辑源' : '新增源'" width="520px" @closed="reset">
      <div class="fld">
        <label>名称</label>
        <el-input v-model="form.resolver_name" :disabled="editing" placeholder="唯一标识，如 dwh" />
      </div>
      <div class="fld">
        <label>类型</label>
        <el-select v-model="form.resolver_type" :disabled="editing" style="width:100%" @change="onTypeChange">
          <el-option value="sql" label="SQL 数据源" />
          <el-option value="agent" label="Agent（LLM）" />
          <el-option value="action" label="Action（动作）" />
        </el-select>
      </div>
      <div class="fld" v-if="credType">
        <label>凭据（{{ credType }} 类型）</label>
        <el-select v-model="form.credential_name" style="width:100%" placeholder="选择一个凭据" filterable>
          <el-option v-for="c in compatCreds" :key="c.credential_name" :value="c.credential_name" :label="c.credential_name" />
        </el-select>
        <div class="hint" v-if="!compatCreds.length">没有 {{ credType }} 类型的凭据，请先到「凭据」页新增。</div>
      </div>
      <div class="fld" v-else>
        <div class="hint">该类型无需凭据。</div>
      </div>
      <div class="fld">
        <label>附加配置 config（JSON，可选）</label>
        <el-input v-model="form.config" type="textarea" :rows="2" placeholder="{}" />
      </div>
      <div class="fld">
        <el-checkbox v-model="form.is_active">启用</el-checkbox>
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
import {
  listResolverAdmin, createResolverAdmin, updateResolverAdmin, deleteResolverAdmin,
  RESOLVER_CRED_TYPE, type ResolverAdminItem,
} from '../bff/ResolverAdmin.js'
import { listCredentials, type CredentialListItem } from '../bff/Credentials.js'
import { reloadRegistry } from '../backend/Registry.js'

const TYPE_LABELS: Record<string, string> = { sql: 'SQL 数据源', agent: 'Agent（LLM）', action: 'Action（动作）' }

const items = ref<ResolverAdminItem[]>([])
const creds = ref<CredentialListItem[]>([])
const loading = ref(false)

const dlg = ref(false)
const editing = ref(false)
const saving = ref(false)
const form = reactive<{ resolver_name: string; resolver_type: string; credential_name: string; config: string; is_active: boolean }>({
  resolver_name: '', resolver_type: 'sql', credential_name: '', config: '', is_active: true,
})

const credType = computed(() => RESOLVER_CRED_TYPE[form.resolver_type] ?? null)
const compatCreds = computed(() => creds.value.filter((c) => c.credential_type === credType.value))
const isValidConfig = computed(() => {
  if (!form.config.trim()) return true
  try { JSON.parse(form.config); return true } catch { return false }
})
const canSubmit = computed(() => {
  if (!form.resolver_name.trim() || !form.resolver_type || !isValidConfig.value) return false
  if (credType.value && !form.credential_name) return false   // 需要凭据的类型必须选
  return true
})

function typeLabel(t: string) { return TYPE_LABELS[t] || t }

onMounted(async () => { await Promise.all([load(), loadCreds()]) })

async function load() {
  loading.value = true
  try { items.value = await listResolverAdmin() }
  catch (e: any) { ElMessage.error('加载失败：' + (e?.message || e)) }
  finally { loading.value = false }
}
async function loadCreds() {
  try { creds.value = await listCredentials() } catch { /* ignore */ }
}

function reset() {
  form.resolver_name = ''; form.resolver_type = 'sql'; form.credential_name = ''; form.config = ''; form.is_active = true
  editing.value = false
}
function onTypeChange() { form.credential_name = '' }
function openCreate() { reset(); editing.value = false; dlg.value = true }
function openEdit(row: ResolverAdminItem) {
  reset()
  editing.value = true
  form.resolver_name = row.resolver_name
  form.resolver_type = row.resolver_type
  form.credential_name = row.credential_name || ''
  form.config = row.config && row.config !== '{}' ? row.config : ''
  form.is_active = row.is_active
  dlg.value = true
}

async function submit() {
  saving.value = true
  try {
    const payload = {
      resolver_name: form.resolver_name.trim(), resolver_type: form.resolver_type,
      credential_name: credType.value ? (form.credential_name || null) : null,
      config: form.config.trim() || '{}', is_active: form.is_active,
    }
    if (editing.value) await updateResolverAdmin(form.resolver_name, payload)
    else await createResolverAdmin(payload)
    await reloadRegistry()
    ElMessage.success(editing.value ? '已更新' : '已创建')
    dlg.value = false
    await load()
  } catch (e: any) {
    ElMessage.error('保存失败：' + (e?.message || e))
  } finally {
    saving.value = false
  }
}

async function remove(row: ResolverAdminItem) {
  try { await ElMessageBox.confirm(`删除源「${row.resolver_name}」？`, '确认', { type: 'warning' }) } catch { return }
  try {
    await deleteResolverAdmin(row.resolver_name)
    await reloadRegistry()
    ElMessage.success('已删除')
    await load()
  } catch (e: any) {
    ElMessage.error('删除失败：' + (e?.message || e))
  }
}
</script>

<style scoped>
.res-page { flex: 1; min-height: 0; overflow-y: auto; padding: 24px 28px 34px; background: #f3f6fb; }
.rp-head {
  display: flex; align-items: flex-start; justify-content: space-between;
  margin-bottom: 18px; padding: 16px 20px; border-radius: 14px;
  background: #fff; border: 1px solid #dfe6f0; box-shadow: 0 8px 22px rgba(22, 43, 77, 0.05);
}
.rp-head h1 { font-size: 20px; color: #20314c; margin: 0; }
.rp-head p { color: #667991; font-size: 13px; margin: 6px 0 0; }
.rp-table { background: transparent; }
.fld { margin-bottom: 12px; }
.fld label { display: block; font-size: 12px; color: #5a6b80; margin-bottom: 5px; }
.hint { font-size: 11px; color: #c07a3e; margin-top: 4px; }
</style>
