<script setup>
import { contentDetailUrl } from './contentLinks.js'
import { computed, ref, watch } from 'vue'
import CategoryOpportunity from './CategoryOpportunity.vue'

const props = defineProps({
  tagGroups: { type: Object, default: () => ({ image: [], video: [] }) },
  categoryInsights: { type: Object, default: () => ({}) },
  insightStatus: { type: String, default: '' },
  periodLabel: { type: String, default: '' },
})
const emit = defineEmits(['scope-change'])
const activeType = ref('image')
const activeTag = ref('all')
const activeMetric = ref('exposure')
const expandedCategory = ref('')
const topCount = ref(5)
const sampleTrack = ref(null)
const sampleLimit = computed(() => Math.max(1, Math.floor(Number(topCount.value) || 5)))
const metrics = [
  { key: 'revenue', label: '种草成交', note: '当前下载周期成交金额合计' },
  { key: 'exposure', label: '累计曝光人数', note: '各内容曝光人数求和' },
  { key: 'clicks', label: '点击次数', note: '各内容点击次数求和' },
  { key: 'viralCount', label: '爆文数', note: '当前下载周期爆文总数' },
]
const metricLabel = computed(() => metrics.find((metric) => metric.key === activeMetric.value).label)
const groupNames = {
  image: { label: '图文内容', shortLabel: '图文' },
  video: { label: '视频内容', shortLabel: '视频' },
}
const activeGroup = computed(() => groupNames[activeType.value])
const tags = computed(() => props.tagGroups?.[activeType.value] || [])
const rankedTags = computed(() => {
  const groups = new Map()
  for (const tag of tags.value) {
    const name = tag.category || tag.label
    if (!groups.has(name)) groups.set(name, {
      id: name, label: name, color: tag.color, children: [], samples: [],
      trendLabels: tag.trendLabels,
      trends: Object.fromEntries(metrics.map(({ key }) => [key, tag.trends[key].map(() => 0)])),
      contentCount: 0, viralCount: 0, exposure: 0, clicks: 0, product_click_users: 0, views: 0, interactions: 0, revenue: 0,
    })
    const parent = groups.get(name)
    for (const key of ['contentCount', 'viralCount', 'exposure', 'clicks', 'product_click_users', 'views', 'interactions', 'revenue']) parent[key] += tag[key]
    for (const { key } of metrics) parent.trends[key] = parent.trends[key].map((value, index) => value + (tag.trends[key][index] || 0))
    parent.samples.push(...tag.samples)
    if (tag.subcategory) parent.children.push({ ...tag, shortLabel: tag.subcategory })
  }
  return [...groups.values()].map((parent) => {
    parent.children.sort((a, b) => metricAmount(b) - metricAmount(a))
    return parent
  }).sort((a, b) => metricAmount(b) - metricAmount(a))
})
const selectedTag = computed(() => rankedTags.value.find((tag) => tag.id === activeTag.value)
  || rankedTags.value.flatMap((tag) => tag.children).find((tag) => tag.id === activeTag.value)
  || null)
const rankingRows = computed(() => {
  if (!selectedTag.value) return rankedTags.value
  if (selectedTag.value.children?.length) return selectedTag.value.children.map((tag) => ({ ...tag, label: tag.shortLabel }))
  return [...selectedTag.value.samples].sort(compareSamples).slice(0, 5).map((sample) => ({
    id: sample.content_id, label: sample.title, color: selectedTag.value.color,
    ...sample, contentCount: 1, isContent: true,
  }))
})
const rankingTitle = computed(() => !selectedTag.value
  ? activeGroup.value.shortLabel + '分类表现排名'
  : selectedTag.value.children?.length
    ? selectedTag.value.label + '二级分类排名'
    : selectedTag.value.label + '内容表现排名')
