<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { apiRequest } from '../../api-client.js'
import TagAnalysisPanel from './TagAnalysisPanel.vue'
import AssistantRichText from './AssistantRichText.vue'
import { analyzeContent } from './content-analysis.js'

const period = ref('')
const activeMetric = ref('content_viewers')
const comparison = ref('previous')
const loading = ref(true)
const error = ref('')
const data = ref(null)
const aiResult = ref(null)
const aiLoading = ref(false)
const aiError = ref('')
const assistantOpen = ref(false)
const assistantDraft = ref('')
const assistantMessages = ref([])
const assistantConversationId = ref(null)
const assistantBusy = ref(false)
const assistantError = ref('')
let assistantRequest = 0
const assistantScope = ref({ type: 'image', tagId: 'all', label: '全部图文' })
const assistantPreview = (content) => content.replace(/\*\*|__|`|^#{1,3}\s+/gm, '').replace(/\s+/g, ' ').slice(0, 180).trim()
let analysisRequest = 0
const metricOptions = [
  { key: 'content_viewers', label: '查看人数合计' },
  { key: 'impressions', label: '曝光次数' },
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
const comparisonLabel = computed(() => comparison.value === 'previous' ? '较上期' : '较去年同月')
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
  { key: 'previous', label: '较上期', available: comparisons.value.previous_week?.available !== false && Boolean(compareTrend.value.length || comparisons.value.previous_week?.available) },
  { key: 'year', label: '较去年同月', available: comparisons.value.same_period_last_year?.available !== false && Boolean(yearComparisonTrend.value.length || comparisons.value.same_period_last_year?.available) },
])
const contentAnalysis = computed(() => aiResult.value || analyzeContent(data.value))
const aiAnalysis = computed(() => contentAnalysis.value.cards)
const aiContentSummary = computed(() => contentAnalysis.value.summary)
const stateLabel = computed(() => {
  if (loading.value) return '正在同步数据库'
  if (error.value) return '数据库读取失败'
  if (data.value?.configured === false) return '等待配置 MySQL'
  if (data.value?.empty) return '数据库暂无看板数据'
  return '数据库已同步'
})

async function loadDashboard() {
  analysisRequest += 1
  aiResult.value = null
  aiError.value = ''
  aiLoading.value = false
  loading.value = true
  error.value = ''
  try {
    data.value = await apiRequest(`/api/dashboard?period=${encodeURIComponent(period.value || 'latest')}`)
    if (!period.value && data.value.selected_period) period.value = data.value.selected_period
  } catch (requestError) {
    error.value = requestError.message
  } finally {
    loading.value = false
  }
}

async function generateAiAnalysis() {
  const requestId = ++analysisRequest
  aiLoading.value = true
  aiError.value = ''
  try {
    const result = await apiRequest(`/api/dashboard/analysis?period=${encodeURIComponent(period.value)}`, { method: 'POST' })
    if (requestId === analysisRequest) aiResult.value = result
  } catch (requestError) {
    if (requestId === analysisRequest) aiError.value = requestError.message
  } finally {
    if (requestId === analysisRequest) aiLoading.value = false
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

async function loadAssistantHistory() {
  const requestId = ++assistantRequest
  assistantMessages.value = []
  assistantConversationId.value = null
  assistantError.value = ''
  if (!assistantOpen.value || !period.value || period.value !== data.value?.selected_period) return
  const query = new URLSearchParams({ period: period.value, content_type: assistantScope.value.type, tag_id: assistantScope.value.tagId })
  try {
    const history = await apiRequest(`/api/dashboard/chat?${query}`)
    if (requestId === assistantRequest) {
      assistantConversationId.value = history.conversation_id
      assistantMessages.value = history.messages
    }
  } catch (requestError) {
    if (requestId === assistantRequest) assistantError.value = requestError.message
  }
}

async function sendAssistantQuestion() {
  const question = assistantDraft.value.trim()
  if (!question || assistantBusy.value || !assistantConversationId.value) return
  const requestId = assistantRequest
  assistantBusy.value = true
  assistantError.value = ''
  try {
    const reply = await apiRequest('/api/dashboard/chat', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, conversation_id: assistantConversationId.value, period: period.value, content_type: assistantScope.value.type, tag_id: assistantScope.value.tagId }),
    })
    if (requestId === assistantRequest) {
      assistantMessages.value.push({ role: 'user', content: question, evidence: [] }, { role: 'assistant', content: reply.answer, evidence: reply.evidence })
      assistantDraft.value = ''
    }
  } catch (requestError) {
    if (requestId === assistantRequest) assistantError.value = requestError.message
  } finally {
    assistantBusy.value = false
  }
}

watch([assistantOpen, period, assistantScope, () => data.value?.selected_period], loadAssistantHistory)
watch(period, (next) => { if (next && next !== data.value?.selected_period) loadDashboard() })
onMounted(loadDashboard)
</script>

<template>
  <section class="dashboard-view" :class="{ 'assistant-visible': assistantOpen }">
    <div class="dashboard-intro">
      <div>
        <div class="dashboard-kicker"><span class="pulse-dot"></span> {{ data?.brand?.name || 'BRAND' }} DATA · MYSQL LIVE</div>
      </div>
      <div class="dashboard-controls">
        <button class="assistant-open-button" type="button" :aria-expanded="assistantOpen" aria-controls="dashboard-assistant" @click="assistantOpen = true">✦ 问数据助手</button>
        <div class="period-switch" role="tablist" aria-label="数据周期">
          <button v-for="item in periods" :key="item.key" :class="{ active: period === item.key }" type="button" @click="period = item.key">{{ item.label }}</button>
        </div>
        <span class="data-note"><i :class="['status-dot', { loading }]" />{{ stateLabel }} · {{ dateLabel }}</span>
      </div>
    </div>

    <div v-if="error || data?.configured === false || data?.empty" class="dashboard-state" :class="{ error }">
      <strong>{{ error ? '无法加载数据库看板' : data?.configured === false ? '看板尚未连接 MySQL' : '数据库暂无可展示数据' }}</strong>
      <span>{{ error || (data?.configured === false ? `请配置：${(data.missing_settings || []).join('、')}` : '请检查当前品牌在 content_performance 中是否有数据。') }}</span>
      <button v-if="error" type="button" @click="loadDashboard">重试</button>
    </div>

    <div v-if="current" class="dashboard-grid dashboard-main-grid trend-only-grid">
        <article class="dashboard-card trend-card">
          <header class="dashboard-card-head"><div><p class="card-eyebrow">CORE TREND</p><h3>{{ metricLabel }}趋势</h3><p>按下载月份展示；有数据时可与上期或去年同月对比</p></div><div class="trend-options"><div class="metric-switch"><button v-for="metric in metricOptions" :key="metric.key" :class="{ active: activeMetric === metric.key }" type="button" @click="activeMetric = metric.key">{{ metric.label }}</button></div><div class="compare-switch"><button :class="{ active: comparison === 'previous' }" type="button" :disabled="!comparisonOptions[0].available" @click="comparison = 'previous'">较上期</button><button :class="{ active: comparison === 'year' }" type="button" :disabled="!comparisonOptions[1].available" @click="comparison = 'year'">较去年同月</button></div></div></header>
          <div class="trend-body">
            <div class="trend-chart-column">
              <div class="chart-legend"><span><i class="legend-current"></i>{{ dateLabel }}</span><span v-if="comparePoints"><i class="legend-compare"></i>{{ comparisonLabel }}</span><b>{{ formatMetric(activeMetric, valueFor(activeMetric)) }}</b></div>
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
                <p v-else>接入去年同月数据后自动显示</p>
              </div>
            </aside>
          </div>
        </article>

      </div>

    <TagAnalysisPanel :tag-groups="data?.tags" :period-label="dateLabel" @scope-change="assistantScope = $event" />

    <template v-if="current">
      <div class="dashboard-grid dashboard-bottom-grid ai-analysis-grid">
        <article class="dashboard-card ai-analysis-suite-card">
          <header class="dashboard-card-head"><div><p class="card-eyebrow">AI CONTENT ANALYSIS · BETA</p><h3>本周期五维分析</h3><p>评估内容表现与种草链路，查看已有证据及待补数据</p></div><button class="assistant-inline-button" type="button" @click="assistantOpen = true">打开对话助手</button><button class="ai-generate-button" type="button" :disabled="aiLoading || loading" @click="generateAiAnalysis">{{ aiLoading ? '分析中…' : aiResult ? '重新分析' : '生成 AI 分析' }}</button></header>
          <p v-if="aiError" class="ai-analysis-error" role="alert">{{ aiError }}</p>
          <div class="ai-analysis-suite-body">
            <div class="ai-content-overview"><span class="ai-content-overview-icon">✦</span><div><strong>本周期分析结论</strong><p>{{ aiContentSummary }}</p><div class="ai-overview-stats"><span><small>查看人数合计</small><b>{{ formatNumber(valueFor('content_viewers')) }}</b></span><span><small>商品点击人数合计</small><b>{{ formatNumber(valueFor('product_click_users')) }}</b></span><span><small>种草成交金额</small><b>{{ formatMoney(valueFor('revenue')) }}</b></span></div></div></div>
            <div class="ai-report-panel"><div class="ai-report-panel-head"><strong>五个维度 · 判断与动作</strong><small>根据当前看板可用字段分析</small></div><div class="ai-report-list"><div v-for="item in aiAnalysis" :key="item.title" class="ai-report-row"><span class="ai-analysis-icon">{{ item.icon }}</span><div><div v-if="item.dimension" class="ai-dimension-label">{{ item.dimension }}</div><div class="ai-report-row-title"><strong>{{ item.title }}</strong><em>{{ item.tag }}</em></div><p>{{ item.text }}</p><details v-if="item.evidence?.length" class="ai-evidence"><summary>查看数据依据</summary><p v-for="(entry, index) in item.evidence" :key="index">{{ entry }}</p></details></div></div><div v-if="!aiAnalysis.length" class="activity-empty">连接数据库后，将展示五个维度的分析与数据覆盖情况。</div></div></div>
          </div>
          <div class="ai-analysis-footnote"><span>数据状态</span><strong>{{ data?.source?.latest_period ? `已基于 ${dateLabel} 的品牌数据分析` : '等待数据库数据' }}</strong><em>{{ aiResult ? `AI 分析 · ${aiResult.provider} · ${aiResult.model}` : '当前为规则分析，未调用 AI 模型' }}；汇总人数未跨内容去重；下载周期不等于发布时间；种草成交不等于直接购买归因</em></div>
        </article>
      </div>
    </template>

    <div v-if="assistantOpen" class="assistant-backdrop" @click="assistantOpen = false"></div>
    <aside id="dashboard-assistant" class="assistant-drawer" :class="{ open: assistantOpen }" :aria-hidden="!assistantOpen" aria-label="问数据助手" :inert="!assistantOpen">
      <header class="assistant-drawer-header"><div class="assistant-header-row"><div><small>DATA ASSISTANT · LIVE</small><h3>问数据助手</h3></div><button type="button" aria-label="关闭数据助手" @click="assistantOpen = false">×</button></div><div class="assistant-scope"><span>当前分析范围</span><strong>{{ data?.brand?.name || '当前品牌' }} · {{ dateLabel || '未选择周期' }} · {{ assistantScope.label }}</strong><small>切换看板周期或标签后，范围会同步更新。</small></div></header>
      <div class="assistant-conversation">
        <div class="assistant-welcome"><span>✦</span><h4>从当前数据开始提问</h4><p>可以围绕趋势、内容分类或具体作品继续追问。回答会附上本次查询的数据依据。</p></div>
        <div class="assistant-suggestions"><button v-for="question in ['哪些内容值得继续做？', '与上期相比，变化最大的是哪里？', '这个分类有哪些高点击作品？']" :key="question" type="button" @click="assistantDraft = question">{{ question }}</button></div>
        <div v-for="(message, index) in assistantMessages" :key="index" class="assistant-message" :class="message.role"><details v-if="message.role === 'assistant' && message.content.length > 500" class="assistant-long-answer"><summary><span class="assistant-answer-preview">{{ assistantPreview(message.content) }}… 展开完整回答</span><span class="assistant-answer-collapse">收起回答</span></summary><AssistantRichText :text="message.content" /></details><AssistantRichText v-else-if="message.role === 'assistant'" :text="message.content" /><p v-else>{{ message.content }}</p><details v-if="message.evidence?.length"><summary>查看数据依据</summary><pre v-for="(item, evidenceIndex) in message.evidence" :key="evidenceIndex">{{ item.tool }}：{{ JSON.stringify(item.result, null, 2) }}</pre></details></div>
        <div v-if="aiResult && !assistantMessages.length" class="assistant-current-analysis"><strong>本周期已有分析</strong><p>{{ aiResult.summary }}</p><small>来源：当前看板的 AI 内容分析</small></div>
      </div>
      <form class="assistant-compose" @submit.prevent="sendAssistantQuestion"><label for="assistant-question">向数据助手提问</label><textarea id="assistant-question" v-model="assistantDraft" rows="3" placeholder="例如：这个分类为什么点击高？" /><div><small>{{ assistantError || (assistantBusy ? '正在查询数据并生成回答…' : '按当前品牌、周期和标签范围查询') }}</small><button type="submit" :disabled="assistantBusy || !assistantDraft.trim() || !assistantConversationId">{{ assistantBusy ? '处理中' : '发送' }}</button></div></form>
    </aside>
  </section>
</template>

<style scoped>
.assistant-open-button, .assistant-inline-button { border: 1px solid #cbdca0; border-radius: 9px; padding: 9px 13px; color: #365a3e; background: #e6efbf; font-weight: 750; cursor: pointer; }
.assistant-inline-button { margin-left: auto; background: #fff; }
.assistant-backdrop { display: none; }
.dashboard-view.assistant-visible { padding-right: 420px; }
.assistant-drawer { position: fixed; z-index: 80; inset: 0 0 0 auto; display: flex; flex-direction: column; width: min(420px, 100vw); height: 100dvh; box-sizing: border-box; border-left: 1px solid #dce6d9; background: #fbfcf7; box-shadow: -14px 0 38px rgba(25, 52, 42, .14); transform: translateX(100%); transition: transform .2s ease; }
.assistant-drawer.open { transform: translateX(0); }
.assistant-drawer-header { padding: 22px 22px 18px; border-bottom: 1px solid #e2e9dc; }
.assistant-header-row { display: flex; align-items: center; justify-content: space-between; }
.assistant-drawer-header small { color: #8b9f83; font-size: 10px; letter-spacing: .12em; }
.assistant-drawer-header h3 { margin: 4px 0 0; color: #294c42; font-size: 20px; }
.assistant-drawer-header button { border: 0; background: transparent; color: #567166; font-size: 27px; cursor: pointer; }
.assistant-scope { display: grid; gap: 5px; margin-top: 20px; }
.assistant-scope span, .assistant-scope small { color: #81927b; font-size: 11px; }
.assistant-scope strong { color: #365a3e; font-size: 13px; }
.assistant-conversation { flex: 1; overflow-y: auto; padding: 20px 16px; }
.assistant-welcome { padding: 18px; border: 1px solid #e1e9da; border-radius: 13px; background: white; }
.assistant-welcome span { color: #86a050; font-size: 20px; }
.assistant-welcome h4 { margin: 9px 0; color: #294c42; }
.assistant-welcome p, .assistant-current-analysis p { color: #6f8378; font-size: 12px; line-height: 1.65; }
.assistant-suggestions { display: grid; gap: 8px; margin: 16px 0; }
.assistant-suggestions button { padding: 10px; border: 1px solid #dde7d2; border-radius: 9px; background: white; color: #456451; text-align: left; cursor: pointer; }
.assistant-message { margin: 12px 0; padding: 12px; border: 1px solid #e1e9da; border-radius: 10px; background: white; color: #3c6248; font-size: 12px; }
.assistant-message.user { margin-left: 25px; background: #eff5dc; }
.assistant-message p { margin: 8px 0; line-height: 1.7; white-space: pre-wrap; }
.assistant-message details { color: #6f8378; }
.assistant-answer-collapse, .assistant-long-answer[open] .assistant-answer-preview { display: none; }
.assistant-long-answer[open] .assistant-answer-collapse { display: inline; }
.assistant-message pre { max-height: 200px; overflow: auto; padding: 8px; border-radius: 7px; background: #f6f8f2; font-size: 10px; white-space: pre-wrap; overflow-wrap: anywhere; }
.assistant-current-analysis { padding: 13px; border-radius: 9px; background: #f1f6df; color: #3c6248; font-size: 12px; }
.assistant-current-analysis small { color: #83937e; }
.assistant-compose { display: grid; gap: 8px; padding: 16px; border-top: 1px solid #e1e9da; }
.assistant-compose label { color: #3c6248; font-size: 12px; font-weight: 750; }
.assistant-compose textarea { box-sizing: border-box; width: 100%; resize: vertical; padding: 10px; border: 1px solid #d3dfd1; border-radius: 9px; background: white; font: inherit; }
.assistant-compose > div { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.assistant-compose small { color: #8d9d91; font-size: 10px; }
.assistant-compose button { border: 0; border-radius: 8px; padding: 9px 15px; background: #dce6b3; color: #5c7458; }
@media (max-width: 900px) { .dashboard-view.assistant-visible { padding-right: 0; } .assistant-backdrop { display: block; position: fixed; inset: 0; z-index: 79; background: rgba(22, 46, 38, .22); } .assistant-drawer { width: min(420px, 100vw); } }
@media (max-width: 700px) { .assistant-drawer { width: 100vw; } }
@media (prefers-reduced-motion: reduce) { .assistant-drawer { transition: none; } }

.ai-generate-button { padding: 9px 14px; border: 1px solid #cbdca0; border-radius: 9px; background: #e2edb0; color: #3f6249; cursor: pointer; font-weight: 700; }
.ai-generate-button:disabled { opacity: .6; cursor: wait; }
.ai-analysis-error { color: #a34730; font-size: 12px; }
.ai-evidence { margin-top: 7px; font-size: 11px; color: #617b61; }
.ai-evidence summary { cursor: pointer; }
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
.ai-analysis-suite-card .ai-content-overview strong { font-size: 14px; }
.ai-analysis-suite-card .ai-content-overview p { color: #627b68; font-size: 14px; line-height: 1.75; }
.ai-analysis-suite-card .ai-report-panel-head strong { font-size: 15px; }
.ai-analysis-suite-card .ai-report-panel-head small { font-size: 12px; }
.ai-analysis-suite-card .ai-report-row-title { flex-wrap: wrap; }
.ai-analysis-suite-card .ai-report-row-title strong { overflow: visible; font-size: 14px; line-height: 1.45; text-overflow: clip; white-space: normal; }
.ai-analysis-suite-card .ai-report-row-title em { font-size: 11px; }
.ai-analysis-suite-card .ai-report-row p { color: #627b68; font-size: 13px; line-height: 1.7; }
.ai-analysis-suite-card .ai-evidence { font-size: 12px; }
.ai-analysis-suite-card .ai-overview-stats small { font-size: 11px; }
.ai-analysis-suite-card .ai-overview-stats b { font-size: 14px; overflow: visible; white-space: normal; overflow-wrap: anywhere; }
.ai-overview-stats { grid-template-columns: 1fr; }
.ai-dimension-label { margin-bottom: 5px; color: #708562; font-size: 11px; font-weight: 700; }
.primary-kpis .dashboard-kpi { min-height: 148px; padding: 14px 16px; }.primary-kpis .dashboard-kpi > strong { margin: 11px 0 7px; font-size: clamp(27px, 2.4vw, 33px); }.primary-kpis .kpi-label { font-size: 12px; }.primary-kpis .kpi-symbol { width: 23px; height: 23px; }.primary-kpis .kpi-foot { font-size: 9px; }.primary-kpis .kpi-spark, .primary-kpis .mini-bars { bottom: 12px; }.primary-kpis .goal-meter { bottom: 16px; }.secondary-metrics > span, .secondary-metrics div { padding-top: 8px; padding-bottom: 8px; }.secondary-metrics strong { font-size: 12px; }.trend-card { padding-top: 32px; padding-bottom: 32px; }.trend-card .line-chart { height: 320px; margin-top: 23px; }.trend-card .line-chart::before { inset: 24px 0 51px 34px; }.trend-card .line-chart svg { inset: 24px 0 50px 34px; height: calc(100% - 74px); }.trend-card .chart-y-axis { top: 18px; bottom: 51px; }.trend-card .chart-x-axis { bottom: 16px; }
@media (max-width: 1120px) { .dashboard-kpis { grid-template-columns: repeat(2, minmax(0, 1fr)); }.secondary-metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }.secondary-metrics > span { display: none; }.secondary-metrics div:nth-child(odd) { border-left: 0; }.dashboard-main-grid, .dashboard-bottom-grid { grid-template-columns: 1fr; }.ai-analysis-suite-body { grid-template-columns: 1fr; } }
@media (max-width: 700px) { .dashboard-intro { align-items: flex-start; flex-direction: column; }.dashboard-controls { width: 100%; justify-items: stretch; }.period-switch { justify-content: space-between; }.period-switch button { flex: 1; }.dashboard-kpis, .secondary-metrics { grid-template-columns: 1fr; }.secondary-metrics div { border-top: 1px solid #e4eae4; border-left: 0; }.dashboard-card { padding: 16px 14px; }.trend-card { padding-top: 23px; padding-bottom: 23px; }.trend-card .line-chart { height: 250px; margin-top: 17px; }.trend-options { justify-items: start; max-width: 100%; overflow-x: auto; }.metric-switch { margin-top: 8px; }.dashboard-card-head { flex-wrap: wrap; }.trend-body { grid-template-columns: 1fr; }.trend-comparison-panel { margin-top: 4px; }.ai-content-grid, .ai-analysis-suite-body .ai-content-grid, .ai-report-list { grid-template-columns: 1fr; }.ai-analysis-footnote { align-items: flex-start; flex-wrap: wrap; }.ai-analysis-footnote em { width: 100%; margin-left: 0; }.chart-legend { margin-left: 30px; }.platform-filter { justify-content: flex-start; max-width: none; }.dashboard-state { align-items: flex-start; flex-wrap: wrap; } }
</style>
