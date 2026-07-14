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
              <span class="ao-label">模型</span>
              <el-select v-model="llmName" size="small" placeholder="默认" class="ao-sel">
                <el-option value="" label="默认" />
                <el-option v-for="l in llms" :key="l.llm_name" :value="l.llm_name"
                           :label="l.is_default ? l.llm_name + '（默认）' : l.llm_name" />
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
        <MarkdownContent class="answer-text" :content="answerText" />

        <div class="lineage-grid">
          <div
            v-for="(item, i) in lineage"
            :key="i"
            class="lineage-card"
            :class="{ expanded: expandedLineage === i }"
            tabindex="0"
            role="button"
            :aria-expanded="expandedLineage === i"
            @click="toggleLineage(i)"
            @keydown.enter.prevent="toggleLineage(i)"
            @keydown.space.prevent="toggleLineage(i)"
          >
            <button
              class="lineage-toggle"
              type="button"
              :title="expandedLineage === i ? '收起完整信息' : '展开完整信息'"
              @click.stop="toggleLineage(i)"
            >{{ expandedLineage === i ? '收起' : '展开' }}</button>
            <div class="lineage-name" :title="item.label">{{ item.label }}</div>
            <MarkdownContent
              v-if="!sameLineageUrl(item) && hasMarkdown(item.value)"
              class="lineage-value lineage-markdown"
              :content="item.value"
              compact
            />
            <div v-else-if="!sameLineageUrl(item)" class="lineage-value" :class="{ 'is-url': isUrl(item.value) }">
              <a v-if="isUrl(item.value)" :href="item.value" target="_blank" rel="noopener noreferrer" @click.stop>{{ item.value }}</a>
              <template v-else>{{ item.value }}</template>
            </div>
            <div v-if="item.detail" class="lineage-detail">{{ item.detail }}</div>
            <div class="lineage-source">
              <el-icon><Coin /></el-icon>
              <a v-if="isUrl(item.source)" :href="item.source" target="_blank" rel="noopener noreferrer" @click.stop>{{ item.source }}</a>
              <span v-else>{{ item.source }}</span>
            </div>
          </div>
        </div>
      </section>

      <!-- 执行过程（四段引擎 + SQG/执行图，提问后立即展示并实时刷新） -->
      <section v-if="runId" class="runtime-panel">
        <div class="runtime-title">分析执行过程</div>
        <NexusRuntime :run-id="runId" :question="lastQuestion" @done="onRuntimeDone" />
      </section>

      <!-- 初始化中（提交后到拿到 run_id 之间：正在做本体路由 / 建运行，可能较久） -->
      <section v-else-if="loading" class="init-state">
        <span class="init-spin"></span>
        <p class="init-title">正在初始化…</p>
        <p class="init-sub">选择本体、装配引擎并创建运行，请稍候。</p>
      </section>

      <!-- 预检查 / 提问失败（如本体不可用） -->
      <section v-else-if="askError" class="err-state">
        <el-icon class="err-icon"><WarningFilled /></el-icon>
        <p class="err-title">无法使用该本体</p>
        <p class="err-sub">{{ askError }}</p>
      </section>

      <!-- 空状态 -->
      <section v-if="!runId && !answerText && !loading && !askError" class="empty-state">
        <el-icon class="empty-icon"><ChatLineRound /></el-icon>
        <p>提问后，这里会显示分析执行过程与答案。</p>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ask } from '../backend/Ask.js'
import { listOntologies, type OntologyMeta } from '../bff/Ontology.js'
import { listLlms, type LlmItem } from '../bff/Llms.js'
import NexusRuntime from './runtime/NexusRuntime.vue'
import MarkdownContent from './common/MarkdownContent.vue'
import type { RuntimeAnswer } from './runtime/dag'

interface Cell {
  label: string
  value: string
  source: string
  detail: string
}

function isUrl(value: string): boolean {
  return /^https?:\/\//i.test(value || '')
}

function sameLineageUrl(item: Cell): boolean {
  return isUrl(item.value) && item.value === item.source
}