const opportunityRows = computed(() => {
  if (!selectedTag.value) return rankedTags.value
  if (selectedTag.value.children?.length) return selectedTag.value.children.map(tag => ({ ...tag, label: tag.shortLabel }))
  return [selectedTag.value]
})
const showOpportunity = computed(() => {
  if (selectedTag.value?.category === '种草短视频' && selectedTag.value.subcategory) return false
  return !rankedTags.value.some(tag => tag.id === activeTag.value && !tag.children.length)
})
const trendTarget = computed(() => selectedTag.value || rankedTags.value[0] || null)
const summary = computed(() => selectedTag.value || tags.value.reduce((total, tag) => ({
  contentCount: total.contentCount + tag.contentCount,
  viralCount: total.viralCount + tag.viralCount,
  exposure: total.exposure + tag.exposure,
  clicks: total.clicks + tag.clicks,
  views: total.views + tag.views,
  interactions: total.interactions + tag.interactions,
  revenue: total.revenue + tag.revenue,
}), { contentCount: 0, viralCount: 0, exposure: 0, clicks: 0, product_click_users: 0, views: 0, interactions: 0, revenue: 0 }))
const availableSamples = computed(() => (selectedTag.value
  ? selectedTag.value.samples.map((sample) => ({ ...sample, tag: selectedTag.value }))
  : tags.value.flatMap((tag) => tag.samples.map((sample) => ({ ...sample, tag }))))
  .sort(compareSamples))
const visibleSamples = computed(() => availableSamples.value.slice(0, sampleLimit.value))
const concentration = computed(() => {
  const rows = availableSamples.value
  const total = rows.reduce((sum, row) => sum + metricAmount(row), 0)
  const bands = [
    { label: '第1名', start: 0, end: 1, color: '#345f4c' },
    { label: '第2–5名', start: 1, end: 5, color: '#76955e' },
    { label: '第6–10名', start: 5, end: 10, color: '#a9bf7c' },
    { label: '其余内容', start: 10, end: rows.length, color: '#cdd9ba' },
  ].map(band => {
    const items = rows.slice(band.start, Math.max(band.start, band.end))
    const amount = items.reduce((sum, row) => sum + metricAmount(row), 0)
    return { ...band, count: items.length, amount, share: total > 0 ? amount / total : 0 }
  })
  return { total, bands, count: rows.length, topFiveShare: total > 0 ? rows.slice(0, 5).reduce((sum, row) => sum + metricAmount(row), 0) / total : 0 }
})
const trendPoints = computed(() => trendTarget.value?.trends[activeMetric.value] || [])
const trendDelta = computed(() => {
  const previous = trendPoints.value.at(-2)
  return previous ? (metricAmount(trendTarget.value) - previous) / previous : null
})
const maxRanking = computed(() => Math.max(1, ...rankingRows.value.map(metricAmount)))
const maxTrend = computed(() => Math.max(1, ...trendPoints.value))
watch([activeType, activeTag, activeMetric, sampleLimit], () => { if (sampleTrack.value) sampleTrack.value.scrollLeft = 0 })
watch(() => props.tagGroups, () => { activeTag.value = 'all'; expandedCategory.value = '' })
watch([activeType, activeTag, selectedTag], () => emit('scope-change', { type: activeType.value, tagId: activeTag.value, label: selectedTag.value?.label || `全部${activeType.value === 'image' ? '图文' : '视频'}` }), { immediate: true })

