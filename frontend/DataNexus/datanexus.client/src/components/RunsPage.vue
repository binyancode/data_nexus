<template>
  <div class="runs-page">
    <aside class="runs-list">
      <div class="rl-head">
        <span>运行历史</span>
        <button class="rl-refresh" :disabled="loading" @click="load" title="刷新">⟳</button>
      </div>
      <div v-if="loading && !runs.length" class="rl-empty">加载中…</div>
      <div v-else-if="!runs.length" class="rl-empty">暂无运行记录</div>
      <ul v-else class="rl-items">
        <li
          v-for="r in runs"
          :key="r.run_id"
          class="rl-item"
          :class="{ active: r.run_id === selectedRunId }"
          @click="selectedRunId = r.run_id"
        >
          <div class="rl-q">
            <span class="rl-text">{{ r.question || '（无问题）' }}</span>
          </div>
          <div class="rl-meta">
            <span>{{ fmt(r.created_at) }}</span>
            <span v-if="r.cost_ms">· {{ r.cost_ms }} ms</span>
          </div>
        </li>
      </ul>
    </aside>

    <section class="runs-detail">
      <NexusRuntime v-if="selectedRunId" :run-id="selectedRunId" />
      <div v-else class="rd-empty">
        <el-icon class="rd-icon"><Histogram /></el-icon>
        <p>选择左侧一条运行记录，查看它的分析执行过程。</p>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { getRuns, type RunListItem } from '../bff/Runs.js'
import NexusRuntime from './runtime/NexusRuntime.vue'

const runs = ref<RunListItem[]>([])
const loading = ref(false)
const selectedRunId = ref<string | null>(null)

async function load() {
  loading.value = true
  try {
    runs.value = await getRuns(50)
    if (!selectedRunId.value && runs.value.length) selectedRunId.value = runs.value[0]!.run_id
  } finally {
    loading.value = false
  }
}
function fmt(s: string | null) {
  if (!s) return ''
  const d = new Date(s)
  return isNaN(d.getTime()) ? s : d.toLocaleString('zh-CN', { hour12: false })
}

onMounted(load)
</script>

<style scoped>
.runs-page {
  flex: 1;
  min-height: 0;
  display: flex;
  overflow: hidden;
  padding: 14px;
  gap: 0;
  background: #f1f4fa;
}
.runs-list {
  width: 300px;
  flex: 0 0 auto;
  border: 1px solid #d8e0ec;
  border-right: 0;
  border-radius: 12px 0 0 12px;
  background: #ffffff;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  box-shadow: 0 8px 20px rgba(17, 24, 39, 0.05);
}
.rl-head {
  display: flex; align-items: center; justify-content: space-between;
  height: 50px;
  padding: 0 16px;
  font-size: 13px;
  font-weight: 700;
  color: #102a43;
  border-bottom: 1px solid #e5eaf1;
  background: #f5f8fd;
}
.rl-refresh {
  border: 1px solid #d3dfec;
  background: #ffffff;
  cursor: pointer;
  width: 28px;
  height: 28px;
  border-radius: 7px;
  font-size: 14px;
  color: #5f748a;
}
.rl-refresh:hover { background: #f4f8fc; color: #3e556e; }
.rl-empty { padding: 20px 16px; color: #73879d; font-size: 13px; }
.rl-items { list-style: none; margin: 0; padding: 0; overflow-y: auto; }
.rl-item {
  position: relative;
  padding: 12px 14px 11px;
  cursor: pointer;
  border-bottom: 1px solid #eef2f6;
  transition: background .12s;
}
.rl-item:hover { background: #f7f9fc; }
.rl-item.active {
  background: #cdddf8;
  box-shadow: none !important;
  border-left: 0 !important;
  outline: none;
}
.rl-item.active::before {
  content: '';
  position: absolute;
  left: 0;
  top: 8px;
  bottom: 8px;
  width: 3px;
  border-radius: 0 3px 3px 0;
  background: #5f88b3;
}
.rl-q {
  font-size: 13px;
  color: #0f2942;
  display: flex;
  align-items: flex-start;
  gap: 7px;
  font-weight: 600;
  line-height: 1.45;
}
.rl-text {
  min-width: 0;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.rl-meta {
  margin-top: 5px;
  font-size: 10.5px;
  color: #4f647a;
  display: flex;
  gap: 6px;
  padding-left: 15px;
}
.runs-detail {
  flex: 1;
  min-width: 0;
  overflow-y: auto;
  padding: 18px 22px;
  border: 1px solid transparent;
  border-radius: 0 12px 12px 0;
  background: #f1f4fa;
  box-shadow: none;
}
.rd-empty {
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: #70849a;
  gap: 10px;
}
.rd-icon { font-size: 40px; color: #9db0c4; }

@media (max-width: 900px) {
  .runs-page { padding: 10px; }
  .runs-list { width: 260px; }
  .runs-detail { padding: 14px; }
}
</style>
