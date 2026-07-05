<template>
  <pre class="jsonv" v-html="html"></pre>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ value: unknown }>()

function esc(s: string) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

const html = computed(() => {
  let json: string
  try {
    json = JSON.stringify(props.value, null, 2)
  } catch {
    json = String(props.value)
  }
  return esc(json).replace(
    /("(\\u[a-zA-Z0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+-]?\d+)?)/g,
    (m) => {
      let cls = 'jv-num'
      if (/^"/.test(m)) cls = /:$/.test(m) ? 'jv-key' : 'jv-str'
      else if (/true|false/.test(m)) cls = 'jv-bool'
      else if (/null/.test(m)) cls = 'jv-null'
      return `<span class="${cls}">${m}</span>`
    },
  )
})
</script>

<style scoped>
.jsonv {
  margin: 0;
  padding: 14px 16px;
  border-radius: 10px;
  background: #0e1b2c;
  border: 1px solid var(--tech-border, #1e3550);
  color: #cdd9e5;
  font-family: 'Cascadia Code', Consolas, monospace;
  font-size: 12.5px;
  line-height: 1.6;
  overflow: auto;
  white-space: pre;
}
.jsonv :deep(.jv-key) { color: #7fd6e6; }
.jsonv :deep(.jv-str) { color: #9be59b; }
.jsonv :deep(.jv-num) { color: #f0b666; }
.jsonv :deep(.jv-bool) { color: #e991c2; }
.jsonv :deep(.jv-null) { color: #8ba2b8; }
</style>
