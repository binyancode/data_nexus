<template>
  <div class="ask-console">
    <div class="ask-scroll">
      <!-- 提问区 -->
      <section class="ask-hero">
        <h1 class="ask-title">你想问什么？</h1>
        <p class="ask-subtitle">用自然语言提问，看 Data Nexus 怎么一步步把答案算出来。</p>

        <div class="ask-box">
          <el-input
            v-model="question"
            type="textarea"
            :rows="3"
            resize="none"
            placeholder="例如：华东上季度毛利是多少？"
            @keydown.enter.exact.prevent="onAsk"
          />
          <div class="ask-actions">
            <div class="ask-onto">
              <span class="ao-label">本体</span>
              <el-select v-model="ontologyId" size="small" placeholder="自动" class="ao-sel">
                <el-option value="" label="自动（智能路由）" />
                <el-option v-for="o in ontologies" :key="o.ontologyId" :value="o.ontologyId" :label="o.name" />
              </el-select>
            </div>
            <span class="ask-hint">Enter 提问 · Shift+Enter 换行</span>
            <el-button type="primary" :loading="loading" :disabled="!question.trim()" @click="onAsk">
              提问
            </el-button>
          </div>
        </div>

        <div class="ask-examples">
          <span class="examples-label">试试：</span>
          <el-tag
            v-for="ex in examples"
            :key="ex"
            class="example-tag"
            effect="plain"
            round
            @click="useExample(ex)"
          >
            {{ ex }}
          </el-tag>
        </div>
      </section>

      <!-- 回答区（运行完成后显示） -->
      <section v-if="answerText" class="answer-panel">
        <div class="answer-head">
          <el-icon class="answer-icon"><Opportunity /></el-icon>
          <span class="answer-label">答案</span>
        </div>
        <p class="answer-text">{{ answerText }}</p>

        <div class="lineage-grid">
          <div v-for="(item, i) in lineage" :key="i" class="lineage-card">
            <div class="lineage-name">{{ item.label }}</div>
            <div class="lineage-value">{{ item.value }}</div>
            <div class="lineage-source">
              <el-icon><Coin /></el-icon>{{ item.source }}
            </div>
          </div>
        </div>
      </section>

      <!-- 执行过程（四段引擎 + SQG/执行图，提问后立即展示并实时刷新） -->
      <section v-if="runId" class="runtime-panel">
        <div class="runtime-title">分析执行过程</div>
        <NexusRuntime :run-id="runId" :question="lastQuestion" @done="onRuntimeDone" />
      </section>

      <!-- 空状态 -->
      <section v-if="!runId && !answerText" class="empty-state">
        <el-icon class="empty-icon"><ChatLineRound /></el-icon>
        <p>提问后，这里会显示分析执行过程与答案。</p>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { ask } from '../backend/Ask.js'
import { listOntologies, type OntologyMeta } from '../bff/Ontology.js'
import NexusRuntime from './runtime/NexusRuntime.vue'
import type { RuntimeAnswer } from './runtime/dag'

interface Cell {
  label: string
  value: string
  source: string
}

const question = ref('')
const loading = ref(false)
const answerText = ref('')
const lineage = ref<Cell[]>([])
const runId = ref<string | null>(null)
const lastQuestion = ref('')
const ontologyId = ref('')
const ontologies = ref<OntologyMeta[]>([])

onMounted(async () => {
  try { ontologies.value = await listOntologies() } catch { /* ignore */ }
})

const examples = [
  '华东上季度毛利',
  '华南2024Q1毛利',
  '华北去年销售额',
]

function useExample(ex: string) {
  question.value = ex
  onAsk()
}

// 异步提问：立即拿 run_id 并展示执行过程；答案由 NexusRuntime 完成时回传
async function onAsk() {
  const q = question.value.trim()
  if (!q || loading.value) return
  loading.value = true
  answerText.value = ''
  lineage.value = []
  runId.value = null
  lastQuestion.value = q
  try {
    const res = await ask(q, ontologyId.value || null)
    runId.value = res.run_id
  } catch (e: any) {
    ElMessage.error('提问失败：' + (e?.message || e))
  } finally {
    loading.value = false
  }
}

