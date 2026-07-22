<template>
  <div class="ce-page">
    <div class="ce-head">
      <div>
        <h1>计算引擎</h1>
        <p>管理跨源查询使用的临时计算引擎。未显式选择时使用默认配置。</p>
      </div>
      <div class="head-actions">
        <el-button :loading="loading" @click="refresh">刷新</el-button>
        <el-button v-if="authState.isAdmin" type="primary" @click="openCreate">＋ 新增计算引擎</el-button>
      </div>
    </div>

    <el-alert
      v-if="authState.loaded && !authState.isAdmin"
      title="当前账号可查看并选择计算引擎；只有管理员可以修改配置。"
      type="info"
      :closable="false"
      class="ce-alert"
    />

    <el-table v-loading="loading" :data="items" class="ce-table" empty-text="暂无计算引擎">
      <el-table-column label="名称" min-width="160">
        <template #default="{ row }">
          <span class="engine-name">{{ row.engine_name }}</span>
          <el-tag v-if="row.is_default" size="small" type="success" effect="plain" class="def-tag">默认</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="类型" width="130">
        <template #default="{ row }">
          <el-tag :type="row.engine_type === 'duckdb' ? 'primary' : 'warning'" effect="plain">
            {{ typeLabel(row.engine_type) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="credential_name" label="SQL 凭据" min-width="150">
        <template #default="{ row }">{{ row.credential_name || '—' }}</template>
      </el-table-column>
      <el-table-column prop="runtime_user" label="运行用户" min-width="150">
        <template #default="{ row }">{{ row.runtime_user || '—' }}</template>
      </el-table-column>
      <el-table-column label="能力" min-width="230">
        <template #default="{ row }">
          <span class="caps">{{ capabilityText(row) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="状态" min-width="180">
        <template #default="{ row }">
          <el-tag :type="row.provision_state === 'ready' ? 'success' : 'danger'" size="small">
            {{ row.provision_state === 'ready' ? '就绪' : row.provision_state }}
          </el-tag>
          <div v-if="row.provision_error" class="state-error" :title="row.provision_error">
            {{ row.provision_error }}
          </div>
        </template>
      </el-table-column>
      <el-table-column v-if="authState.isAdmin" label="操作" width="280" align="right" fixed="right">
        <template #default="{ row }">
          <el-button v-if="row.provision_state === 'ready' && !row.is_default" link type="success" @click="makeDefault(row)">设为默认</el-button>
          <el-button v-if="row.provision_state === 'ready'" link @click="test(row)">测试</el-button>
          <el-button v-if="row.provision_state === 'ready'" link type="primary" @click="openEdit(row)">编辑</el-button>
          <el-button link type="danger" @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialogOpen" :title="editing ? '编辑计算引擎' : '新增计算引擎'" width="560px" @closed="reset">
      <div class="field">
        <label>名称</label>
        <el-input v-model="form.engine_name" :disabled="editing" placeholder="唯一名称，如 sql-server-temp" />
      </div>
      <div class="field">
        <label>类型</label>
        <el-select v-model="form.engine_type" :disabled="editing" style="width: 100%">
          <el-option value="duckdb" label="DuckDB（进程内存）" />
          <el-option value="sql_server" label="SQL Server（独占 Session + #temp）" />
        </el-select>
      </div>

      <template v-if="form.engine_type === 'sql_server'">
        <div class="field">
          <label>管理员 SQL 凭据</label>
          <el-select
            v-model="form.credential_name"
            :disabled="editing"
            style="width: 100%"
            placeholder="选择 sql 类型凭据"
            filterable
          >
            <el-option v-for="credential in sqlCredentials" :key="credential.credential_name"
                       :value="credential.credential_name" :label="credential.credential_name" />
          </el-select>
          <div v-if="!sqlCredentials.length" class="hint">没有 sql 类型凭据，请先到「凭据」页新增。</div>
        </div>
        <div class="field">
          <label>固定运行用户名</label>
          <el-input v-model="form.runtime_user" :disabled="editing" placeholder="如 dn_compute_runtime" />
          <div class="hint">创建时将在目标数据库建立同名 <b>WITHOUT LOGIN</b> 用户；删除配置时同步删除该用户。</div>
        </div>
      </template>

      <div class="field">
        <label>运行配置（JSON）</label>
        <el-input v-model="form.config" type="textarea" :rows="4" :placeholder="configPlaceholder" />
        <div v-if="!validConfig" class="validation">JSON 格式无效</div>
      </div>
      <div class="field check-field">
        <el-checkbox v-model="form.is_default">设为默认（查询未选时使用）</el-checkbox>
      </div>

      <el-alert
        v-if="!editing && form.engine_type === 'sql_server'"
        title="创建过程会连接目标 SQL Server、创建运行用户并实际验证 #temp 表读写。"
        type="warning"
        :closable="false"
        show-icon
      />
      <el-alert
        v-if="saveError"
        class="save-error"
        title="创建或保存失败"
        :description="saveError"
        type="error"
        :closable="false"
        show-icon
      />

      <template #footer>
        <el-button @click="dialogOpen = false">取消</el-button>
        <el-button type="primary" :loading="saving" :disabled="!canSubmit" @click="submit">
          {{ editing ? '保存' : '创建并验证' }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  createComputeEngine,
  deleteComputeEngine,
  listComputeEngines,
  setDefaultComputeEngine,
  testComputeEngine,
  updateComputeEngine,
  type ComputeEngineItem,
  type ComputeEngineType,
} from '../backend/ComputeEngines.js'
import { listCredentials, type CredentialListItem } from '../bff/Credentials.js'
import { authState } from '../common/authState.js'

const items = ref<ComputeEngineItem[]>([])
const credentials = ref<CredentialListItem[]>([])
const loading = ref(false)
const saving = ref(false)
const saveError = ref('')
const dialogOpen = ref(false)
const editing = ref(false)

const form = reactive<{
  engine_name: string
  engine_type: ComputeEngineType
  credential_name: string
  runtime_user: string
  config: string
  is_default: boolean
}>({
  engine_name: '',
  engine_type: 'duckdb',
  credential_name: '',
  runtime_user: '',
  config: '{}',
  is_default: false,
})

const sqlCredentials = computed(() => credentials.value.filter((item) => item.credential_type === 'sql'))
const validConfig = computed(() => {
  try {
    const value = JSON.parse(form.config || '{}')
    return value !== null && typeof value === 'object' && !Array.isArray(value)
  } catch {
    return false
  }
})
const runtimeUserValid = computed(() => /^[A-Za-z][A-Za-z0-9_]{2,127}$/.test(form.runtime_user.trim()))
const canSubmit = computed(() => {
  if (!form.engine_name.trim() || !validConfig.value) return false
  if (form.engine_type === 'sql_server') {
    return !!form.credential_name && runtimeUserValid.value
  }
  return true
})
const configPlaceholder = computed(() => form.engine_type === 'sql_server'
  ? '{"command_timeout":120,"batch_size":1000}'
  : '{"memory_limit":"2GB","threads":4}')

onMounted(async () => {
  await refresh()
})

async function refresh() {
  await Promise.all([load(), loadCredentials()])
}

function errorText(error: any): string {
  return error?.response?.data?.message || error?.message || String(error)
}

async function load() {
  loading.value = true
  try {
    items.value = await listComputeEngines()
  } catch (error: any) {
    ElMessage.error('加载失败：' + errorText(error))
  } finally {
    loading.value = false
  }
}

async function loadCredentials() {
  try { credentials.value = await listCredentials() } catch { /* 管理员表单自行显示空状态 */ }
}

function reset() {
  form.engine_name = ''
  form.engine_type = 'duckdb'
  form.credential_name = ''
  form.runtime_user = ''
  form.config = '{}'
  form.is_default = false
  saveError.value = ''
  editing.value = false
}

function openCreate() {
  reset()
  dialogOpen.value = true
}

function openEdit(row: ComputeEngineItem) {
  reset()
  editing.value = true
  form.engine_name = row.engine_name
  form.engine_type = row.engine_type
  form.credential_name = row.credential_name || ''
  form.runtime_user = row.runtime_user || ''
  form.config = JSON.stringify(row.config || {}, null, 2)
  form.is_default = row.is_default
  dialogOpen.value = true
}

function typeLabel(type: ComputeEngineType) {
  return type === 'duckdb' ? 'DuckDB' : 'SQL Server'
}

function capabilityText(row: ComputeEngineItem) {
  const aggregates = row.capabilities?.aggregates || []
  return aggregates.length ? aggregates.join(' · ') : '—'
}

async function submit() {
  if (!canSubmit.value) return
  saveError.value = ''
  saving.value = true
  try {
    const config = JSON.parse(form.config || '{}')
    if (editing.value) {
      await updateComputeEngine(form.engine_name, { config, is_default: form.is_default })
    } else {
      await createComputeEngine({
        engine_name: form.engine_name.trim(),
        engine_type: form.engine_type,
        credential_name: form.engine_type === 'sql_server' ? form.credential_name : null,
        runtime_user: form.engine_type === 'sql_server' ? form.runtime_user.trim() : null,
        config,
        is_default: form.is_default,
      })
    }
    ElMessage.success(editing.value ? '已更新' : '已创建并验证')
    dialogOpen.value = false
    await load()
  } catch (error: any) {
    saveError.value = errorText(error)
    ElMessage.error('保存失败，完整错误已显示在弹窗内')
    await load()
  } finally {
    saving.value = false
  }
}

async function makeDefault(row: ComputeEngineItem) {
  try {
    await setDefaultComputeEngine(row.engine_name)
    ElMessage.success('已设为默认')
    await load()
  } catch (error: any) {
    ElMessage.error('操作失败：' + errorText(error))
  }
}

async function test(row: ComputeEngineItem) {
  try {
    await testComputeEngine(row.engine_name)
    ElMessage.success(`计算引擎「${row.engine_name}」测试通过`)
  } catch (error: any) {
    ElMessage.error('测试失败：' + errorText(error))
  }
}

async function remove(row: ComputeEngineItem) {
  const detail = row.engine_type === 'sql_server' && row.runtime_user
    ? `删除计算引擎「${row.engine_name}」？目标数据库用户「${row.runtime_user}」也会被删除。`
    : `删除计算引擎「${row.engine_name}」？`
  try {
    await ElMessageBox.confirm(detail, '确认删除', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  try {
    await deleteComputeEngine(row.engine_name)
    ElMessage.success('已删除')
    await load()
  } catch (error: any) {
    ElMessage.error('删除失败：' + errorText(error))
  }
}
</script>

<style scoped>
.ce-page {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 24px 28px 34px;
  background: #f3f6fb;
}
.ce-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 18px;
  padding: 16px 20px;
  border: 1px solid #dfe6f0;
  border-radius: 14px;
  background: #fff;
  box-shadow: 0 8px 22px rgba(22, 43, 77, 0.05);
}
.ce-head h1 { margin: 0; color: #20314c; font-size: 20px; }
.ce-head p { margin: 6px 0 0; color: #667991; font-size: 13px; }
.head-actions { display: flex; align-items: center; gap: 8px; }
.ce-alert { margin-bottom: 14px; }
.ce-table { background: transparent; }
.engine-name { font-weight: 600; color: #20314c; }
.def-tag { margin-left: 8px; }
.caps { color: #667991; font-size: 11px; line-height: 1.5; }
.state-error {
  max-width: 220px;
  margin-top: 4px;
  overflow: hidden;
  color: #b84f4f;
  font-size: 10px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.field { margin-bottom: 14px; }
.field label { display: block; margin-bottom: 5px; color: #5a6b80; font-size: 12px; }
.check-field { margin-top: 2px; }
.hint { margin-top: 5px; color: #8a6f52; font-size: 11px; line-height: 1.5; }
.validation { margin-top: 4px; color: #c45656; font-size: 11px; }
.save-error { margin-top: 14px; }
.save-error :deep(.el-alert__description) {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  line-height: 1.55;
  user-select: text;
}
</style>
