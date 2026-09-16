<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { apiRequest } from '../../api-client.js'
import TagAnalysisPanel from './TagAnalysisPanel.vue'

const period = ref('week')
const activeMetric = ref('content_viewers')
const comparison = ref('previous')
const loading = ref(true)
const error = ref('')
const data = ref(null)

const metricOptions = [
  { key: 'content_viewers', label: '内容查看人数' },
  { key: 'content_views', label: '内容查看次数' },
  { key: 'revenue', label: '种草成交金额' },
  { key: 'product_click_users', label: '商品点击人数' },
]

const current = computed(() => data.value?.summary?.current || null)
const periods = computed(() => data.value?.periods || [])
const channels = computed(() => data.value?.channels || [])
const trend = computed(() => data.value?.trend || [])
const compareTrend = computed(() => data.value?.comparison_trend || [])
const yearComparisonTrend = computed(() => data.value?.year_comparison_trend || [])
const comparisons = computed(() => data.value?.comparisons || {})
const comparisonLabel = computed(() => comparison.value === 'previous' ? '较上周' : '较去年同期')
const comparisonTrendRows = computed(() => comparison.value === 'previous' ? compareTrend.value : yearComparisonTrend.value)
const chartLabels = computed(() => {
  if (trend.value.length <= 7) return trend.value
  return Array.from({ length: 7 }, (_, index) => trend.value[Math.round(index * (trend.value.length - 1) / 6)])
})
const chartScale = computed(() => Math.max(
  1,
  ...trend.value.map((row) => Number(row[activeMetric.value] || 0)),
  ...compareTrend.value.map((row) => Number(row[activeMetric.value] || 0)),
  ...yearComparisonTrend.value.map((row) => Number(row[activeMetric.value] || 0)),
))
const chartValues = computed(() => normalizeTrend(trend.value, activeMetric.value, chartScale.value))
const comparisonValues = computed(() => normalizeTrend(comparisonTrendRows.value, activeMetric.value, chartScale.value))
const chartPoints = computed(() => points(chartValues.value))
const comparePoints = computed(() => points(comparisonValues.value))
const dateLabel = computed(() => periods.value.find((item) => item.key === period.value)?.date_label || '')
const metricLabel = computed(() => metricOptions.find((item) => item.key === activeMetric.value)?.label || '')
const comparisonOptions = computed(() => [
  { key: 'previous', label: '较上周', available: comparisons.value.previous_week?.available !== false && Boolean(compareTrend.value.length || comparisons.value.previous_week?.available) },
  { key: 'year', label: '较去年同期', available: comparisons.value.same_period_last_year?.available !== false && Boolean(yearComparisonTrend.value.length || comparisons.value.same_period_last_year?.available) },
])
const topClickChannel = computed(() => [...channels.value].sort((a, b) => Number(b.product_click_users || 0) - Number(a.product_click_users || 0))[0] || null)
const topSeedChannel = computed(() => [...channels.value].sort((a, b) => Number(b.revenue || 0) - Number(a.revenue || 0))[0] || null)
const aiAnalysis = computed(() => {
  if (!current.value) return []
  const clickChannel = topClickChannel.value
  const seedChannel = topSeedChannel.value
  const viewerDelta = deltaFor('content_viewers')
  const clickDelta = deltaFor('product_click_users')
  const viewers = Number(valueFor('content_viewers'))
  const clicks = Number(valueFor('product_click_users'))
  const revenue = Number(valueFor('revenue'))
  const clickRate = viewers ? clicks / viewers : 0
  return [
    {
      icon: '总',
      tag: '整体判断',
      title: '触达与转化需要一起看',
      text: `本周期累计触达 ${formatNumber(viewers)} 人，商品点击 ${formatNumber(clicks)} 人，点击承接率约 ${formatPercent(clickRate)}${revenue > 0 ? `，带来 ${formatMoney(revenue)} 成交` : '，成交信号仍需继续积累'}。建议不要只追求播放量，要同时观察点击和成交。`,
    },
    {
      icon: '机',
      tag: '内容机会',
      title: '找到可复制的内容组合',
      text: clickChannel && seedChannel && clickChannel.name !== seedChannel.name
        ? `${clickChannel.name}更擅长承接商品点击，${seedChannel.name}的成交表现更突出。可以把前者的表达效率与后者的场景说服力组合成新的内容模板。`
        : clickChannel
          ? `${clickChannel.name}在当前数据中同时表现出较好的点击承接，建议围绕它继续测试不同开场、封面和商品露出时机。`
          : '建议从开场信息密度、使用场景和商品露出时机三个变量入手，建立可复用的内容模板。',
    },
    {
      icon: '链',
      tag: '转化链路',
      title: '优化从兴趣到购买的最后一步',
      text: clickDelta != null && clickDelta >= 0
        ? `商品点击较上周仍在增长，说明内容已经具备兴趣承接；下一步应强化视频结尾的行动指引、商品利益点和落地页一致性，减少点击后的流失。`
        : '当前商品点击承接还有提升空间，建议检查商品露出、标题利益点、评论区引导和落地页首屏是否一致。',
    },
    {
      icon: viewerDelta != null && viewerDelta < 0 ? '!' : '稳',
      tag: viewerDelta != null && viewerDelta < 0 ? '风险提示' : '节奏观察',
      title: viewerDelta != null && viewerDelta < 0 ? '触达回落，先稳住内容供给' : '保持稳定更新并扩大测试面',
      text: viewerDelta != null && viewerDelta < 0
        ? `内容查看人数较上周下降 ${formatPercent(Math.abs(viewerDelta))}，不建议立刻大幅改变内容方向；优先保持更新频率，再用小批量变体测试找回触达。`
        : '当前触达表现没有明显预警，适合保持稳定发布节奏，用小批量 A/B 测试逐步扩大高效主题，而不是一次性改变全部内容。',
    },
    {
      icon: '下',
      tag: '执行建议',
      title: '下一周建议这样安排',
      text: '建议安排“复用一个高效主题 + 测试两个新变量 + 复盘一次数据”的内容节奏；每条视频至少记录主题、开场、时长、商品露出位置和点击结果，方便后续真正沉淀为 AI 可学习的样本。',
    },
  ]
})
const aiContentSummary = computed(() => {
  if (!current.value) return '连接数据库后，将根据现有视频数据总结内容表现。'
  const clickChannel = topClickChannel.value?.name || '当前主要渠道'
  const seedChannel = topSeedChannel.value?.name || '成交表现较好的渠道'
  const viewerDelta = deltaFor('content_viewers')
  return viewerDelta != null && viewerDelta < 0
    ? `本周期内容触达较上周下降 ${formatPercent(Math.abs(viewerDelta))}，但${clickChannel}的点击承接更突出；建议把${seedChannel}的真实场景表达复制到高点击主题中，优先修复“有曝光、少点击”的内容。`
    : `${clickChannel}更容易带来商品点击，${seedChannel}的成交表现更突出；后续可将高点击主题与真实使用场景结合，持续放大内容触达和种草转化。`
})
const stateLabel = computed(() => {
  if (loading.value) return '正在同步数据库'
  if (error.value) return '数据库读取失败'
  if (data.value?.configured === false) return '等待配置 MySQL'
  if (data.value?.empty) return '数据库暂无看板数据'
  return '数据库已同步'
})