function hasMarkdown(value: string): boolean {
  return /(^|\n)\s*(#{1,6}\s|[-*+]\s|\d+\.\s|>\s|\|.+\||```)|\*\*[^*]+\*\*|__[^_]+__/m.test(value || '')
}

const question = ref('')
const loading = ref(false)
const answerText = ref('')
const lineage = ref<Cell[]>([])
const expandedLineage = ref<number | null>(null)
const runId = ref<string | null>(null)
const lastQuestion = ref('')
const askError = ref('')
const ontologyId = ref('')
const ontologies = ref<OntologyMeta[]>([])
const llmName = ref('')
const llms = ref<LlmItem[]>([])

onMounted(async () => {
  try { ontologies.value = await listOntologies() } catch { /* ignore */ }
  try { llms.value = await listLlms() } catch { /* ignore */ }
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

function toggleLineage(index: number) {
  expandedLineage.value = expandedLineage.value === index ? null : index
}

// 异步提问：立即拿 run_id 并展示执行过程；答案由 NexusRuntime 完成时回传
async function onAsk() {
  const q = question.value.trim()
  if (!q || loading.value) return
  loading.value = true
  answerText.value = ''
  lineage.value = []
  expandedLineage.value = null
  runId.value = null
  askError.value = ''
  lastQuestion.value = q
  try {
    const res = await ask(q, ontologyId.value || null, llmName.value || null)
    runId.value = res.run_id
  } catch (e: any) {
    askError.value = e?.message || String(e)
  } finally {
    loading.value = false
  }
}

function onRuntimeDone(a: RuntimeAnswer) {
  expandedLineage.value = null
  answerText.value = a.text
  lineage.value = (a.lineage || []).map((li) => ({
    label: li.label,
    value: li.value == null ? '—' : String(li.value),
    source: li.source,
    detail: li.detail || '',
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
  margin-bottom: 18px;
}

.lineage-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(min(240px, 100%), 1fr));
  gap: 12px;
}

.lineage-card {
  position: relative;
  min-width: 0;
  height: 190px;
  box-sizing: border-box;
  overflow: hidden;
  border: 1px solid var(--beone-border);
  border-radius: 8px;
  padding: 12px 38px 12px 14px;
  background: var(--beone-bg-panel-muted);
  transition: border-color .16s ease, box-shadow .16s ease, background .16s ease;
}
.lineage-card { cursor: pointer; }
.lineage-card:hover,
.lineage-card:focus-visible {
  border-color: color-mix(in srgb, var(--beone-cerulean-blue) 55%, var(--beone-border));
  box-shadow: 0 5px 14px rgba(26, 67, 105, .09);
  outline: none;
}
.lineage-card.expanded {
  grid-column: 1 / -1;
  height: auto;
  min-height: 190px;
  overflow: visible;
  background: var(--beone-bg-panel);
}
.lineage-toggle {
  position: absolute;
  top: 9px;
  right: 10px;
  border: 1px solid color-mix(in srgb, var(--beone-cerulean-blue) 28%, transparent);
  border-radius: 10px;
  padding: 1px 7px;
  background: color-mix(in srgb, var(--beone-cerulean-blue) 8%, #ffffff);
  color: var(--beone-cerulean-blue);
  font-size: 11px;
  line-height: 18px;
  cursor: pointer;
}
.lineage-toggle:hover { background: color-mix(in srgb, var(--beone-cerulean-blue) 14%, #ffffff); }

.lineage-name {
  font-size: 13px;
  color: var(--beone-text-secondary);
  line-height: 1.45;
  overflow-wrap: anywhere;
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  overflow: hidden;
}

.lineage-value {
  font-size: 20px;
  font-weight: 600;
  color: var(--beone-text-primary);
  margin: 4px 0;
  overflow-wrap: anywhere;
  word-break: break-word;
  line-height: 1.4;
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
  line-clamp: 3;
  overflow: hidden;
}
.lineage-value.is-url { font-size: 14px; line-height: 1.45; }
.lineage-value.lineage-markdown {
  display: block;
  max-height: 84px;
  font-size: 12px;
  font-weight: 400;
  overflow: hidden;
}
.lineage-value a, .lineage-source a { color: inherit; text-decoration: none; }
.lineage-value a:hover, .lineage-source a:hover { text-decoration: underline; }

.lineage-detail {
  margin: 7px 0;
  color: var(--beone-text-secondary);
  font-size: 12px;
  line-height: 1.5;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  word-break: break-word;
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 4;
  line-clamp: 4;
  overflow: hidden;
}

.lineage-source {
  display: flex;
  align-items: flex-start;
  gap: 4px;
  font-size: 12px;
  color: var(--beone-text-secondary);
  min-width: 0;
  line-height: 1.45;
}
.lineage-source .el-icon { flex: 0 0 auto; margin-top: 2px; }
.lineage-source a, .lineage-source span {
  min-width: 0;
  overflow-wrap: anywhere;
  word-break: break-word;
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  overflow: hidden;
}
.lineage-card.expanded .lineage-name,
.lineage-card.expanded .lineage-value,
.lineage-card.expanded .lineage-detail,
.lineage-card.expanded .lineage-source a,
.lineage-card.expanded .lineage-source span {
  display: block;
  overflow: visible;
  -webkit-line-clamp: unset;
  line-clamp: unset;
}
.lineage-card.expanded .lineage-markdown { max-height: none; }

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

.init-state {
  margin-top: 60px;
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
}
.init-spin {
  width: 30px;
  height: 30px;
  border-radius: 50%;
  border: 3px solid rgba(47, 125, 188, 0.18);
  border-top-color: var(--beone-cerulean-blue);
  animation: init-rotate 0.8s linear infinite;
  margin-bottom: 8px;
}
@keyframes init-rotate { to { transform: rotate(360deg); } }
.init-title { font-size: 15px; font-weight: 600; color: var(--beone-text-primary); margin: 0; }
.init-sub { font-size: 13px; color: var(--beone-text-secondary); margin: 0; }

.err-state {
  margin-top: 60px;
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
}
.err-icon { font-size: 40px; color: #e0736a; margin-bottom: 6px; }
.err-title { font-size: 15px; font-weight: 600; color: #b23b32; margin: 0; }
.err-sub { font-size: 13px; color: #8a6d6a; margin: 0; max-width: 520px; line-height: 1.6; }
</style>

