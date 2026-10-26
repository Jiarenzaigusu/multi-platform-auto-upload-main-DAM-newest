<script setup>
import { computed } from 'vue'

const props = defineProps({ items: { type: Array, required: true }, label: { type: String, required: true } })
const total = computed(() => props.items.reduce((sum, item) => sum + item.value, 0))
const number = value => new Intl.NumberFormat('zh-CN').format(value)
const shortNumber = value => new Intl.NumberFormat('zh-CN', { notation: 'compact', maximumFractionDigits: 1 }).format(value)
const segments = computed(() => {
  let offset = 0
  return props.items.filter(item => item.value > 0).map(item => {
    const percent = 100 * item.value / total.value
    const segment = { ...item, percent, offset }
    offset += percent
    return segment
  })
})
</script>

<template>
  <div class="donut-layout">
    <svg viewBox="0 0 120 120" role="img" :aria-label="`${label}，合计 ${number(total)}`">
      <circle cx="60" cy="60" r="44" fill="none" stroke="#edf1e9" stroke-width="14" />
      <circle v-for="item in segments" :key="item.label" cx="60" cy="60" r="44" fill="none" :stroke="item.color" stroke-width="14" pathLength="100" :stroke-dasharray="`${item.percent} ${100 - item.percent}`" :stroke-dashoffset="-item.offset" transform="rotate(-90 60 60)"><title>{{ item.label }}：{{ number(item.value) }}（{{ item.percent.toFixed(1) }}%）</title></circle>
      <text x="60" y="59" class="donut-value">{{ total ? shortNumber(total) : '—' }}</text><text x="60" y="73" class="donut-caption">{{ total ? '合计' : '暂无数据' }}</text>
    </svg>
    <div class="donut-legend"><div v-for="item in segments" :key="item.label" class="donut-row"><i :style="{ background: item.color }"></i><span :title="item.label">{{ item.label }}</span><b>{{ number(item.value) }}</b><small>{{ item.percent.toFixed(1) }}%</small></div><p v-if="!segments.length">所选范围暂无可展示的数据</p></div>
  </div>
</template>

<style scoped>
.donut-layout { display: flex; align-items: center; gap: 24px; min-height: 210px; min-width: 0; }
svg { width: 180px; flex: 0 0 180px; max-width: 45%; } text { text-anchor: middle; fill: #183d32; } .donut-value { font-size: 17px; font-weight: 750; } .donut-caption { font-size: 7px; fill: #6d7f73; }
.donut-legend { flex: 1; min-width: 0; display: grid; gap: 13px; }
.donut-row { display: grid; grid-template-columns: 8px minmax(0,1fr) auto auto; gap: 8px; align-items: center; font-size: 12px; }
i { width: 8px; height: 8px; border-radius: 50%; } span { overflow-wrap: anywhere; } b { font-variant-numeric: tabular-nums; } small { color: #687d70; min-width: 40px; text-align: right; } p { font-size: 12px; color: #687d70; }
@media (max-width: 580px) { .donut-layout { gap: 12px; } svg { width: 120px; flex-basis: 120px; } .donut-row { grid-template-columns: 8px minmax(0,1fr) auto; } small { grid-column: 3; } }
</style>
