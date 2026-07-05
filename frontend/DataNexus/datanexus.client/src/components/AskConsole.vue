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

      <!-- 回答区 -->
      <section v-if="answered" class="answer-panel">
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

      <!-- 空状态 -->
      <section v-else class="empty-state">
        <el-icon class="empty-icon"><ChatLineRound /></el-icon>
        <p>提问后，这里会显示答案与每个数字的来源。</p>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { ask } from '../backend/Ask.js'

interface Cell {
  label: string
  value: string
  source: string
}

const question = ref('')
const loading = ref(false)
const answered = ref(false)
const answerText = ref('')
const lineage = ref<Cell[]>([])

const examples = [
  '华东上季度毛利',
  '华南2024Q1毛利',
  '华北去年销售额',
]

function useExample(ex: string) {
  question.value = ex
  onAsk()
}

// 直连后端 POST {BaseUrl}/v1/ask（service 带 Bearer → 测 token 到后端的认证）
async function onAsk() {
  const q = question.value.trim()
  if (!q || loading.value) return
  loading.value = true
  answered.value = false
  try {
    const res = await ask(q)
    answerText.value = res.answer
    lineage.value = (res.lineage || []).map((li) => ({
      label: li.label,
      value: li.value == null ? '—' : String(li.value),
      source: li.source,
    }))
    answered.value = true
  } catch (e: any) {
    ElMessage.error('提问失败：' + (e?.message || e))
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.ask-console {
  flex: 1;
  min-height: 0;
  display: flex;
  justify-content: center;
  overflow: hidden;
}

.ask-scroll {
  width: 100%;
  max-width: 860px;
  height: 100%;
  overflow-y: auto;
  padding: 40px 24px 60px;
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
  border-radius: 12px;
  padding: 14px;
  box-shadow: var(--beone-shadow-panel);
  text-align: left;
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
  background: var(--beone-bg-panel);
  border: 1px solid var(--beone-border);
  border-radius: 12px;
  padding: 20px 22px;
  box-shadow: var(--beone-shadow-panel);
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

.empty-icon {
  font-size: 40px;
  color: var(--beone-border-strong);
  margin-bottom: 12px;
}
</style>
