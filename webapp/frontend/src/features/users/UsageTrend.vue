<script setup>
import { computed, ref, useId } from 'vue'

const props = defineProps({
  rows: { type: Array, required: true },
  metric: { type: String, required: true },
  label: { type: String, required: true },
  color: { type: String, default: '#336655' },
})
const gradientId = `usage-spark-${useId()}`
const hovered = ref(null)
const number = value => new Intl.NumberFormat('zh-CN').format(value)
const max = computed(() => Math.max(1, ...props.rows.map(row => row[props.metric])))
const points = computed(() => props.rows.map((row, index) => ({
  x: props.rows.length === 1 ? 150 : 3 + index * 294 / (props.rows.length - 1),
  y: 68 - row[props.metric] * 58 / max.value,
  date: row.date,
  value: row[props.metric],
})))
const line = computed(() => points.value.map(point => `${point.x},${point.y}`).join(' '))
const activePoint = computed(() => hovered.value == null ? null : points.value[hovered.value])
function inspect(event) {
  const bounds = event.currentTarget.getBoundingClientRect()
  const fraction = Math.max(0, Math.min(1, (event.clientX - bounds.left) / Math.max(1, bounds.width)))
  hovered.value = Math.round(fraction * Math.max(0, props.rows.length - 1))
}
function move(direction) {
  hovered.value = Math.max(0, Math.min(props.rows.length - 1, (hovered.value ?? props.rows.length - 1) + direction))
}
</script>

<template>
  <div class="usage-sparkline">
    <div v-if="activePoint" class="spark-tooltip" role="status">{{ activePoint.date }} · {{ number(activePoint.value) }}</div>
    <svg viewBox="0 0 300 76" preserveAspectRatio="none" role="img" tabindex="0" :aria-label="`${label}，${rows[0]?.date || ''} 至 ${rows.at(-1)?.date || ''}；使用左右方向键查看每日数值`" @pointermove="inspect" @pointerleave="hovered = null" @focus="hovered = rows.length - 1" @blur="hovered = null" @keydown.left.prevent="move(-1)" @keydown.right.prevent="move(1)">
      <defs><linearGradient :id="gradientId" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" :stop-color="color" stop-opacity=".2" /><stop offset="100%" :stop-color="color" stop-opacity=".02" /></linearGradient></defs>
      <polygon v-if="points.length" :points="`${points[0].x},72 ${line} ${points.at(-1).x},72`" :fill="`url(#${gradientId})`" />
      <polyline :points="line" :stroke="color" stroke-width="1.8" vector-effect="non-scaling-stroke" fill="none" stroke-linejoin="round" stroke-linecap="round" />
      <template v-if="activePoint"><line :x1="activePoint.x" :x2="activePoint.x" y1="5" y2="72" :stroke="color" stroke-opacity=".3" stroke-dasharray="3 3" /><circle :cx="activePoint.x" :cy="activePoint.y" r="3" :fill="color" stroke="#fff" stroke-width="1.5" /></template>
      <circle v-else-if="points.length === 1" :cx="points[0].x" :cy="points[0].y" r="2.5" :fill="color" />
    </svg>
    <span class="spark-caption">{{ label }}</span>
  </div>
</template>

<style scoped>
.usage-sparkline { position: relative; min-width: 0; margin-top: auto; height: 88px; display: flex; flex-direction: column; gap: 7px; }
svg { display: block; width: 100%; height: 66px; overflow: visible; border-radius: 3px; }
svg:focus-visible { outline: 2px solid #8b9e91; outline-offset: 3px; }
.spark-caption { color: #87968b; font-size: 9px; line-height: 1.5; }
.spark-tooltip { position: absolute; top: -8px; left: 50%; transform: translateX(-50%); z-index: 1; max-width: 100%; box-sizing: border-box; padding: 5px 7px; border: 1px solid #d8e1d9; border-radius: 6px; background: #fff; color: #365847; font-size: 10px; white-space: nowrap; pointer-events: none; box-shadow: 0 3px 10px #24483712; }
</style>