function onRuntimeDone(a: RuntimeAnswer) {
  answerText.value = a.text
  lineage.value = (a.lineage || []).map((li) => ({
    label: li.label,
    value: li.value == null ? '—' : String(li.value),
    source: li.source,
  }))
}
</script>

<style scoped>
.ask-console {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}

.ask-scroll {
  max-width: 920px;
  margin: 0 auto;
  padding: 44px 24px 72px;
}

.ask-hero {
  text-align: center;
}

.ask-title {
  font-size: 28px;
  font-weight: 600;
  color: var(--beone-text-primary);
  margin-bottom: 8px;
}

.ask-subtitle {
  font-size: 14px;
  color: var(--beone-text-secondary);
  margin-bottom: 28px;
}

.ask-box {
  background: var(--beone-bg-panel);
  border: 1px solid var(--beone-border);
  border-radius: 14px;
  padding: 16px;
  box-shadow: 0 10px 30px rgba(40, 51, 74, 0.1);
  text-align: left;
  transition: box-shadow 0.2s, border-color 0.2s;
}

.ask-box:focus-within {
  border-color: var(--beone-cerulean-blue);
  box-shadow: 0 0 0 3px rgba(0, 103, 127, 0.12), 0 12px 34px rgba(0, 103, 127, 0.14);
}

.ask-box :deep(.el-textarea__inner) {
  border: none;
  box-shadow: none;
  font-size: 15px;
  padding: 6px 8px;
  font-family: var(--beone-font-family);
}

.ask-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 8px;
  padding: 0 4px;
}

.ask-onto {
  display: flex;
  align-items: center;
  gap: 8px;
}

.ao-label {
  font-size: 12px;
  color: var(--beone-text-secondary);
  white-space: nowrap;
}

.ao-sel {
  width: 150px;
}

.ask-hint {
  font-size: 12px;
  color: var(--beone-text-secondary);
}

.ask-examples {
  display: flex;
  align-items: center;
  justify-content: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 18px;
}

.examples-label {
  font-size: 13px;
  color: var(--beone-text-secondary);
}

.example-tag {
  cursor: pointer;
}

.answer-panel {
  margin-top: 32px;
  position: relative;
  background: linear-gradient(180deg, #ffffff 0%, #fbfdff 100%);
  border: 1px solid var(--beone-border);
  border-radius: 14px;
  padding: 20px 22px;
  box-shadow: 0 10px 30px rgba(40, 51, 74, 0.08);
  overflow: hidden;
}

.answer-panel::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 4px;
  background: linear-gradient(180deg, var(--beone-cerulean-blue), var(--beone-autumn-leaf));
}

.answer-head {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 10px;
}

.answer-icon {
  color: var(--beone-autumn-leaf);
  font-size: 18px;
}

.answer-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--beone-text-secondary);
}

.answer-text {
  font-size: 16px;
  color: var(--beone-text-primary);
  margin-bottom: 18px;
}

.lineage-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 12px;
}

.lineage-card {
  border: 1px solid var(--beone-border);
  border-radius: 8px;
  padding: 12px 14px;
  background: var(--beone-bg-panel-muted);
}

.lineage-name {
  font-size: 13px;
  color: var(--beone-text-secondary);
}

.lineage-value {
  font-size: 20px;
  font-weight: 600;
  color: var(--beone-text-primary);
  margin: 4px 0;
}

.lineage-source {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: var(--beone-text-secondary);
}

.empty-state {
  margin-top: 60px;
  text-align: center;
  color: var(--beone-text-secondary);
}

.runtime-panel {
  margin-top: 28px;
}

.runtime-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--beone-text-primary);
  margin-bottom: 14px;
}

.empty-icon {
  font-size: 40px;
  color: var(--beone-border-strong);
  margin-bottom: 12px;
}
</style>
