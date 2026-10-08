<script setup>
import { computed } from 'vue'
const props = defineProps({ rows: { type: Array, default: () => [] }, title: String, insights: { type: Array, default: () => [] }, insightStatus: String, metricKey: { type: String, default: 'exposure' }, metricLabel: { type: String, default: '累计曝光人数' } })
const total = computed(() => props.rows.reduce((sum, row) => ({ exposure: sum.exposure + row.exposure, clicks: sum.clicks + row.product_click_users, count: sum.count + row.contentCount }), { exposure: 0, clicks: 0, count: 0 }))
const baseline = computed(() => total.value.exposure ? total.value.clicks / total.value.exposure * 100 : 0)
const points = computed(() => props.rows.map(row => ({ ...row, share: total.value.exposure ? row.exposure / total.value.exposure * 100 : 0, rate: row.exposure ? row.product_click_users / row.exposure * 100 : 0, average: row.contentCount ? row.exposure / row.contentCount : 0 })).sort((a,b) => b.exposure - a.exposure))
const maxRate = computed(() => Math.max(1, baseline.value * 1.3, ...points.value.map(row => row.rate * 1.2)))
const maxAverage = computed(() => Math.max(1, ...points.value.map(row => row.average)))
const shareBaseline = computed(() => points.value.length ? 100 / points.value.length : 0)
const contributionTotal = computed(() => props.rows.reduce((sum, row) => sum + Number(row[props.metricKey] || 0), 0))
const contributions = computed(() => props.rows.map(row => ({ ...row, contribution: contributionTotal.value ? Number(row[props.metricKey] || 0) / contributionTotal.value * 100 : 0 })).sort((a, b) => Number(b[props.metricKey] || 0) - Number(a[props.metricKey] || 0)))
const leader = computed(() => contributions.value[0])
const number = value => new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 1 }).format(value)
const x = value => 55 + value / 100 * 500
const y = value => 260 - value / maxRate.value * 210
const radius = row => 9 + Math.sqrt(row.average / maxAverage.value) * 20
</script>
<template>
  <article class="opportunity">
    <header><div><p>CATEGORY OPPORTUNITY</p><h4>{{ title }} · 分类机会分析</h4></div><span>{{ points.length }} 个分类</span></header>
    <p class="summary" v-if="leader && contributionTotal">{{ leader.label }}贡献 {{ number(leader.contribution) }}% 的{{ metricLabel }}；当前范围商品点击率为 {{ number(baseline) }}%。</p>
    <p class="summary" v-else>当前范围{{ metricLabel }}合计为0，暂无可计算的贡献比例。</p>
    <div class="visual-grid">
      <section class="matrix"><h5>规模与点击效率</h5><p>横轴：曝光占比 · 纵轴：商品点击人数 / 曝光人数 · 气泡：单篇曝光</p>
        <svg viewBox="0 0 620 310" role="img" aria-label="分类曝光占比与商品点击率气泡图">
          <g v-for="tick in [0,1,2,3,4]" :key="tick" class="grid"><line x1="55" x2="555" :y1="y(tick * maxRate / 4)" :y2="y(tick * maxRate / 4)"/><text x="47" :y="y(tick * maxRate / 4)+4" text-anchor="end">{{ number(tick * maxRate / 4) }}%</text></g>
          <g v-for="tick in [0,20,40,60,80,100]" :key="tick" class="grid"><line :x1="x(tick)" :x2="x(tick)" y1="50" y2="260"/><text :x="x(tick)" y="282" text-anchor="middle">{{ tick }}%</text></g>
          <line class="baseline" x1="55" x2="555" :y1="y(baseline)" :y2="y(baseline)"/><line class="baseline" :x1="x(shareBaseline)" :x2="x(shareBaseline)" y1="50" y2="260"/>
          <text class="hint" x="55" y="24">虚线：当前范围平均点击率 / 平均曝光份额</text>
          <g v-for="row in points" :key="row.id"><title>{{ row.label }}：曝光占比 {{ number(row.share) }}%，点击率 {{ number(row.rate) }}%，单篇曝光 {{ number(row.average) }}，{{ row.contentCount }}篇内容，{{ row.viralCount }}篇爆文</title><circle :cx="x(row.share)" :cy="y(row.rate)" :r="radius(row)" :fill="row.color" fill-opacity=".8" stroke="white" stroke-width="2"/><text :x="Math.min(550, Math.max(70, x(row.share)))" :y="y(row.rate)-radius(row)-7" text-anchor="middle">{{ row.label }}</text></g>
        </svg>
      </section>
      <div class="comparisons"><section><h5>{{ metricLabel }}贡献</h5><div v-for="row in contributions" :key="row.id" class="share-row"><span :title="row.label">{{ row.label }}</span><div><b :style="{ width: row.contribution + '%', background: row.color }"></b></div><strong>{{ number(row.contribution) }}%</strong></div></section>

      </div>
    </div>
    <section class="category-ai-summary" aria-label="分类优势、不足与建议"><header><h5>子分类总结</h5><span>AI分析 · 数据更新后自动重算</span></header><div v-if="insights.length" class="category-ai-cards"><div v-for="insight in insights" :key="insight.id"><strong>{{ insight.label }}</strong><p><b>优势</b>{{ insight.strength }}</p><p><b class="weakness">不足</b>{{ insight.weakness }}</p><p><b class="suggestion">建议</b>{{ insight.suggestion }}</p></div></div><p v-else class="ai-state">{{ insightStatus === 'loading' ? '正在生成分类总结…' : insightStatus === 'error' ? '分类总结接口暂不可用，系统将自动重试。' : 'AI总结暂不可用，请检查LLM适配器配置。' }}</p></section>
  </article>