function selectType(type) {
  activeType.value = type
  activeTag.value = 'all'
  expandedCategory.value = ''
}
function selectPrimary(tag) {
  activeTag.value = tag.id
  expandedCategory.value = tag.children.length && expandedCategory.value !== tag.id ? tag.id : ''
}
function selectRankingRow(row) {
  if (row.isContent) return
  if (row.children?.length) selectPrimary(row)
  else activeTag.value = row.id
}
function metricAmount(item) {
  return Number(item?.[activeMetric.value] || 0)
}
function compareSamples(a, b) {
  return (metricAmount(b) - metricAmount(a)) || b.exposure - a.exposure
}
function formatNumber(value) {
  return new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 0 }).format(Number(value || 0))
}
function formatCompact(value) {
  const number = Number(value || 0)
  return number >= 10000 ? (number / 10000).toFixed(number >= 100000 ? 0 : 1) + '万' : formatNumber(number)
}
function formatMoney(value) {
  const number = Number(value || 0)
  return number >= 10000 ? '¥' + (number / 10000).toFixed(number >= 100000 ? 0 : 1) + '万'
    : '¥' + new Intl.NumberFormat('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(number)
}
function formatMetric(value) {
  return activeMetric.value === 'revenue' ? formatMoney(value) : formatCompact(value) + (activeMetric.value === 'viralCount' ? '篇' : activeMetric.value === 'exposure' ? '人' : '次')
}
function formatPercent(value) {
  return value == null ? '暂无对比' : ((Number(value) * 100).toFixed(1) + '%')
}
function contentUrl(sample) {
  return contentDetailUrl(sample.content_id, activeType.value)
}
</script>

<template>
  <section class="tag-analysis-panel" aria-labelledby="tag-analysis-title">
    <header class="tag-analysis-header">
      <div>
        <p class="tag-analysis-eyebrow">CONTENT TAG LAB · MYSQL DATA</p>
        <h3 id="tag-analysis-title">按内容标签看清每种内容的表现</h3>
        <p>按汇总分类和二级分类统计当前下载周期的内容表现。</p>
      </div>
      <div class="tag-analysis-status"><i></i><span>品牌数据</span><small>{{ periodLabel }}</small></div>
    </header>

    <div class="tag-type-switch" role="tablist" aria-label="内容大分类">
      <button v-for="type in ['image', 'video']" :key="type" :class="{ active: activeType === type }" role="tab" :aria-selected="activeType === type" type="button" @click="selectType(type)">
        <span class="tag-type-icon" :class="type === 'image' ? 'image-icon' : 'video-icon'">{{ type === 'image' ? '图' : '视' }}</span>
        <span><strong>{{ groupNames[type].shortLabel }}</strong><small>{{ type === activeType ? rankedTags.length : new Set((tagGroups?.[type] || []).map((tag) => tag.category || tag.label)).size }} 个一级分类</small></span>
      </button>
    </div>

    <div v-if="!tags.length" class="dashboard-state">当前下载周期暂无{{ activeGroup.shortLabel }}数据。</div>
    <div v-else class="tag-analysis-layout">
      <aside class="tag-category-rail">
        <div class="tag-rail-heading"><span>一级分类</span><strong>{{ activeGroup.shortLabel }}内容</strong></div>
        <button class="tag-all-option" :class="{ active: activeTag === 'all' }" type="button" @click="activeTag = 'all'">
          <span class="tag-all-mark">总</span><span><strong>全部{{ activeGroup.shortLabel }}</strong><small>汇总全部分类表现</small></span><em>{{ formatCompact(tags.reduce((sum, tag) => sum + tag.contentCount, 0)) }}篇</em>
        </button>
        <div class="tag-category-list">
          <div v-for="tag in rankedTags" :key="tag.id" class="tag-category-group">
            <button :class="['tag-category-item', { active: activeTag === tag.id }]" type="button" :aria-expanded="tag.children.length ? expandedCategory === tag.id : undefined" @click="selectPrimary(tag)">
              <i :style="{ background: tag.color }"></i><span><strong>{{ tag.label }}<b v-if="tag.children.length" class="tag-expand-icon">{{ expandedCategory === tag.id ? '⌄' : '›' }}</b></strong><small>{{ tag.children.length ? tag.children.length + ' 个二级分类 · 点击展开' : '当前下载周期' }}</small></span><em>{{ formatMetric(metricAmount(tag)) }}</em>
            </button>
            <div v-if="tag.children.length && expandedCategory === tag.id" class="tag-subcategory-list">
              <button v-for="child in tag.children" :key="child.id" class="tag-subcategory-item" :class="{ active: activeTag === child.id }" type="button" @click="activeTag = child.id">
                <span>{{ child.shortLabel }}</span><em>{{ formatMetric(metricAmount(child)) }}</em>
              </button>
            </div>
          </div>
        </div>
      </aside>

      <div class="tag-analysis-content">
        <div class="tag-summary-grid">
          <button v-for="metric in metrics" :key="metric.key" type="button" class="tag-summary-card" :class="{ active: activeMetric === metric.key, 'money-summary': metric.key === 'revenue' }" :aria-pressed="activeMetric === metric.key" @click="activeMetric = metric.key">
            <span>{{ metric.label }}</span><strong>{{ metric.key === 'revenue' ? formatMoney(summary[metric.key]) : formatCompact(summary[metric.key]) }}</strong><small>{{ metric.note }}</small>
          </button>
        </div>

        <div v-if="trendTarget" class="tag-insight-strip"><span class="tag-insight-mark">↗</span><div><strong>{{ trendTarget.label }}{{ selectedTag ? '表现' : '是当前' + activeGroup.shortLabel + '中' + metricLabel + '最高的分类' }}</strong><p>{{ metricLabel }}合计 {{ formatMetric(metricAmount(trendTarget)) }}。</p></div><em>{{ trendDelta == null ? '暂无上期' : formatPercent(trendDelta) }}</em></div>

        <div v-if="activeTag !== 'all'" class="tag-analysis-charts">
          <article class="tag-chart-card">
            <header><div><p>CONTENT CONCENTRATION</p><h4>内容贡献集中度</h4></div><span>{{ metricLabel }}占比</span></header>
            <template v-if="concentration.total > 0">
              <div class="concentration-summary"><strong>{{ formatPercent(concentration.topFiveShare) }}</strong><span>前 {{ Math.min(5, concentration.count) }} 篇内容贡献占比</span><small>基于当前分类全部 {{ concentration.count }} 篇内容</small></div>
              <div class="concentration-bar" role="img" :aria-label="concentration.bands.map(band => band.label + '贡献' + formatPercent(band.share)).join('，')"><span v-for="band in concentration.bands" :key="band.label" :style="{ width: band.share * 100 + '%', background: band.color }" :title="band.label + '：' + formatPercent(band.share)"></span></div>
              <div class="concentration-legend"><div v-for="band in concentration.bands" :key="band.label"><span><i :style="{ background: band.color }"></i>{{ band.label }}<small>{{ band.count }}篇</small></span><strong>{{ formatPercent(band.share) }}</strong><small>{{ formatMetric(band.amount) }}</small></div></div>
            </template>
            <div v-else class="concentration-empty">当前分类{{ metricLabel }}合计为0，暂无可计算的贡献比例。</div>
          </article>

          <article v-if="trendTarget" class="tag-chart-card tag-trend-card">
            <header><div><p>CONTENT TREND · MYSQL</p><h4>{{ trendTarget.label }}下载周期趋势</h4></div><span>{{ metricLabel }}合计</span></header>
            <div class="tag-trend-chart">
              <div class="tag-trend-y-axis"><span>高</span><span></span><span>中</span><span></span><span>低</span></div>
              <div class="tag-trend-plot"><div class="tag-trend-grid"></div><div class="tag-trend-bars"><div v-for="(point, index) in trendPoints" :key="index" class="tag-trend-bar-wrap" :title="trendTarget.trendLabels[index] + '：' + formatMetric(point)"><b :style="{ height: Math.max(3, point / maxTrend * 100) + '%', background: trendTarget.color }"></b><small>{{ trendTarget.trendLabels[index] }}</small></div></div></div>
            </div>
            <footer><span><i :style="{ background: trendTarget.color }"></i>{{ trendTarget.label }}</span><strong>本期 {{ formatMetric(metricAmount(trendTarget)) }}</strong></footer>
          </article>
        </div>

        <CategoryOpportunity v-if="showOpportunity" :rows="opportunityRows" :insights="categoryInsights[activeType + ':' + activeTag] || []" :insight-status="insightStatus" :metric-key="activeMetric" :metric-label="metricLabel" :title="selectedTag?.label || activeGroup.shortLabel" />

        <div class="tag-sample-heading"><div><p>CONTENT EXAMPLES</p><h4>{{ activeTag === 'all' ? 'TOP案例' : selectedTag.label + ' TOP案例' }}</h4></div><div class="tag-sample-controls"><label>TOP <input v-model.number="topCount" type="number" min="1" :max="Math.max(1, availableSamples.length)" step="1" aria-label="TOP案例数量" @change="topCount = Math.min(sampleLimit, Math.max(1, availableSamples.length))" /></label><span>显示 {{ visibleSamples.length }} / {{ availableSamples.length }} 条</span><button type="button" aria-label="向左查看案例" @click="sampleTrack?.scrollBy({ left: -280, behavior: 'smooth' })">‹</button><button type="button" aria-label="向右查看案例" @click="sampleTrack?.scrollBy({ left: 280, behavior: 'smooth' })">›</button></div></div>
        <div ref="sampleTrack" class="tag-sample-grid" tabindex="0" aria-label="TOP案例，支持横向滚动">
          <a v-for="sample in visibleSamples" :key="sample.content_id" class="tag-sample-card" :href="contentUrl(sample)" target="_blank" rel="noopener noreferrer">
            <span class="tag-sample-type">{{ activeGroup.shortLabel }} · {{ sample.tag.label }}</span>
            <strong>{{ sample.title }}</strong>
            <small>内容ID {{ sample.content_id }}</small>
            <small>{{ sample.meta }}</small>
            <span class="tag-sample-metric">{{ metricLabel }} {{ formatMetric(metricAmount(sample)) }}</span>
            <small>{{ sample.metric }}</small>
            <span class="tag-sample-link">查看原内容 ↗</span>
          </a>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.tag-analysis-panel { display: grid; gap: 16px; padding: 22px; border: 1px solid #d8e3d9; border-radius: 18px; background: linear-gradient(135deg, rgba(255,255,255,.94), rgba(244,248,239,.96)); box-shadow: 0 12px 30px rgba(36,68,57,.05); }
.tag-analysis-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 18px; }.tag-analysis-eyebrow, .tag-chart-card header p, .tag-sample-heading p { margin: 0 0 5px; color: #9bab9d; font-size: 9px; font-weight: 850; letter-spacing: .15em; }.tag-analysis-header h3 { margin: 0; color: #234541; font-size: 22px; letter-spacing: -.035em; }.tag-analysis-header p:last-child { margin: 5px 0 0; color: #87958e; font-size: 11px; }.tag-analysis-status { display: flex; align-items: center; gap: 6px; padding: 8px 10px; border: 1px solid #e4eac6; border-radius: 8px; color: #6e8150; background: #f7fae9; white-space: nowrap; }.tag-analysis-status i { width: 7px; height: 7px; border-radius: 50%; background: #c0cc58; box-shadow: 0 0 0 4px rgba(192,204,88,.18); }.tag-analysis-status span { font-size: 10px; font-weight: 850; }.tag-analysis-status small { color: #a0aa8b; font-size: 9px; }
.tag-type-switch { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }.tag-type-switch button { display: flex; align-items: center; gap: 11px; min-height: 66px; padding: 10px 13px; border: 1px solid #dce6dd; border-radius: 11px; color: #78908a; background: #fafcf9; text-align: left; cursor: pointer; }.tag-type-switch button.active { border-color: #6f8e58; color: #244c40; background: linear-gradient(135deg, #f1f6d0, #f8faea); box-shadow: inset 0 0 0 1px rgba(130,153,87,.14); }.tag-type-switch button > span:last-child { display: grid; gap: 3px; }.tag-type-switch strong { color: inherit; font-size: 14px; }.tag-type-switch small { color: #9aa89e; font-size: 10px; }.tag-type-icon { display: grid; width: 34px; height: 34px; place-items: center; border-radius: 9px; font-size: 14px; font-weight: 900; }.image-icon { color: #536e9e; background: #e5ecf5; }.video-icon { color: #a06f65; background: #f5e6dc; }
.tag-analysis-layout { display: grid; grid-template-columns: 210px minmax(0, 1fr); gap: 15px; }.tag-category-rail { min-width: 0; padding: 13px 10px; border: 1px solid #e0e8df; border-radius: 13px; background: rgba(248,251,246,.8); }.tag-rail-heading { display: flex; justify-content: space-between; align-items: baseline; padding: 0 6px 9px; border-bottom: 1px solid #e7eee6; }.tag-rail-heading span { color: #a0aca2; font-size: 9px; letter-spacing: .12em; }.tag-rail-heading strong { color: #4d665e; font-size: 11px; }.tag-all-option, .tag-category-item { display: grid; grid-template-columns: 28px minmax(0, 1fr) auto; gap: 8px; align-items: center; width: 100%; padding: 9px 6px; border: 0; border-radius: 9px; color: #5f766e; background: transparent; text-align: left; cursor: pointer; }.tag-all-option { margin-top: 7px; }.tag-all-option.active, .tag-category-item.active { background: #eaf1d0; }.tag-all-mark { display: grid; width: 25px; height: 25px; place-items: center; border-radius: 7px; color: #56713f; background: #dce8ab; font-size: 9px; font-weight: 900; }.tag-category-item > i { display: block; width: 9px; height: 9px; margin-left: 8px; border-radius: 50%; }.tag-all-option > span:nth-child(2), .tag-category-item > span { display: grid; gap: 2px; min-width: 0; }.tag-all-option strong, .tag-category-item strong { overflow: hidden; color: #48645a; font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }.tag-all-option small, .tag-category-item small { overflow: hidden; color: #9aa89f; font-size: 9px; text-overflow: ellipsis; white-space: nowrap; }.tag-all-option em, .tag-category-item em { color: #8b9b91; font-size: 9px; font-style: normal; white-space: nowrap; }.tag-category-list { display: grid; gap: 2px; margin-top: 4px; }
.tag-analysis-content { display: grid; gap: 13px; min-width: 0; }.tag-summary-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 9px; }.tag-summary-card { min-width: 0; padding: 13px 14px; border: 1px solid #dce6df; border-radius: 11px; background: rgba(255,255,255,.75); text-align: left; cursor: pointer; }.tag-summary-card.active { border-color: #ceda83; background: linear-gradient(135deg, #f0f5c1, #f7f9e5); box-shadow: inset 0 0 0 1px #ceda83; }.tag-summary-card.money-summary { border-color: #eadbbd; background: linear-gradient(135deg, #fffdf8, #fbf4e2); }.tag-summary-card span { color: #789087; font-size: 10px; }.tag-summary-card strong { display: block; margin-top: 7px; overflow: hidden; color: #294c42; font-size: clamp(20px, 2vw, 27px); letter-spacing: -.045em; text-overflow: ellipsis; white-space: nowrap; }.tag-summary-card small { display: block; margin-top: 5px; overflow: hidden; color: #9ba79f; font-size: 9px; text-overflow: ellipsis; white-space: nowrap; }.tag-summary-card b { color: #4c9a6e; font-weight: 850; }.money-summary strong { color: #8c6b2c; }
.tag-insight-strip { display: flex; align-items: center; gap: 10px; padding: 11px 13px; border: 1px solid #e0e9bf; border-radius: 10px; background: #f7f9e9; }.tag-insight-mark { display: grid; flex: 0 0 26px; width: 26px; height: 26px; place-items: center; border-radius: 8px; color: #668444; background: #e3edb9; font-size: 17px; font-weight: 900; }.tag-insight-strip div { min-width: 0; }.tag-insight-strip strong { color: #557145; font-size: 11px; }.tag-insight-strip p { margin: 3px 0 0; overflow: hidden; color: #879675; font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }.tag-insight-strip em { margin-left: auto; color: #4d996c; font-size: 12px; font-style: normal; font-weight: 900; white-space: nowrap; }
.tag-analysis-charts { display: grid; grid-template-columns: minmax(0, 1.02fr) minmax(0, 1fr); gap: 11px; }.tag-chart-card { min-width: 0; padding: 14px; border: 1px solid #dde7df; border-radius: 12px; background: rgba(255,255,255,.72); }.tag-chart-card header { display: flex; justify-content: space-between; gap: 10px; align-items: flex-start; }.tag-chart-card header p { color: #a0ada4; }.tag-chart-card h4, .tag-sample-heading h4 { margin: 0; color: #34584d; font-size: 14px; }.tag-chart-card header > span, .tag-sample-heading > span { color: #a0aaa3; font-size: 9px; white-space: nowrap; }.tag-ranking-list { display: grid; gap: 8px; margin-top: 15px; }.tag-ranking-row { display: grid; grid-template-columns: 20px 9px minmax(58px, .45fr) minmax(70px, 1fr) 70px; gap: 6px; align-items: center; width: 100%; padding: 5px 5px; border: 0; border-radius: 7px; background: transparent; text-align: left; cursor: pointer; }.tag-ranking-row.selected { background: #f0f4df; }.tag-ranking-row:disabled { cursor: default; }.tag-ranking-index { color: #a5b0a8; font-size: 9px; font-weight: 750; }.tag-ranking-row > i { width: 8px; height: 8px; border-radius: 50%; }.tag-ranking-row > span { overflow: hidden; color: #60776f; font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }.tag-ranking-bar { height: 5px; overflow: hidden; border-radius: 8px; background: #ecf1ea; }.tag-ranking-bar b { display: block; height: 100%; border-radius: inherit; }.tag-ranking-row > strong { color: #516e64; font-size: 10px; text-align: right; }.tag-trend-card { background: linear-gradient(135deg, #fbfcf7, #f5f8eb); }.tag-trend-chart { display: grid; grid-template-columns: 25px minmax(0, 1fr); gap: 7px; height: 136px; margin-top: 13px; }.tag-trend-y-axis { display: flex; flex-direction: column; justify-content: space-between; padding-bottom: 18px; color: #a5b0a8; font-size: 8px; text-align: right; }.tag-trend-plot { position: relative; min-width: 0; }.tag-trend-grid { position: absolute; inset: 0 0 18px; background: repeating-linear-gradient(to bottom, #e4ece0 0, #e4ece0 1px, transparent 1px, transparent 25%); }.tag-trend-bars { position: absolute; inset: 0 3px 0; display: flex; align-items: end; justify-content: space-around; gap: 7px; }.tag-trend-bar-wrap { display: flex; flex: 1; height: 100%; flex-direction: column; align-items: center; justify-content: end; gap: 5px; }.tag-trend-bar-wrap b { display: block; width: min(25px, 70%); min-height: 8px; border-radius: 5px 5px 2px 2px; opacity: .82; }.tag-trend-bar-wrap small { color: #a3afa7; font-size: 8px; white-space: nowrap; }.tag-trend-card footer { display: flex; justify-content: space-between; align-items: center; margin-top: 2px; color: #94a29a; font-size: 9px; }.tag-trend-card footer span { display: inline-flex; align-items: center; gap: 5px; }.tag-trend-card footer i { width: 12px; height: 3px; border-radius: 5px; }.tag-trend-card footer strong { color: #638164; font-size: 10px; }
.concentration-summary { display: flex; flex-wrap: wrap; align-items: baseline; gap: 6px 10px; margin: 15px 0 12px; }.concentration-summary strong { font-size: 28px; color: #345f4c; }.concentration-summary span { font-size: 11px; color: #65816d; }.concentration-summary > small { flex-basis: 100%; font-size: 9px; color: #96a395; }.concentration-bar { display: flex; height: 18px; overflow: hidden; border-radius: 6px; background: #ecf1e6; }.concentration-bar span { height: 100%; }.concentration-legend { display: grid; gap: 8px; margin-top: 13px; }.concentration-legend > div { display: grid; grid-template-columns: 1fr 50px 80px; align-items: center; gap: 8px; font-size: 10px; color: #5b7666; }.concentration-legend span { display: flex; align-items: center; gap: 6px; }.concentration-legend i { width: 8px; height: 8px; border-radius: 3px; }.concentration-legend small { color: #96a395; font-size: 9px; }.concentration-legend > div > small,.concentration-legend strong { text-align: right; }.concentration-empty { padding: 35px 0; color: #96a395; font-size: 11px; }
.tag-sample-heading { display: flex; justify-content: space-between; align-items: end; gap: 10px; padding-top: 2px; }
.tag-sample-grid { display: grid; grid-auto-flow: column; grid-auto-columns: max(190px, calc((100% - 36px) / 5)); gap: 9px; overflow-x: auto; padding-bottom: 9px; scroll-snap-type: x proximity; scrollbar-width: thin; scrollbar-color: #9caf8e #edf2e7; }
.tag-sample-card { display: grid; align-content: start; gap: 5px; min-width: 0; padding: 10px 12px; scroll-snap-align: start; border: 1px solid #dee8e0; border-radius: 11px; color: #45655a; background: #fff; text-decoration: none; }
.tag-sample-controls { display: flex; align-items: center; gap: 8px; color: #8a9c91; font-size: 10px; }.tag-sample-controls label { display: flex; align-items: center; gap: 5px; color: #557661; font-weight: 750; }.tag-sample-controls input { width: 60px; padding: 5px 6px; border: 1px solid #dce6d6; border-radius: 6px; color: #34584d; background: #fff; }.tag-sample-controls button { width: 26px; height: 26px; border: 1px solid #dce6d6; border-radius: 6px; background: #f5f8ed; color: #557661; cursor: pointer; font-size: 18px; }.tag-sample-grid::-webkit-scrollbar { height: 7px; }.tag-sample-grid::-webkit-scrollbar-track { background: #edf2e7; border-radius: 8px; }.tag-sample-grid::-webkit-scrollbar-thumb { background: #9caf8e; border-radius: 8px; }
.tag-sample-card:hover, .tag-sample-card:focus-visible { border-color: #8ba991; outline: none; box-shadow: 0 5px 15px rgba(36,68,57,.08); }
.tag-sample-type { width: fit-content; padding: 3px 7px; border-radius: 5px; color: #557661; background: #eef4e8; font-size: 10px; font-weight: 800; }
.tag-sample-card strong { display: -webkit-box; overflow: hidden; min-height: 2.8em; color: #34584d; font-size: 13px; line-height: 1.4; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }
.tag-sample-card small { overflow: hidden; color: #8a9c91; font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.tag-sample-metric { color: #62886a; font-size: 10px; font-weight: 750; line-height: 1.4; }
.tag-sample-link { align-self: end; color: #456e59; font-size: 10px; font-weight: 800; }
.tag-category-group { min-width: 0; }.tag-expand-icon { margin-left: 5px; color: #769188; font-size: 15px; }.tag-subcategory-list { display: grid; gap: 2px; margin: 0 3px 5px 19px; padding-left: 11px; border-left: 1px solid #d7e3d8; }.tag-subcategory-item { display: flex; justify-content: space-between; gap: 8px; width: 100%; padding: 7px 8px; border: 0; border-radius: 7px; color: #647d72; background: transparent; font-size: 10px; text-align: left; cursor: pointer; }.tag-subcategory-item.active { color: #315c46; background: #eaf1d0; font-weight: 800; }.tag-subcategory-item span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.tag-subcategory-item em { color: #8b9b91; font-style: normal; white-space: nowrap; }
@media (max-width: 1050px) { .tag-analysis-layout { grid-template-columns: 1fr; }.tag-category-rail { padding: 10px; }.tag-rail-heading { padding-bottom: 7px; }.tag-all-option, .tag-category-list { display: flex; flex-wrap: wrap; gap: 5px; }.tag-all-option, .tag-category-item { width: auto; flex: 1 1 160px; }.tag-category-item em, .tag-all-option em { margin-left: auto; }.tag-sample-grid { grid-auto-columns: max(190px, calc((100% - 18px) / 3)); } }
@media (max-width: 1050px) { .tag-category-group { flex: 1 1 160px; }.tag-category-group .tag-category-item { width: 100%; } }
@media (max-width: 700px) { .tag-analysis-panel { padding: 15px; }.tag-analysis-header { flex-direction: column; }.tag-analysis-status { width: fit-content; }.tag-type-switch, .tag-summary-grid, .tag-analysis-charts { grid-template-columns: 1fr; }.tag-summary-card strong { font-size: 25px; }.tag-insight-strip { align-items: flex-start; }.tag-insight-strip p { white-space: normal; line-height: 1.45; }.tag-sample-grid { grid-auto-columns: 210px; }.tag-sample-heading { flex-wrap: wrap; }.tag-ranking-row { grid-template-columns: 18px 9px minmax(52px, .55fr) minmax(50px, 1fr) 65px; }.tag-type-switch button { min-height: 58px; } }
</style>