async function loadDashboard() {
  loading.value = true
  error.value = ''
  try {
    data.value = await apiRequest(`/api/dashboard?period=${encodeURIComponent(period.value)}`)
    if (!data.value.periods?.some((item) => item.key === period.value) && data.value.periods?.[0]) {
      period.value = data.value.periods[0].key
    }
  } catch (requestError) {
    error.value = requestError.message
  } finally {
    loading.value = false
  }
}

function valueFor(metric) { return current.value?.[metric] ?? 0 }
function deltaFor(metric) { return data.value?.summary?.deltas?.[metric] ?? null }
function formatNumber(value) { return new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 2 }).format(Number(value || 0)) }
function formatMoney(value) { return `¥${new Intl.NumberFormat('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(Number(value || 0))}` }
function formatPercent(value) { return value == null ? '—' : `${(Number(value) * 100).toFixed(1)}%` }
function formatDelta(value) {
  if (value == null) return '暂无对比'
  const percentage = Number(value) * 100
  return `${percentage >= 0 ? '+' : ''}${percentage.toFixed(1)}%`
}
function formatMetric(metric, value) { return metric === 'revenue' ? formatMoney(value) : formatNumber(value) }
function normalizeTrend(rows, metric, scaleMax) {
  if (!rows.length) return []
  return rows.map((row) => Math.max(5, Math.round((Number(row[metric] || 0) / scaleMax) * 92)))
}
function points(values) {
  if (!values.length) return ''
  const step = values.length === 1 ? 100 : 100 / (values.length - 1)
  return values.map((value, index) => `${(index * step).toFixed(2)},${104 - value}`).join(' ')
}
function insightText() {
  if (!current.value) return '连接数据库后，这里会根据实际指标生成周期速览。'
  const delta = deltaFor('content_viewers')
  if (delta == null) return '当前周期已加载，暂时没有可用的前一周期对比。'
  return delta >= 0
    ? `内容查看人数较前一周期提升 ${formatPercent(delta)}，继续关注内容触达与商品点击的联动。`
    : `内容查看人数较前一周期下降 ${formatPercent(Math.abs(delta))}，建议检查内容曝光和渠道承接。`
}

watch(period, (next, previousValue) => { if (next !== previousValue) loadDashboard() })
onMounted(loadDashboard)
</script>