</template>
<style scoped>
.opportunity{padding:16px;border:1px solid #dce6d6;border-radius:13px;background:linear-gradient(120deg,#fcfdf8,#f4f8ed);color:#34584d;min-width:0}header{display:flex;justify-content:space-between;gap:12px}header p{margin:0 0 5px;color:#98a799;font-size:9px;font-weight:850;letter-spacing:.15em}h4{margin:0;font-size:16px}header>span,.summary{font-size:11px;color:#7d9083}.summary{margin:8px 0 12px;line-height:1.6}.visual-grid{display:grid;grid-template-columns:minmax(0,1.15fr) minmax(0,1fr);gap:18px;align-items:start}h5{font-size:12px;margin:0 0 8px}section>p{font-size:9px;color:#94a095;margin:0 0 8px;line-height:1.6}svg{display:block;width:100%;max-height:280px;overflow:visible}svg text{font-size:10px;fill:#587469}.grid line{stroke:#e5ecdf;stroke-width:1}.grid text,.hint{fill:#97a599;font-size:9px}.baseline{stroke:#b9ca9b;stroke-width:1.5;stroke-dasharray:5 4}.comparisons{padding-top:0;min-width:0}.comparisons section{display:grid;align-content:start;gap:4px}.share-row{display:grid;grid-template-columns:85px 1fr 48px;gap:8px;align-items:center;margin:8px 0;min-height:22px;font-size:10px}.share-row>span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.share-row>div{height:13px;border-radius:20px;background:#e9efdf;overflow:hidden}.share-row b{display:block;height:100%;border-radius:20px}.share-row strong{text-align:right}.category-ai-summary{margin-top:14px;padding-top:12px;border-top:1px solid #e1e9d9}.category-ai-summary header{align-items:center;margin-bottom:10px}.category-ai-summary header span{font-size:9px;color:#99a697}.category-ai-cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:9px}.category-ai-cards>div{padding:10px 12px;border:1px solid #dce6d6;border-radius:9px;background:#ffffffb8}.category-ai-cards strong{font-size:11px}.category-ai-cards p{margin:7px 0 0;font-size:10px;line-height:1.6;color:#738774}.category-ai-cards b{margin-right:6px;color:#4d8967}.category-ai-cards .suggestion{color:#5f7ca4}.category-ai-cards .weakness{color:#a28a54}.ai-state{font-size:10px;color:#94a095}@media(max-width:800px){.visual-grid{grid-template-columns:1fr}.opportunity{padding:14px}}
</style>
