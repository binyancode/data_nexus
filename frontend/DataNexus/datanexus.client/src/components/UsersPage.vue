<template>
  <div class="users-page">
    <header class="page-head">
      <div>
        <h1>用户管理</h1>
        <p>管理允许登录 Data Nexus 的 Azure AD 用户及其管理员权限。</p>
      </div>
      <div class="head-actions">
        <el-button :loading="loading" @click="load">刷新</el-button>
        <el-button type="primary" @click="openCreate">＋ 新增用户</el-button>
      </div>
    </header>

    <el-table v-loading="loading" :data="items" class="users-table" empty-text="暂无用户">
      <el-table-column prop="user_name" label="登录账号" min-width="260">
        <template #default="{ row }">
          <span class="user-name">{{ row.user_name }}</span>
          <el-tag v-if="row.user_name === authState.userName" size="small" effect="plain" class="self-tag">当前用户</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="display_name" label="显示名称" min-width="180">
        <template #default="{ row }">{{ row.display_name || '—' }}</template>
      </el-table-column>
      <el-table-column label="权限" width="130">
        <template #default="{ row }">
          <el-tag :type="row.is_admin ? 'warning' : 'info'" effect="plain">{{ row.is_admin ? '管理员' : '普通用户' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="创建时间" width="190">
        <template #default="{ row }">{{ fmt(row.created_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="150" align="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
          <el-button link type="danger" @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialog" :title="editingId == null ? '新增用户' : '编辑用户'" width="480px" @closed="reset">
      <div class="field">
        <label>Azure AD 登录账号 <span>*</span></label>
        <el-input v-model="form.user_name" :disabled="editingId != null" maxlength="200" placeholder="user@domain.com" />
        <p v-if="editingId != null" class="field-hint">登录身份不可修改；如账号变化，请删除后重新新增。</p>
      </div>
      <div class="field">
        <label>显示名称</label>
        <el-input v-model="form.display_name" maxlength="200" placeholder="可选" />
      </div>
      <div class="field admin-field">
        <div>
          <label>管理员权限</label>
          <p>管理员可以浏览 API 日志并维护用户。</p>
        </div>
        <el-switch v-model="form.is_admin" />
      </div>
      <el-alert v-if="saveError" type="error" title="保存失败" :description="saveError" :closable="false" show-icon />
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" :disabled="!form.user_name.trim()" @click="submit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { authState, loadAuthState } from '../common/authState.js'
import { createUser, deleteUser, getUsers, updateUser, type AppUser } from '../bff/User.js'

const items = ref<AppUser[]>([])
const loading = ref(false)
const dialog = ref(false)
const saving = ref(false)
const saveError = ref('')
const editingId = ref<number | null>(null)
const originalUserName = ref('')
const form = reactive({ user_name: '', display_name: '', is_admin: false })

function errorText(error: any) {
  return error?.response?.data?.message || error?.message || String(error)
}

async function load() {
  loading.value = true
  try { items.value = await getUsers() }
  catch (error: any) { ElMessage.error('用户加载失败：' + errorText(error)) }
  finally { loading.value = false }
}

function reset() {
  editingId.value = null
  originalUserName.value = ''
  form.user_name = ''
  form.display_name = ''
  form.is_admin = false
  saveError.value = ''
}

function openCreate() {
  reset()
  dialog.value = true
}

function openEdit(row: AppUser) {
  reset()
  editingId.value = row.id
  originalUserName.value = row.user_name
  form.user_name = row.user_name
  form.display_name = row.display_name || ''
  form.is_admin = row.is_admin
  dialog.value = true
}

async function submit() {
  saving.value = true
  saveError.value = ''
  const payload = {
    user_name: form.user_name.trim(),
    display_name: form.display_name.trim() || null,
    is_admin: form.is_admin,
  }
  try {
    if (editingId.value == null) await createUser(payload)
    else await updateUser(editingId.value, payload)
    const changedSelf = originalUserName.value === authState.userName || payload.user_name === authState.userName
    ElMessage.success(editingId.value == null ? '用户已创建' : '用户已更新')
    dialog.value = false
    await load()
    if (changedSelf) await loadAuthState()
  } catch (error: any) {
    saveError.value = errorText(error)
  } finally {
    saving.value = false
  }
}

async function remove(row: AppUser) {
  const message = row.user_name === authState.userName
    ? `删除当前登录用户「${row.user_name}」后，后续请求将无法通过登录白名单。确认删除？`
    : `删除用户「${row.user_name}」？`
  try {
    await ElMessageBox.confirm(message, '确认删除', {
      type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消',
    })
  } catch { return }
  try {
    await deleteUser(row.id)
    ElMessage.success('用户已删除')
    await load()
    if (row.user_name === authState.userName) await loadAuthState()
  } catch (error: any) {
    ElMessage.error('删除失败：' + errorText(error))
  }
}

function fmt(value: string | null) {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false })
}

onMounted(load)
</script>

<style scoped>
.users-page { flex:1; min-height:0; overflow-y:auto; padding:24px 28px 34px; background:#f3f6fb; }
.page-head { display:flex; align-items:flex-start; justify-content:space-between; gap:16px; margin-bottom:18px; padding:16px 20px; border:1px solid #dfe6f0; border-radius:14px; background:#fff; box-shadow:0 8px 22px rgba(22,43,77,.05); }
.page-head h1 { margin:0; color:#20314c; font-size:20px; }
.page-head p { margin:6px 0 0; color:#667991; font-size:13px; }
.head-actions { display:flex; gap:8px; }
.users-table { background:transparent; }
.user-name { color:#20314c; font-weight:600; }
.self-tag { margin-left:8px; }
.field { margin-bottom:15px; }
.field label { display:block; margin-bottom:5px; color:#52677f; font-size:12px; font-weight:600; }
.field label span { color:#cf5555; }
.field-hint { margin:4px 0 0; color:#8a99aa; font-size:11px; }
.admin-field { display:flex; align-items:center; justify-content:space-between; gap:20px; padding:12px 14px; border:1px solid #e0e8f1; border-radius:10px; background:#f7f9fc; }
.admin-field label { margin:0; }
.admin-field p { margin:4px 0 0; color:#8291a2; font-size:11px; }
</style>
