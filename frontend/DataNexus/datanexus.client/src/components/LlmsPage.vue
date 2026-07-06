<template>
  <div class="llm-page">
    <div class="lp-head">
      <div>
        <h1>LLM</h1>
        <p>管理"规划大脑"可选模型（编译器 / 本体路由用）。提问时可在下拉里选择本次运行使用哪个。</p>
      </div>
      <el-button type="primary" @click="openCreate">＋ 新增 LLM</el-button>
    </div>

    <el-table v-loading="loading" :data="items" class="lp-table" empty-text="暂无 LLM">
      <el-table-column label="名称" min-width="160">
        <template #default="{ row }">
          <span>{{ row.llm_name }}</span>
          <el-tag v-if="row.is_default" size="small" type="success" effect="plain" class="def-tag">默认</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="provider" label="Provider" width="150" />
      <el-table-column prop="credential_name" label="凭据" min-width="160" />
      <el-table-column label="操作" width="220" align="right">
        <template #default="{ row }">
          <el-button v-if="!row.is_default" link type="success" @click="makeDefault(row)">设为默认</el-button>
          <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
          <el-button link type="danger" @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dlg" :title="editing ? '编辑 LLM' : '新增 LLM'" width="520px" @closed="reset">
      <div class="fld">
        <label>名称</label>
        <el-input v-model="form.llm_name" :disabled="editing" placeholder="唯一标识，如 gpt-5-planner" />
      </div>
      <div class="fld">
        <label>Provider</label>
        <el-select v-model="form.provider" style="width:100%">
          <el-option value="azure_openai" label="Azure OpenAI" />
        </el-select>
      </div>
      <div class="fld">
        <label>凭据（azure_openai 类型）</label>
        <el-select v-model="form.credential_name" style="width:100%" placeholder="选择一个凭据" filterable>
          <el-option v-for="c in openaiCreds" :key="c.credential_name" :value="c.credential_name" :label="c.credential_name" />
        </el-select>
        <div class="hint" v-if="!openaiCreds.length">没有 azure_openai 类型的凭据，请先到「凭据」页新增。</div>
      </div>
      <div class="fld">
        <label>附加配置 config（JSON，可选）</label>
        <el-input v-model="form.config" type="textarea" :rows="2" placeholder='如 {"deployment":"gpt-5.4"}' />
      </div>
      <div class="fld">
        <el-checkbox v-model="form.is_default">设为默认（提问未选时使用）</el-checkbox>
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
import { listLlms, createLlm, updateLlm, deleteLlm, setDefaultLlm, type LlmItem } from '../bff/Llms.js'
import { listCredentials, type CredentialListItem } from '../bff/Credentials.js'
import { reloadRegistry } from '../backend/Registry.js'

const items = ref<LlmItem[]>([])
const creds = ref<CredentialListItem[]>([])
const loading = ref(false)

const dlg = ref(false)
const editing = ref(false)
const saving = ref(false)
const form = reactive<{ llm_name: string; provider: string; credential_name: string; config: string; is_default: boolean }>({
  llm_name: '', provider: 'azure_openai', credential_name: '', config: '', is_default: false,
})

const openaiCreds = computed(() => creds.value.filter((c) => c.credential_type === 'azure_openai'))

const canSubmit = computed(() =>
  !!form.llm_name.trim() && !!form.provider && !!form.credential_name && isValidConfig.value,
)
const isValidConfig = computed(() => {
  if (!form.config.trim()) return true
  try { JSON.parse(form.config); return true } catch { return false }
})

onMounted(async () => {
  await Promise.all([load(), loadCreds()])
})

async function load() {
  loading.value = true
  try { items.value = await listLlms() }
  catch (e: any) { ElMessage.error('加载失败：' + (e?.message || e)) }
  finally { loading.value = false }
}
async function loadCreds() {
  try { creds.value = await listCredentials() } catch { /* ignore */ }
}

function reset() {
  form.llm_name = ''; form.provider = 'azure_openai'; form.credential_name = ''; form.config = ''; form.is_default = false
  editing.value = false
}
function openCreate() { reset(); editing.value = false; dlg.value = true }
function openEdit(row: LlmItem) {
  reset()
  editing.value = true
  form.llm_name = row.llm_name
  form.provider = row.provider || 'azure_openai'
  form.credential_name = row.credential_name || ''
  form.config = row.config && row.config !== '{}' ? row.config : ''
  form.is_default = row.is_default
  dlg.value = true
}

async function submit() {
  saving.value = true
  try {
    const payload = {
      llm_name: form.llm_name.trim(), provider: form.provider,
      credential_name: form.credential_name || null,
      config: form.config.trim() || '{}', is_default: form.is_default,
    }
    if (editing.value) await updateLlm(form.llm_name, payload)
    else await createLlm(payload)
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

async function makeDefault(row: LlmItem) {
  try {
    await setDefaultLlm(row.llm_name)
    await reloadRegistry()
    ElMessage.success('已设为默认')
    await load()
  } catch (e: any) {
    ElMessage.error('操作失败：' + (e?.message || e))
  }
}

async function remove(row: LlmItem) {
  try { await ElMessageBox.confirm(`删除 LLM「${row.llm_name}」？`, '确认', { type: 'warning' }) } catch { return }
  try {
    await deleteLlm(row.llm_name)
    await reloadRegistry()
    ElMessage.success('已删除')
    await load()
  } catch (e: any) {
    ElMessage.error('删除失败：' + (e?.message || e))
  }
}
</script>

<style scoped>
.llm-page { flex: 1; min-height: 0; overflow-y: auto; padding: 24px 28px 34px; background: #f3f6fb; }
.lp-head {
  display: flex; align-items: flex-start; justify-content: space-between;
  margin-bottom: 18px; padding: 16px 20px; border-radius: 14px;
  background: #fff; border: 1px solid #dfe6f0; box-shadow: 0 8px 22px rgba(22, 43, 77, 0.05);
}
.lp-head h1 { font-size: 20px; color: #20314c; margin: 0; }
.lp-head p { color: #667991; font-size: 13px; margin: 6px 0 0; }
.lp-table { background: transparent; }
.def-tag { margin-left: 8px; }
.fld { margin-bottom: 12px; }
.fld label { display: block; font-size: 12px; color: #5a6b80; margin-bottom: 5px; }
.hint { font-size: 11px; color: #c07a3e; margin-top: 4px; }
</style>
