<script setup lang="ts">
import { computed } from 'vue'
import { renderMarkdown } from '../utils/markdown'

const props = defineProps<{
  content: string
}>()

const html = computed(() => renderMarkdown(props.content))
</script>

<template>
  <!-- renderMarkdown escapes source HTML before adding its own safe markup. -->
  <div class="markdown-body" v-html="html" />
</template>

<style scoped>
.markdown-body {
  min-width: 0;
  overflow-wrap: anywhere;
}

.markdown-body :deep(h1),
.markdown-body :deep(h2),
.markdown-body :deep(h3),
.markdown-body :deep(h4) {
  margin: 1.15em 0 0.55em;
  color: #1d3577;
  line-height: 1.28;
  letter-spacing: -0.02em;
}

.markdown-body :deep(h1:first-child),
.markdown-body :deep(h2:first-child),
.markdown-body :deep(h3:first-child) {
  margin-top: 0;
}

.markdown-body :deep(h1) { font-size: 1.32em; }
.markdown-body :deep(h2) {
  padding-bottom: 0.32em;
  border-bottom: 1px solid rgba(77, 107, 254, 0.14);
  font-size: 1.18em;
}
.markdown-body :deep(h3) { font-size: 1.08em; }
.markdown-body :deep(h4) { font-size: 1em; }

.markdown-body :deep(p) {
  margin: 0.62em 0;
}

.markdown-body :deep(ul),
.markdown-body :deep(ol) {
  margin: 0.58em 0;
  padding-left: 1.35em;
}

.markdown-body :deep(li) {
  margin: 0.28em 0;
  padding-left: 0.12em;
}

.markdown-body :deep(li::marker) {
  color: #4d6bfe;
}

.markdown-body :deep(strong) {
  color: #18316f;
  font-weight: 760;
}

.markdown-body :deep(em) {
  color: #5068a6;
}

.markdown-body :deep(code) {
  padding: 0.12em 0.35em;
  border: 1px solid rgba(77, 107, 254, 0.14);
  border-radius: 5px;
  color: #3154c7;
  background: rgba(77, 107, 254, 0.07);
  font-family: inherit;
  font-size: 0.9em;
}

.markdown-body :deep(pre) {
  overflow-x: auto;
  margin: 0.7em 0;
  padding: 10px;
  border: 1px solid rgba(77, 107, 254, 0.12);
  border-radius: 9px;
  background: rgba(237, 242, 255, 0.82);
}

.markdown-body :deep(pre code) {
  padding: 0;
  border: 0;
  background: transparent;
}

.markdown-body :deep(blockquote) {
  margin: 0.7em 0;
  padding: 0.45em 0.8em;
  border-left: 2px solid #4d6bfe;
  color: rgba(32, 53, 104, 0.68);
  background: rgba(77, 107, 254, 0.06);
}

.markdown-body :deep(.markdown-table-wrap) {
  overflow-x: auto;
  margin: 0.75em 0;
  border: 1px solid rgba(77, 107, 254, 0.12);
  border-radius: 9px;
}

.markdown-body :deep(table) {
  width: 100%;
  min-width: 430px;
  border-collapse: collapse;
  background: rgba(248, 250, 255, 0.78);
  font-size: 0.92em;
}

.markdown-body :deep(th),
.markdown-body :deep(td) {
  padding: 7px 8px;
  border-right: 1px solid rgba(77, 107, 254, 0.09);
  border-bottom: 1px solid rgba(77, 107, 254, 0.09);
  text-align: left;
  vertical-align: top;
}

.markdown-body :deep(th) {
  color: #1d3577;
  background: rgba(77, 107, 254, 0.09);
  white-space: nowrap;
}

.markdown-body :deep(tr:last-child td) { border-bottom: 0; }
.markdown-body :deep(th:last-child),
.markdown-body :deep(td:last-child) { border-right: 0; }
</style>
