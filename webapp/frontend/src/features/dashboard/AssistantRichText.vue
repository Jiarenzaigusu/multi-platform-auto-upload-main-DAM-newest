<script setup>
import { computed } from 'vue'
import { linkWorkNames } from './contentLinks.js'
import { formatAssistantAnswer } from './assistantLayout.js'

const props = defineProps({
  text: { type: String, default: '' },
  evidence: { type: Array, default: () => [] },
  contentType: { type: String, default: 'image' },
})

function inlineParts(line) {
  const parts = []
  const pattern = /(\*\*(.+?)\*\*|__(.+?)__|`([^`]+)`)/g
  let start = 0
  for (const match of line.matchAll(pattern)) {
    if (match.index > start) parts.push({ type: 'text', text: line.slice(start, match.index) })
    parts.push({ type: match[4] ? 'code' : 'strong', text: match[2] || match[3] || match[4] })
    start = match.index + match[0].length
  }
  if (start < line.length) parts.push({ type: 'text', text: line.slice(start) })
  return parts.flatMap(part => part.type === 'code' ? [part] : linkWorkNames(part.text, props.evidence, props.contentType).map(piece => ({ ...part, ...piece })))
}

const lines = computed(() => formatAssistantAnswer(props.text).split(/\r?\n/).filter((line) => line.trim()).map((line) => {
  const trimmed = line.trim()
  const heading = trimmed.match(/^#{1,3}\s+(.+)$/)
  const bullet = trimmed.match(/^[-*]\s+(.+)$/)
  const numbered = trimmed.match(/^\d+[.)]\s+(.+)$/)
  return {
    type: heading ? 'heading' : bullet || numbered ? 'item' : 'paragraph',
    parts: inlineParts(heading?.[1] || bullet?.[1] || numbered?.[1] || trimmed),
  }
}))
</script>

<template>
  <div class="assistant-rich-text">
    <div v-for="(line, index) in lines" :key="index" :class="`assistant-rich-${line.type}`"><span v-if="line.type === 'item'" class="assistant-rich-bullet" aria-hidden="true">•</span><template v-for="(part, partIndex) in line.parts" :key="partIndex"><a v-if="part.href" :href="part.href" target="_blank" rel="noopener noreferrer" :title="`打开作品：${part.text}`">{{ part.text }}</a><strong v-else-if="part.type === 'strong'">{{ part.text }}</strong><code v-else-if="part.type === 'code'">{{ part.text }}</code><template v-else>{{ part.text }}</template></template></div>
  </div>
</template>

<style scoped>
.assistant-rich-text { line-height: 1.75; overflow-wrap: anywhere; }
.assistant-rich-paragraph + .assistant-rich-paragraph, .assistant-rich-heading, .assistant-rich-item + .assistant-rich-paragraph { margin-top: 9px; }
.assistant-rich-heading { color: #294c42; font-weight: 750; }
.assistant-rich-item { padding-left: 15px; text-indent: -12px; }
.assistant-rich-bullet { margin-right: 6px; color: #83a456; }
strong { color: #294c42; font-weight: 750; }
a { color: inherit; font-weight: inherit; text-decoration: underline; text-underline-offset: 3px; }
a:hover { color: #648632; }
a:focus-visible { outline: 2px solid #83a456; outline-offset: 3px; }
code { padding: 1px 3px; border-radius: 3px; background: #f1f5e8; font: inherit; }
</style>
