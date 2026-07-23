<template>
  <div class="logs-page">
    <header class="page-head">
      <div>
        <h1>API 日志</h1>
        <p>查询后端与 BFF 的请求状态、耗时、请求体、响应和错误堆栈。</p>
      </div>
      <el-button :loading="loading" @click="load">刷新</el-button>
    </header>

    <section class="filters">
      <el-input v-model="filter.keyword" clearable placeholder="路径 / 函数 / 用户 / 错误" class="f-keyword" @keyup.enter="search" />
      <el-select v-model="filter.state" clearable placeholder="状态" class="f-select">
        <el-option v-for="item in states" :key="item" :value="item" :label="item" />
      </el-select>
      <el-select v-model="filter.source" clearable placeholder="来源" class="f-select">
        <el-option value="backend" label="backend" />
        <el-option value="bff" label="bff" />
      </el-select>
      <el-input v-model="filter.user" clearable placeholder="用户" class="f-user" @keyup.enter="search" />
      <el-input v-model="filter.function" clearable placeholder="函数" class="f-user" @keyup.enter="search" />
      <el-date-picker
        v-model="filter.range"
        type="datetimerange"
        value-format="YYYY-MM-DDTHH:mm:ss"
        start-placeholder="开始时间"
        end-placeholder="结束时间"
        range-separator="至"
        class="f-range"
      />
      <el-button type="primary" @click="search">查询</el-button>
      <el-button @click="reset">重置</el-button>
    </section>

    <section class="table-card">
      <el-table v-loading="loading" :data="items" height="100%" empty-text="暂无日志" @row-dblclick="openDetail">
        <el-table-column prop="id" label="ID" width="82" />
        <el-table-column label="时间" width="172">
          <template #default="{ row }">{{ fmt(row.request_time) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="105">
          <template #default="{ row }">
            <el-tag :type="stateType(row.state)" size="small" effect="plain">{{ row.state || '—' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="source" label="来源" width="92" />
        <el-table-column prop="method" label="方法" width="82" />
        <el-table-column prop="function_name" label="函数" min-width="150" show-overflow-tooltip />
        <el-table-column prop="path" label="路径" min-width="230" show-overflow-tooltip />
        <el-table-column prop="user_name" label="用户" min-width="190" show-overflow-tooltip />
        <el-table-column label="耗时" width="95" align="right">
          <template #default="{ row }">{{ formatCost(row.cost_ms) }}</template>
        </el-table-column>
        <el-table-column label="错误" width="70" align="center">
          <template #default="{ row }"><span v-if="row.has_message" class="error-dot" title="包含错误信息"></span></template>
        </el-table-column>
        <el-table-column label="操作" width="76" fixed="right" align="right">
          <template #default="{ row }"><el-button link type="primary" @click.stop="openDetail(row)">详情</el-button></template>
        </el-table-column>
      </el-table>
    </section>

    <footer class="pager">
      <span>共 {{ total }} 条</span>
      <el-pagination
        v-model:current-page="page"
        v-model:page-size="pageSize"
        :page-sizes="[20, 50, 100]"
        :total="total"
        layout="sizes, prev, pager, next"
        @change="load"
      />
    </footer>

    <el-drawer v-model="drawer" title="API 日志详情" size="62%" destroy-on-close>
      <div v-loading="detailLoading" class="detail">
        <el-descriptions v-if="detail" :column="2" border size="small">
          <el-descriptions-item label="ID">{{ detail.id }}</el-descriptions-item>
          <el-descriptions-item label="状态"><el-tag :type="stateType(detail.state)" size="small">{{ detail.state }}</el-tag></el-descriptions-item>
          <el-descriptions-item label="时间">{{ fmt(detail.request_time) }}</el-descriptions-item>
          <el-descriptions-item label="耗时">{{ formatCost(detail.cost_ms) }}</el-descriptions-item>
          <el-descriptions-item label="来源">{{ detail.source || '—' }}</el-descriptions-item>
          <el-descriptions-item label="用户">{{ detail.user_name || '—' }}</el-descriptions-item>
          <el-descriptions-item label="函数">{{ detail.function_name || '—' }}</el-descriptions-item>
          <el-descriptions-item label="方法 / 路径">{{ detail.method }} {{ detail.path }}</el-descriptions-item>
        </el-descriptions>

        <template v-if="detail">
          <div v-for="block in detailBlocks" :key="block.key" class="detail-block" :class="{ error: block.key === 'message' }">
            <div class="db-head">
              <b>{{ block.label }}</b>
              <el-button link size="small" @click="copy(block.value)">复制</el-button>
            </div>
            <pre>{{ pretty(block.value) }}</pre>
          </div>
        </template>
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { getApiLog, getApiLogs, type ApiLogDetail, type ApiLogListItem } from '../bff/ApiLogs.js'

const states = ['success', 'error', 'failed', 'denied', 'unauthorized']
const filter = reactive<{
  keyword: string
  state: string
  source: string
  user: string
  function: string
  range: [string, string] | null
}>({ keyword: '', state: '', source: '', user: '', function: '', range: null })

const items = ref<ApiLogListItem[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(50)
const loading = ref(false)
const drawer = ref(false)
const detailLoading = ref(false)
const detail = ref<ApiLogDetail | null>(null)

const detailBlocks = computed(() => detail.value ? [
  { key: 'payload', label: '请求 Payload', value: detail.value.payload || '' },
  { key: 'response', label: '响应', value: detail.value.response || '' },
  { key: 'message', label: '错误 / 堆栈', value: detail.value.message || '' },
].filter((item) => item.value) : [])

function errorText(error: any): string {
  return error?.response?.data?.message || error?.message || String(error)
}

async function load() {
  loading.value = true
  try {
    const result = await getApiLogs({
      page: page.value,
      pageSize: pageSize.value,
      state: filter.state || undefined,
      source: filter.source || undefined,
      user: filter.user.trim() || undefined,
      function: filter.function.trim() || undefined,
      keyword: filter.keyword.trim() || undefined,
      from: filter.range?.[0],
      to: filter.range?.[1],
    })
    items.value = result.items
    total.value = result.total
  } catch (error: any) {
    ElMessage.error('日志加载失败：' + errorText(error))
  } finally {
    loading.value = false
  }
}

function search() {
  page.value = 1
  load()
}

function reset() {
  filter.keyword = ''
  filter.state = ''
  filter.source = ''
  filter.user = ''
  filter.function = ''
  filter.range = null
  search()
}

async function openDetail(row: ApiLogListItem) {
  drawer.value = true
  detail.value = null
  detailLoading.value = true
  try {
    detail.value = await getApiLog(row.id)
  } catch (error: any) {
    ElMessage.error('详情加载失败：' + errorText(error))
  } finally {
    detailLoading.value = false
  }
}

function stateType(state: string | null) {
  if (state === 'success') return 'success'
  if (state === 'denied' || state === 'unauthorized') return 'warning'
  if (state === 'error' || state === 'failed') return 'danger'
  return 'info'
}

function fmt(value: string | null) {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false })
}

function formatCost(value: number | null) {
  if (value == null) return '—'
  return value < 1000 ? `${value} ms` : `${(value / 1000).toFixed(2)} s`
}

function pretty(value: string) {
  try { return JSON.stringify(JSON.parse(value), null, 2) } catch { return value }
}

async function copy(value: string) {
  try {
    await navigator.clipboard.writeText(value)
    ElMessage.success('已复制')
  } catch {
    ElMessage.error('复制失败')
  }
}

onMounted(load)
</script>

<style scoped>
.logs-page { flex:1; min-height:0; display:flex; flex-direction:column; gap:14px; padding:22px 26px; background:#f2f6fb; }
.page-head { display:flex; align-items:flex-start; justify-content:space-between; gap:16px; }
.page-head h1 { margin:0; color:#20314c; font-size:20px; }
.page-head p { margin:6px 0 0; color:#6c7f94; font-size:13px; }
.filters { display:flex; align-items:center; flex-wrap:wrap; gap:9px; padding:13px 14px; border:1px solid #dfe7f0; border-radius:12px; background:#fff; box-shadow:0 5px 16px rgba(30,52,80,.04); }
.f-keyword { width:230px; }.f-select { width:120px; }.f-user { width:155px; }.f-range { width:340px !important; }
.table-card { flex:1; min-height:220px; overflow:hidden; border:1px solid #dfe7f0; border-radius:12px; background:#fff; box-shadow:0 8px 22px rgba(30,52,80,.05); }
.error-dot { display:inline-block; width:8px; height:8px; border-radius:50%; background:#d95757; box-shadow:0 0 0 3px rgba(217,87,87,.12); }
.pager { display:flex; align-items:center; justify-content:space-between; min-height:34px; color:#73869b; font-size:12px; }
.detail { min-height:160px; }
.detail-block { margin-top:16px; }
.db-head { display:flex; align-items:center; justify-content:space-between; color:#52677f; font-size:12px; }
.detail-block pre { max-height:360px; margin:6px 0 0; overflow:auto; padding:12px 14px; border:1px solid #dce6f0; border-radius:9px; background:#f5f8fc; color:#29445f; font:12px/1.55 'Cascadia Code',Consolas,monospace; white-space:pre-wrap; overflow-wrap:anywhere; user-select:text; }
.detail-block.error pre { border-color:#efcaca; background:#fff5f5; color:#9c3030; }
@media (max-width:900px) { .logs-page{padding:16px}.f-range{width:100%!important}.f-keyword{flex:1;min-width:220px} }
</style>
