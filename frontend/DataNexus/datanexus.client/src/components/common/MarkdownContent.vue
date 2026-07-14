<template>
  <div
    class="markdown-content"
    :class="{ compact }"
    v-html="html"
    @click="openExternalLink"
  />
</template>

<script setup lang="ts">
import { computed } from 'vue'
import DOMPurify from 'dompurify'
import { marked } from 'marked'

const props = withDefaults(defineProps<{ content: string; compact?: boolean }>(), {
  compact: false,
})

const html = computed(() => {
  const rendered = marked.parse(props.content || '', { gfm: true, breaks: true }) as string
  return DOMPurify.sanitize(rendered, {
    USE_PROFILES: { html: true },
    FORBID_TAGS: ['script', 'style', 'iframe', 'object', 'embed', 'form'],
    FORBID_ATTR: ['style', 'onerror', 'onclick', 'onload'],
  })
})

function openExternalLink(event: MouseEvent) {
  const target = event.target as HTMLElement | null
  const link = target?.closest('a') as HTMLAnchorElement | null
  if (!link?.href || !/^https?:\/\//i.test(link.href)) return
  event.preventDefault()
  window.open(link.href, '_blank', 'noopener,noreferrer')
}
</script>

<style scoped>
.markdown-content {
  min-width: 0;
  color: var(--beone-text-primary, #28334a);
  font-size: 14px;
  line-height: 1.7;
  overflow-wrap: anywhere;
  word-break: break-word;
}
.markdown-content :deep(> :first-child) { margin-top: 0; }
.markdown-content :deep(> :last-child) { margin-bottom: 0; }
.markdown-content :deep(h1),
.markdown-content :deep(h2),
.markdown-content :deep(h3),
.markdown-content :deep(h4) {
  color: var(--beone-text-primary, #28334a);
  line-height: 1.35;
  margin: 1.15em 0 .55em;
}
.markdown-content :deep(h1) { font-size: 1.45em; }
.markdown-content :deep(h2) { font-size: 1.28em; padding-bottom: .28em; border-bottom: 1px solid #e0e8f2; }
.markdown-content :deep(h3) { font-size: 1.12em; }
.markdown-content :deep(h4) { font-size: 1em; }
.markdown-content :deep(p) { margin: .55em 0; }
.markdown-content :deep(ul),
.markdown-content :deep(ol) { margin: .55em 0; padding-left: 1.5em; }
.markdown-content :deep(li) { margin: .2em 0; }
.markdown-content :deep(strong) { font-weight: 700; color: #17263c; }
.markdown-content :deep(a) { color: #087f96; text-decoration: none; }
.markdown-content :deep(a:hover) { text-decoration: underline; }
.markdown-content :deep(blockquote) {
  margin: .75em 0;
  padding: .55em .9em;
  color: #526b83;
  background: #f3f7fb;
  border-left: 3px solid #2d9fb3;
  border-radius: 0 6px 6px 0;
}
.markdown-content :deep(table) {
  width: 100%;
  margin: .75em 0 1em;
  border-collapse: separate;
  border-spacing: 0;
  border: 1px solid #d9e4ef;
  border-radius: 9px;
  overflow: hidden;
  font-size: .94em;
}
.markdown-content :deep(th),
.markdown-content :deep(td) {
  padding: 8px 11px;
  text-align: left;
  vertical-align: top;
  border-right: 1px solid #e3ebf3;
  border-bottom: 1px solid #e3ebf3;
  overflow-wrap: anywhere;
}
.markdown-content :deep(th:last-child),
.markdown-content :deep(td:last-child) { border-right: 0; }
.markdown-content :deep(tr:last-child td) { border-bottom: 0; }
.markdown-content :deep(th) {
  color: #314b65;
  font-weight: 650;
  background: #edf4fa;
  white-space: nowrap;
}
.markdown-content :deep(tbody tr:nth-child(even)) { background: #f8fafc; }
.markdown-content :deep(tbody tr:hover) { background: #eef7f7; }
.markdown-content :deep(code) {
  padding: .12em .35em;
  color: #6f3f8f;
  background: #f2edf7;
  border-radius: 4px;
  font-family: 'Cascadia Code', Consolas, monospace;
  font-size: .9em;
}
.markdown-content :deep(pre) {
  margin: .75em 0;
  padding: 11px 13px;
  overflow-x: auto;
  color: #e6edf3;
  background: #17263c;
  border-radius: 8px;
}
.markdown-content :deep(pre code) { padding: 0; color: inherit; background: transparent; }
.markdown-content :deep(hr) { border: 0; border-top: 1px solid #dbe5ef; margin: 1em 0; }
.markdown-content.compact { font-size: 12.5px; line-height: 1.55; }
.markdown-content.compact :deep(table) { font-size: 11.5px; margin: .55em 0; }
.markdown-content.compact :deep(th),
.markdown-content.compact :deep(td) { padding: 5px 7px; }
</style>