<template>
  <section class="dashboard-view">
    <div class="dashboard-intro">
      <div>
        <div class="dashboard-kicker"><span class="pulse-dot"></span> MOVADO DATA · MYSQL LIVE</div>
      </div>
      <div class="dashboard-controls">
        <div class="period-switch" role="tablist" aria-label="数据周期">
          <button v-for="item in periods" :key="item.key" :class="{ active: period === item.key }" type="button" @click="period = item.key">{{ item.label }}</button>
        </div>
        <span class="data-note"><i :class="['status-dot', { loading }]" />{{ stateLabel }} · {{ dateLabel }}</span>
      </div>
    </div>

    <TagAnalysisPanel />

    <div v-if="error || data?.configured === false || data?.empty" class="dashboard-state" :class="{ error }">
      <strong>{{ error ? '无法加载数据库看板' : data?.configured === false ? '看板尚未连接 MySQL' : '数据库暂无可展示数据' }}</strong>
      <span>{{ error || (data?.configured === false ? `请配置：${(data.missing_settings || []).join('、')}` : '请先导入 movado_data.sql，或检查数据表是否为空。') }}</span>
      <button v-if="error" type="button" @click="loadDashboard">重试</button>
    </div>

    <template v-if="current">
      <div class="dashboard-kpis primary-kpis">
        <article class="dashboard-kpi kpi-primary">
          <div class="kpi-label"><span class="kpi-symbol">人</span> 内容查看人数</div>
          <strong>{{ formatNumber(valueFor('content_viewers')) }}</strong>
          <div class="kpi-foot"><span :class="deltaFor('content_viewers') >= 0 ? 'trend-positive' : 'trend-negative'">{{ formatDelta(deltaFor('content_viewers')) }}</span><span>较前周期</span><em>数据库原始口径</em></div>
          <div class="kpi-spark"><i v-for="(bar, index) in chartValues.slice(-7)" :key="index" :style="{ height: `${Math.max(8, bar * .46)}px` }"></i></div>
        </article>
        <article class="dashboard-kpi">
          <div class="kpi-label"><span class="kpi-symbol success">次</span> 内容查看次数</div>
          <strong>{{ formatNumber(valueFor('content_views')) }}</strong>
          <div class="kpi-foot"><span :class="deltaFor('content_views') >= 0 ? 'trend-positive' : 'trend-negative'">{{ formatDelta(deltaFor('content_views')) }}</span><span>较前周期</span><em>人均 {{ (Number(valueFor('content_views')) / Math.max(Number(valueFor('content_viewers')), 1)).toFixed(2) }} 次</em></div>
          <div class="mini-bars green-bars"><i v-for="(bar, index) in chartValues.slice(-6)" :key="index" :style="{ height: `${Math.max(18, bar * .45)}px` }"></i></div>
        </article>
        <article class="dashboard-kpi sales-kpi">
          <div class="kpi-label"><span class="kpi-symbol exposure">¥</span> 订阅引导成交金额</div>
          <strong>{{ formatMoney(valueFor('revenue')) }}</strong>
          <div class="kpi-foot"><span :class="deltaFor('revenue') >= 0 ? 'trend-positive' : 'trend-negative'">{{ formatDelta(deltaFor('revenue')) }}</span><span>较前周期</span><em>订阅表成交</em></div>
          <div class="mini-bars"><i v-for="(bar, index) in chartValues.slice(-6)" :key="index" :style="{ height: `${Math.max(18, bar * .45)}px` }"></i></div>
        </article>
        <article class="dashboard-kpi">
          <div class="kpi-label"><span class="kpi-symbol click">点</span> 商品点击人数</div>
          <strong>{{ formatNumber(valueFor('product_click_users')) }}</strong>
          <div class="kpi-foot"><span :class="deltaFor('product_click_users') >= 0 ? 'trend-positive' : 'trend-negative'">{{ formatDelta(deltaFor('product_click_users')) }}</span><span>较前周期</span><em>UV 点击率 {{ formatPercent(valueFor('uv_rate')) }}</em></div>
          <div class="goal-meter"><span :style="{ width: `${Math.min(100, Number(valueFor('uv_rate')) * 1000)}%` }"></span><b>{{ formatPercent(valueFor('uv_rate')) }}</b></div>
        </article>
      </div>

      <div class="secondary-metrics" aria-label="辅助指标">
        <span>数据库指标</span>
        <div><small>内容曝光人数</small><strong>{{ formatNumber(valueFor('impression_users')) }}</strong></div>
        <div><small>加购件数</small><strong>{{ formatNumber(valueFor('add_to_cart_items')) }}</strong></div>
        <div><small>商品点击次数</small><strong>{{ formatNumber(valueFor('product_clicks')) }}</strong></div>
        <div><small>引导成交人数</small><strong>{{ formatNumber(valueFor('content_driven_buyers')) }}</strong></div>
      </div>

      <div class="dashboard-grid dashboard-main-grid trend-only-grid">
        <article class="dashboard-card trend-card">
          <header class="dashboard-card-head"><div><p class="card-eyebrow">CORE TREND</p><h3>{{ metricLabel }}趋势</h3><p>支持较上周、较去年同期的真实数值对比</p></div><div class="trend-options"><div class="metric-switch"><button v-for="metric in metricOptions" :key="metric.key" :class="{ active: activeMetric === metric.key }" type="button" @click="activeMetric = metric.key">{{ metric.label }}</button></div><div class="compare-switch"><button :class="{ active: comparison === 'previous' }" type="button" :disabled="!comparisonOptions[0].available" @click="comparison = 'previous'">较上周</button><button :class="{ active: comparison === 'year' }" type="button" :disabled="!comparisonOptions[1].available" @click="comparison = 'year'">较去年同期</button></div></div></header>
          <div class="trend-body">
            <div class="trend-chart-column">
              <div class="chart-legend"><span><i class="legend-current"></i>{{ period === '30d' ? '近30天' : period === 'week' ? '本周' : '上周' }}</span><span v-if="comparePoints"><i class="legend-compare"></i>{{ comparisonLabel }}</span><b>{{ formatMetric(activeMetric, valueFor(activeMetric)) }}</b></div>
              <div class="line-chart">
                <div class="chart-y-axis"><span>高</span><span></span><span>中</span><span></span><span>低</span></div>
                <svg viewBox="0 0 100 110" preserveAspectRatio="none" aria-label="数据库指标趋势图"><defs><linearGradient id="trend-area-gradient" x1="0" x2="0" y1="0" y2="1"><stop offset="0%" stop-color="#c6d98d" stop-opacity=".58" /><stop offset="100%" stop-color="#e9f0c8" stop-opacity=".08" /></linearGradient></defs><path v-if="chartPoints" class="chart-area" :d="`M 0,104 L ${chartPoints.replaceAll(' ', ' L ')} L 100,104 Z`" /><polyline v-if="comparePoints" class="chart-line compare" :points="comparePoints" /><polyline v-if="chartPoints" class="chart-line" :points="chartPoints" /></svg>
                <div v-if="chartValues.length" class="chart-point-layer" aria-hidden="true"><span v-for="(point, index) in chartValues" :key="index" class="chart-point-dot" :style="{ left: `${chartValues.length === 1 ? 50 : index * 100 / (chartValues.length - 1)}%`, top: `${(104 - point) / 110 * 100}%` }"></span></div>
                <div class="chart-x-axis"><span v-for="row in chartLabels" :key="row.period_key">{{ row.label }}</span></div>
              </div>
            </div>
            <aside class="trend-comparison-panel" aria-label="趋势对比数值">
              <div class="comparison-panel-title"><span>对比明细</span><small>{{ metricLabel }}</small></div>
              <div v-for="option in comparisonOptions" :key="option.key" class="comparison-item" :class="{ unavailable: !option.available }">
                <div class="comparison-item-head"><strong>{{ option.label }}</strong><span v-if="option.available" :class="(comparisons[option.key === 'previous' ? 'previous_week' : 'same_period_last_year']?.deltas?.[activeMetric] ?? 0) >= 0 ? 'trend-positive' : 'trend-negative'">{{ formatDelta(comparisons[option.key === 'previous' ? 'previous_week' : 'same_period_last_year']?.deltas?.[activeMetric]) }}</span><span v-else>暂无数据</span></div>
                <div v-if="option.available" class="comparison-values"><div><small>本期</small><b>{{ formatMetric(activeMetric, valueFor(activeMetric)) }}</b></div><div><small>对比值</small><b>{{ formatMetric(activeMetric, comparisons[option.key === 'previous' ? 'previous_week' : 'same_period_last_year']?.values?.[activeMetric]) }}</b></div></div>
                <p v-else>接入去年同期数据后自动显示</p>
              </div>
            </aside>
          </div>
        </article>

      </div>

      <div class="dashboard-grid dashboard-bottom-grid ai-analysis-grid">
        <article class="dashboard-card ai-analysis-suite-card">
          <header class="dashboard-card-head"><div><p class="card-eyebrow">AI CONTENT ANALYSIS · BETA</p><h3>AI内容分析</h3><p>内容表现总结、用户行为洞察与后续发布建议</p></div><span class="ai-analysis-badge">AI</span></header>
          <div class="ai-analysis-suite-body">
            <div class="ai-content-overview"><span class="ai-content-overview-icon">✦</span><div><strong>AI本周期判断</strong><p>{{ aiContentSummary }}</p><div class="ai-overview-stats"><span><small>内容触达</small><b>{{ formatNumber(valueFor('content_viewers')) }}</b></span><span><small>商品点击</small><b>{{ formatNumber(valueFor('product_click_users')) }}</b></span><span><small>引导成交</small><b>{{ formatMoney(valueFor('revenue')) }}</b></span></div></div></div>
            <div class="ai-report-panel"><div class="ai-report-panel-head"><strong>关键洞察与动作</strong><small>根据当前可用数据归纳</small></div><div class="ai-report-list"><div v-for="item in aiAnalysis" :key="item.title" class="ai-report-row"><span class="ai-analysis-icon">{{ item.icon }}</span><div><div class="ai-report-row-title"><strong>{{ item.title }}</strong><em>{{ item.tag }}</em></div><p>{{ item.text }}</p></div></div><div v-if="!aiAnalysis.length" class="activity-empty">连接数据库后，将生成内容表现与发布建议。</div></div></div>
          </div>
          <div class="ai-analysis-footnote"><span>数据状态</span><strong>{{ data?.source?.latest_week ? `已基于 ${data.source.latest_week} 最新周报分析` : '等待数据库数据' }}</strong><em>当前为规则化分析示例，后续可接入真实 AI 模型</em></div>
        </article>
      </div>
    </template>
  </section>
