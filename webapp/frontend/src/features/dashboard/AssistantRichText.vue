<script setup>
import { computed } from 'vue'

const props = defineProps({ text: { type: String, default: '' } })

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
  return parts
}

const lines = computed(() => props.text.split(/\r?\n/).filter((line) => line.trim()).map((line) => {
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
    <div v-for="(line, index) in lines" :key="index" :class="`assistant-rich-${line.type}`"><span v-if="line.type === 'item'" class="assistant-rich-bullet" aria-hidden="true">•</span><template v-for="(part, partIndex) in line.parts" :key="partIndex"><strong v-if="part.type === 'strong'">{{ part.text }}</strong><code v-else-if="part.type === 'code'">{{ part.text }}</code><template v-else>{{ part.text }}</template></template></div>
  </div>
</template>

<style scoped>
.assistant-rich-text { line-height: 1.75; overflow-wrap: anywhere; }
.assistant-rich-paragraph + .assistant-rich-paragraph, .assistant-rich-heading { margin-top: 9px; }
.assistant-rich-heading { color: #294c42; font-weight: 750; }
.assistant-rich-item { padding-left: 15px; text-indent: -12px; }
.assistant-rich-bullet { margin-right: 6px; color: #83a456; }
strong { color: #294c42; font-weight: 750; }
code { padding: 1px 3px; border-radius: 3px; background: #f1f5e8; font: inherit; }
</style>