</template>

<style scoped>
.dashboard-view { display: grid; gap: 18px; padding-bottom: 30px; }
.dashboard-intro { display: flex; justify-content: space-between; gap: 28px; align-items: flex-end; padding: 10px 2px 3px; }
.dashboard-kicker, .card-eyebrow { color: #849d91; font-size: 10px; font-weight: 850; letter-spacing: .16em; }.dashboard-kicker { display: flex; align-items: center; gap: 7px; color: #8c9e59; }.pulse-dot, .status-dot { width: 7px; height: 7px; border-radius: 50%; background: #a9c348; box-shadow: 0 0 0 4px rgba(169,195,72,.17); }.status-dot { display: inline-block; margin-right: 6px; width: 6px; height: 6px; background: #6aa47c; box-shadow: none; }.status-dot.loading { background: #d8a658; animation: pulse 1s infinite; }@keyframes pulse { 50% { opacity: .35; } }
.dashboard-intro h2 { max-width: 620px; margin: 9px 0 6px; color: #1a3a3a; font-size: clamp(25px, 3vw, 37px); line-height: 1.12; letter-spacing: -.045em; }.dashboard-intro p { margin: 0; color: #6c7f7e; font-size: 13px; }.dashboard-controls { display: grid; gap: 8px; justify-items: end; }.period-switch { display: flex; padding: 3px; border: 1px solid #d9e2d9; border-radius: 10px; background: #f8faf6; }.period-switch button, .metric-switch button, .compare-switch button, .platform-filter button { border: 0; background: transparent; color: #78908a; cursor: pointer; }.period-switch button { padding: 8px 13px; border-radius: 7px; font-size: 12px; font-weight: 750; }.period-switch button.active { color: #234541; background: #e8efaa; box-shadow: 0 2px 8px rgba(45,76,48,.1); }.data-note { color: #97a7a0; font-size: 10px; }
.dashboard-state { display: flex; align-items: center; gap: 12px; padding: 13px 16px; border: 1px solid #dce5dd; border-radius: 12px; color: #60766d; background: #f7faf5; font-size: 12px; }.dashboard-state strong { color: #35564f; }.dashboard-state span { flex: 1; }.dashboard-state button { border: 1px solid #ccdcbf; border-radius: 7px; padding: 5px 10px; color: #456f52; background: white; cursor: pointer; }.dashboard-state.error { border-color: #efd4ca; background: #fff8f5; }.dashboard-state.error strong { color: #a45d4f; }
.dashboard-kpis { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 13px; }.dashboard-kpi { position: relative; min-height: 188px; overflow: hidden; padding: 21px 19px; border: 1px solid #d9e4db; border-radius: 17px; background: rgba(255,255,255,.85); box-shadow: 0 11px 25px rgba(36,68,57,.055); }.dashboard-kpi.kpi-primary { border-color: #cfd67a; background: linear-gradient(145deg, #f2f6b9, #e9ef9d); }.dashboard-kpi.sales-kpi { border-color: #ecd9aa; background: linear-gradient(145deg, #fffdf7, #fbf3df); }.kpi-label { display: flex; align-items: center; gap: 8px; color: #506d65; font-size: 13px; font-weight: 850; }.kpi-symbol { display: grid; width: 26px; height: 26px; place-items: center; border-radius: 8px; color: #31554a; background: #dfe9a3; font-size: 11px; font-weight: 900; }.kpi-symbol.success { color: #277351; background: #dcefe4; }.kpi-symbol.exposure { color: #8b6a2b; background: #faeac1; }.kpi-symbol.click { color: #4a628c; background: #dee9f4; }.dashboard-kpi > strong { display: block; margin: 18px 0 10px; color: #193b39; font-size: clamp(30px, 3vw, 40px); font-weight: 880; letter-spacing: -.055em; }.kpi-foot { display: flex; align-items: center; gap: 5px; color: #82938d; font-size: 10px; }.kpi-foot em { margin-left: auto; color: #8a9a90; font-style: normal; }.trend-positive { color: #3f996d; font-weight: 850; }.trend-negative { color: #c17566; font-weight: 850; }
.kpi-spark { position: absolute; right: 15px; bottom: 17px; display: flex; align-items: end; gap: 4px; height: 47px; opacity: .72; }.kpi-spark i { width: 6px; min-height: 6px; border-radius: 4px 4px 1px 1px; background: #98ac46; }.mini-bars { position: absolute; right: 17px; bottom: 17px; display: flex; align-items: end; gap: 4px; height: 45px; }.mini-bars i { width: 7px; border-radius: 3px 3px 1px 1px; background: #d8b871; }.mini-bars i:nth-child(4), .mini-bars i:nth-child(6) { background: #ba9852; }.green-bars i { background: #7ca987; }.goal-meter { position: absolute; right: 17px; bottom: 22px; width: 70px; height: 6px; overflow: visible; border-radius: 10px; background: #e3e9e7; }.goal-meter span { display: block; height: 100%; border-radius: inherit; background: #7d9dc0; }.goal-meter b { position: absolute; top: -16px; right: 0; color: #66809a; font-size: 10px; }
.secondary-metrics { display: grid; grid-template-columns: auto repeat(4, minmax(0, 1fr)); align-items: center; overflow: hidden; border: 1px solid #dde5de; border-radius: 12px; background: rgba(248,250,247,.75); }.secondary-metrics > span { padding: 13px 16px; color: #99a69f; font-size: 9px; font-weight: 850; letter-spacing: .1em; white-space: nowrap; }.secondary-metrics div { display: flex; justify-content: space-between; align-items: center; gap: 8px; padding: 11px 15px; border-left: 1px solid #e4eae4; }.secondary-metrics small { color: #8b9b94; font-size: 10px; }.secondary-metrics strong { color: #516c65; font-size: 13px; }
.dashboard-grid { display: grid; gap: 13px; }.dashboard-main-grid, .dashboard-bottom-grid { grid-template-columns: minmax(0, 1.55fr) minmax(280px, .75fr); }.trend-only-grid { grid-template-columns: 1fr; }.dashboard-card { min-width: 0; padding: 19px 20px; border: 1px solid #dce5dd; border-radius: 15px; background: rgba(255,255,255,.78); box-shadow: 0 8px 18px rgba(36,68,57,.035); }.dashboard-card-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 15px; }.card-eyebrow { margin: 0 0 5px; color: #9bab9d; font-size: 9px; }.dashboard-card h3 { margin: 0; color: #254542; font-size: 18px; letter-spacing: -.02em; }.dashboard-card-head p:last-child { margin: 4px 0 0; color: #97a6a0; font-size: 11px; }
.trend-card { background: linear-gradient(135deg, #ffffff, #f8fbf6); border-color: #d6e2d8; }.trend-options { display: grid; gap: 5px; justify-items: end; }.metric-switch, .compare-switch { display: flex; gap: 2px; padding: 3px; border-radius: 8px; background: #f1f5f0; }.metric-switch { overflow-x: auto; max-width: 460px; }.metric-switch button, .compare-switch button { padding: 5px 8px; border: 0; border-radius: 6px; color: #78908a; background: transparent; font-size: 10px; font-weight: 750; white-space: nowrap; }.metric-switch button.active, .compare-switch button.active { color: #31554a; background: #e6edaf; }.compare-switch button:disabled { color: #b3beb7; cursor: not-allowed; }.chart-legend { display: flex; align-items: center; gap: 15px; margin: 18px 0 3px 40px; color: #85938f; font-size: 10px; }.chart-legend span { display: inline-flex; align-items: center; gap: 5px; }.chart-legend i { width: 14px; height: 2px; display: inline-block; }.legend-current { background: #72964b; }.legend-compare { background: #c9d3ca; }.chart-legend b { margin-left: auto; color: #618b6a; font-size: 12px; font-weight: 800; }.trend-body { display: grid; grid-template-columns: minmax(0, 1fr) 225px; gap: 22px; align-items: stretch; }.trend-chart-column { min-width: 0; }.line-chart { position: relative; height: 228px; margin-top: 12px; padding-left: 34px; border: 1px solid #edf2e9; border-radius: 13px; background: linear-gradient(180deg, rgba(247,250,242,.96), rgba(255,255,255,.76)); }.line-chart::before { position: absolute; content: ''; inset: 13px 0 34px 34px; border-radius: 8px; background: repeating-linear-gradient(to bottom, rgba(218,228,216,.72) 0, rgba(218,228,216,.72) 1px, transparent 1px, transparent 25%); }.line-chart svg { position: absolute; inset: 13px 0 33px 34px; width: calc(100% - 34px); height: calc(100% - 46px); overflow: visible; }.chart-area { fill: url(#trend-area-gradient); }.chart-line { fill: none; stroke: #71994f; stroke-width: 2.1; stroke-linecap: round; stroke-linejoin: round; vector-effect: non-scaling-stroke; }.chart-line.compare { stroke: #b8c9bd; stroke-dasharray: 4 4; stroke-width: 1.6; }.chart-point { fill: #fbfdf7; stroke: #6d914c; stroke-width: 1.6; filter: url(#trend-point-shadow); vector-effect: non-scaling-stroke; }.chart-y-axis { position: absolute; top: 8px; bottom: 34px; left: 0; display: flex; flex-direction: column; justify-content: space-between; color: #9aaa9f; font-size: 9px; }.chart-x-axis { position: absolute; right: 0; bottom: 9px; left: 34px; display: flex; justify-content: space-between; gap: 6px; color: #9aaa9f; font-size: 9px; overflow: hidden; }.chart-x-axis span { max-width: 100px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.trend-comparison-panel { display: grid; align-content: start; gap: 9px; margin-top: 12px; padding: 13px; border: 1px solid #e3e9da; border-radius: 13px; background: #f7f9f0; }
.chart-point-layer { position: absolute; z-index: 2; inset: 24px 0 50px 34px; pointer-events: none; }.chart-point-dot { position: absolute; display: block; width: 12px; height: 12px; border: 2px solid #6d914c; border-radius: 50%; background: #fbfdf7; box-shadow: 0 2px 5px rgba(81, 111, 62, .2); transform: translate(-50%, -50%); }
.insight-card { background: #f3f6df; border-color: #e1e8b8; }.insight-score { display: grid; width: 34px; height: 34px; place-items: center; border-radius: 11px; color: #557244; background: #e2edb0; font-size: 11px; font-weight: 850; }.insight-feature { display: flex; gap: 11px; align-items: flex-start; margin: 23px 0 20px; padding: 13px 12px; border-radius: 11px; background: rgba(255,255,255,.58); }.insight-icon { display: grid; flex: 0 0 30px; width: 30px; height: 30px; place-items: center; border-radius: 9px; color: #4f815a; background: #dbeaba; font-size: 19px; font-weight: 850; }.insight-feature strong { color: #3d6148; font-size: 12px; }.insight-feature p { margin: 4px 0 0; color: #7d9080; font-size: 11px; line-height: 1.5; }.insight-list { display: grid; gap: 11px; }.insight-list div { display: flex; justify-content: space-between; align-items: center; padding-bottom: 9px; border-bottom: 1px solid rgba(151,169,114,.2); }.insight-list span { color: #92a18b; font-size: 11px; }.insight-list strong { color: #405f4a; font-size: 12px; }.insight-action { width: 100%; margin-top: 17px; padding: 0; border: 0; color: #527e5d; background: transparent; text-align: left; font-size: 11px; font-weight: 850; cursor: pointer; }.insight-action span { float: right; font-size: 17px; line-height: 11px; }
.platform-filter { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 3px; max-width: 320px; }.platform-filter button { padding: 5px 7px; border-radius: 6px; font-size: 10px; font-weight: 750; }.platform-filter button.active { color: #35564b; background: #e7efb0; }.platform-table-wrap { overflow-x: auto; margin-top: 19px; }table { width: 100%; min-width: 620px; border-collapse: collapse; }th { padding: 0 8px 10px; color: #9aa9a1; font-size: 9px; font-weight: 750; text-align: right; }th:first-child, td:first-child { text-align: left; }td { padding: 12px 8px; border-top: 1px solid #edf1ed; color: #667b75; font-size: 11px; text-align: right; }td strong { color: #35564f; font-size: 11px; }.sales-value { color: #9a712e; font-weight: 850; }.platform-avatar { display: inline-grid; width: 25px; height: 25px; place-items: center; margin-right: 7px; border-radius: 7px; color: #68752a; background: #e9efaf; font-size: 8px; font-weight: 900; vertical-align: middle; }.delta-positive { color: #489465; font-weight: 800; }.delta-negative { color: #c17566; font-weight: 800; }.empty-row { padding: 28px 8px; color: #9aa9a1; text-align: center; }
.ai-content-card { background: linear-gradient(145deg, #fbfcf4, #f3f7e7); border-color: #dfe8bd; }.ai-content-overview { display: flex; gap: 11px; align-items: flex-start; margin: 20px 0 16px; padding: 13px 14px; border: 1px solid rgba(191, 207, 137, .42); border-radius: 11px; background: rgba(229, 239, 182, .35); }.ai-content-overview-icon { display: grid; flex: 0 0 30px; width: 30px; height: 30px; place-items: center; border-radius: 9px; color: #5e7c40; background: #e2edb0; font-size: 17px; font-weight: 900; }.ai-content-overview strong, .ai-content-insight strong, .ai-content-recommendation strong { color: #3f6249; font-size: 11px; }.ai-content-overview p, .ai-content-insight p, .ai-content-recommendation p { margin: 4px 0 0; color: #80917f; font-size: 10px; line-height: 1.55; }.ai-content-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }.ai-content-insight { display: grid; grid-template-columns: 29px 1fr; gap: 9px; padding: 12px 11px; border: 1px solid #e6ecd8; border-radius: 10px; background: rgba(255,255,255,.6); }.ai-content-recommendation { display: grid; grid-template-columns: 29px 1fr; gap: 9px; align-items: start; margin-top: 10px; padding: 12px 11px; border-radius: 10px; background: #edf4d8; }.ai-content-recommendation > span { display: grid; width: 29px; height: 29px; place-items: center; border-radius: 8px; color: #557545; background: #e0ebbb; font-size: 17px; font-weight: 900; }
.ai-analysis-grid { grid-template-columns: 1fr; }.ai-analysis-suite-card { background: linear-gradient(135deg, #fbfcf6, #f1f6e4); border-color: #dce6b9; }.ai-analysis-suite-body { display: grid; grid-template-columns: minmax(230px, .72fr) minmax(0, 1.65fr); gap: 13px; margin-top: 20px; }.ai-analysis-suite-body .ai-content-overview { height: 100%; margin: 0; }.ai-analysis-suite-body .ai-content-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }.ai-analysis-suite-body .ai-content-insight { min-height: 100%; }.ai-analysis-footnote { display: flex; align-items: center; gap: 8px; margin-top: 13px; padding-top: 11px; border-top: 1px solid #e6ecd8; color: #99a695; font-size: 9px; }.ai-analysis-footnote strong { color: #6c866b; font-size: 9px; font-weight: 750; }.ai-analysis-footnote em { margin-left: auto; color: #a6b0a5; font-style: normal; }
.ai-overview-stats { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 7px; margin-top: 14px; }.ai-overview-stats span { display: grid; gap: 3px; padding: 7px 8px; border-radius: 8px; background: rgba(255,255,255,.55); }.ai-overview-stats small { color: #93a18f; font-size: 9px; }.ai-overview-stats b { overflow: hidden; color: #4b6d52; font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }.ai-report-panel { min-width: 0; padding: 12px 13px; border: 1px solid #e4ead7; border-radius: 11px; background: rgba(255,255,255,.45); }.ai-report-panel-head { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; padding-bottom: 9px; border-bottom: 1px solid #e8ede0; }.ai-report-panel-head strong { color: #4c6a51; font-size: 11px; }.ai-report-panel-head small { color: #a0ada0; font-size: 9px; }.ai-report-list { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); column-gap: 16px; }.ai-report-row { display: grid; grid-template-columns: 29px 1fr; gap: 9px; align-items: start; min-width: 0; padding: 11px 0; border-bottom: 1px solid #edf1e9; }.ai-report-row:nth-last-child(-n+2) { border-bottom: 0; }.ai-report-row-title { display: flex; align-items: center; gap: 7px; min-width: 0; }.ai-report-row-title strong { overflow: hidden; color: #46664d; font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }.ai-report-row-title em { flex: 0 0 auto; padding: 2px 5px; border-radius: 4px; color: #829674; background: #edf4d8; font-size: 8px; font-style: normal; }.ai-report-row p { margin: 4px 0 0; color: #81917f; font-size: 10px; line-height: 1.5; }
.ai-analysis-card { background: linear-gradient(145deg, #f6f8e9, #f0f5df); border-color: #dde7b8; }.ai-analysis-badge { display: grid; width: 34px; height: 34px; place-items: center; border-radius: 11px; color: #587447; background: #e2edb0; font-size: 11px; font-weight: 900; }.ai-analysis-list { display: grid; gap: 14px; margin-top: 21px; }.ai-analysis-item { display: grid; grid-template-columns: 29px 1fr; gap: 9px; align-items: start; }.ai-analysis-icon { display: grid; width: 29px; height: 29px; place-items: center; border-radius: 8px; color: #557545; background: #e0ebbb; font-size: 10px; font-weight: 900; }.ai-analysis-item strong { display: block; margin: 1px 0 4px; color: #3b6049; font-size: 11px; line-height: 1.3; }.ai-analysis-item p { margin: 0; color: #81927f; font-size: 10px; line-height: 1.55; }.activity-empty { color: #9aa9a1; font-size: 11px; }
.primary-kpis .dashboard-kpi { min-height: 148px; padding: 14px 16px; }.primary-kpis .dashboard-kpi > strong { margin: 11px 0 7px; font-size: clamp(27px, 2.4vw, 33px); }.primary-kpis .kpi-label { font-size: 12px; }.primary-kpis .kpi-symbol { width: 23px; height: 23px; }.primary-kpis .kpi-foot { font-size: 9px; }.primary-kpis .kpi-spark, .primary-kpis .mini-bars { bottom: 12px; }.primary-kpis .goal-meter { bottom: 16px; }.secondary-metrics > span, .secondary-metrics div { padding-top: 8px; padding-bottom: 8px; }.secondary-metrics strong { font-size: 12px; }.trend-card { padding-top: 32px; padding-bottom: 32px; }.trend-card .line-chart { height: 320px; margin-top: 23px; }.trend-card .line-chart::before { inset: 24px 0 51px 34px; }.trend-card .line-chart svg { inset: 24px 0 50px 34px; height: calc(100% - 74px); }.trend-card .chart-y-axis { top: 18px; bottom: 51px; }.trend-card .chart-x-axis { bottom: 16px; }
@media (max-width: 1120px) { .dashboard-kpis { grid-template-columns: repeat(2, minmax(0, 1fr)); }.secondary-metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }.secondary-metrics > span { display: none; }.secondary-metrics div:nth-child(odd) { border-left: 0; }.dashboard-main-grid, .dashboard-bottom-grid { grid-template-columns: 1fr; }.ai-analysis-suite-body { grid-template-columns: 1fr; } }
@media (max-width: 700px) { .dashboard-intro { align-items: flex-start; flex-direction: column; }.dashboard-controls { width: 100%; justify-items: stretch; }.period-switch { justify-content: space-between; }.period-switch button { flex: 1; }.dashboard-kpis, .secondary-metrics { grid-template-columns: 1fr; }.secondary-metrics div { border-top: 1px solid #e4eae4; border-left: 0; }.dashboard-card { padding: 16px 14px; }.trend-card { padding-top: 23px; padding-bottom: 23px; }.trend-card .line-chart { height: 250px; margin-top: 17px; }.trend-options { justify-items: start; max-width: 100%; overflow-x: auto; }.metric-switch { margin-top: 8px; }.dashboard-card-head { flex-wrap: wrap; }.trend-body { grid-template-columns: 1fr; }.trend-comparison-panel { margin-top: 4px; }.ai-content-grid, .ai-analysis-suite-body .ai-content-grid, .ai-report-list { grid-template-columns: 1fr; }.ai-analysis-footnote { align-items: flex-start; flex-wrap: wrap; }.ai-analysis-footnote em { width: 100%; margin-left: 0; }.chart-legend { margin-left: 30px; }.platform-filter { justify-content: flex-start; max-width: none; }.dashboard-state { align-items: flex-start; flex-wrap: wrap; } }
</style>
