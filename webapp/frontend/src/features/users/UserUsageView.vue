<script setup>
import { computed, onMounted, onBeforeUnmount, ref } from 'vue'
import { apiRequest } from '../../api-client.js'
import UsageDonut from './UsageDonut.vue'
import UsageTrend from './UsageTrend.vue'

function today() {
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date())
}
function daysBefore(value, days) {
  const date = new Date(`${value}T00:00:00Z`)
  date.setUTCDate(date.getUTCDate() - days)
  return date.toISOString().slice(0, 10)
}
const end = ref(today())
const start = ref(daysBefore(end.value, 29))
const search = ref('')
const brand = ref('')
const page = ref(1)
const data = ref(null)
const loading = ref(false)
const error = ref('')
const rankMetric = ref('total_tokens')
let sequence = 0
let detailSequence = 0
const selectedUser = ref(null)
const details = ref(null)
const detailPage = ref(1)
const detailError = ref('')
const detailLoading = ref(false)
const features = { ai_copy: 'AI 文案', dashboard_chat: '数据问答', dashboard_analysis: '数据分析', category_insights: '分类洞察', dashboard_memory: '后台记忆提取', smart_sheet: '智能表格', adapter_probe: '模型连接验证', other: '其他' }
const statuses = { active: '启用', disabled: '停用', locked: '锁定', response: '收到响应', http_error: 'HTTP 错误', transport_error: '连接失败', invalid_response: '无效响应' }
const number = (value) => value == null ? '未知' : new Intl.NumberFormat('zh-CN').format(value)
const timestamp = (value) => value ? new Date(value).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false }) : '从未登录'
const cards = computed(() => {
  const s = data.value?.summary || {}
  return [
    { label: '当前用户', value: s.user_count, note: `启用 ${number(s.enabled_users)}`, color: '#4d78b9', tint: '#edf3fd', icon: 'M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M16 3a4 4 0 0 1 0 8M22 21v-2a4 4 0 0 0-3-3.87', circle: true },
    { label: '期间登录人数', value: s.login_users, note: `成功登录 ${number(s.login_count)} 次`, metric: 'login_users', trendLabel: '每日登录人数 · 跨天不去重', color: '#528b78', tint: '#edf6f1', icon: 'M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4M10 17l5-5-5-5M15 12H3' },
    { label: '发布任务', value: s.publish_count, note: `成功 ${number(s.publish_succeeded)} · 失败 ${number(s.publish_failed)}`, metric: 'publish_count', trendLabel: '每日创建任务', color: '#bf914b', tint: '#fbf4e9', icon: 'M12 16V3M7 8l5-5 5 5M4 14v5a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-5' },
    { label: '文案生成记录', value: s.copy_count, note: '按保存记录计数', metric: 'copy_count', trendLabel: '每日生成记录', color: '#609caa', tint: '#edf5f7', icon: 'M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8zM14 2v6h6M8 13h8M8 17h5' },
    { label: '已知 Token', value: s.total_tokens, note: `输入 ${number(s.input_tokens)} · 输出 ${number(s.output_tokens)}`, metric: 'total_tokens', trendLabel: '每日已知 Token', color: '#9276b3', tint: '#f3eef9', icon: 'M12 3l2.7 5.5 6.1.9-4.4 4.3 1 6.1-5.4-2.9-5.4 2.9 1-6.1L3.2 9.4l6.1-.9z' },
    { label: '模型请求', value: s.request_count, note: `用量不完整 ${number(s.unknown_usage_count)} 次`, metric: 'request_count', trendLabel: '每日请求 · 包含重试', color: '#718496', tint: '#eef2f6', icon: 'M8 6h8M8 18h8M6 8v8M18 8v8M9 9h6v6H9zM9 3v3M15 3v3M9 18v3M15 18v3M3 9h3M3 15h3M18 9h3M18 15h3' },
  ]
})
const palette = ['#356957', '#bd8a35', '#528e9b', '#8d78a3', '#8b9c44', '#bb7161', '#71858b', '#746351']
const rankMetrics = { total_tokens: '已知 Token', publish_count: '发布任务', copy_count: '文案生成记录', login_count: '登录次数' }
const rankedUsers = computed(() => data.value?.rankings?.[rankMetric.value] || [])
const rankMax = computed(() => Math.max(1, ...rankedUsers.value.map(row => row.value)))
const stateLabels = { succeeded: '成功', failed: '失败', queued: '等待', running: '运行中', cancelling: '取消中', cancelled: '已取消', uncertain: '结果不确定', unknown: '未知状态' }
const stateColors = { succeeded: '#356957', failed: '#bb7161', queued: '#bd8a35', running: '#528e9b', cancelling: '#8d78a3', cancelled: '#9aa79c', uncertain: '#8b9c44' }
const publishSegments = computed(() => Object.entries(data.value?.publish_statuses || {}).map(([status, value]) => ({ label: stateLabels[status] || status, value, color: stateColors[status] || '#71858b' })))
function tokenSegments(key) {
  const grouped = new Map()
  for (const row of data.value?.token_breakdown || []) {
    const label = key === 'model' ? `${row.provider} / ${row.model}` : features[row.feature] || row.feature
    grouped.set(label, (grouped.get(label) || 0) + row.total_tokens)
  }
  const items = [...grouped].sort((a, b) => b[1] - a[1])
  const shown = items.slice(0, 6)
  if (items.length > 6) shown.push(['其他', items.slice(6).reduce((sum, row) => sum + row[1], 0)])
  return shown.map(([label, value], index) => ({ label, value, color: palette[index] }))
}
const modelSegments = computed(() => tokenSegments('model'))
const featureSegments = computed(() => tokenSegments('feature'))

async function load(nextPage = 1) {
  const id = ++sequence
  loading.value = true
  error.value = ''
  selectedUser.value = null
  ++detailSequence
  detailLoading.value = false
  try {
    const query = new URLSearchParams({ start_date: start.value, end_date: end.value, search: search.value, brand: brand.value, page: String(nextPage), page_size: '20' })
    const result = await apiRequest(`/api/admin/usage?${query}`)
    if (id !== sequence) return
    data.value = result
    page.value = nextPage
  } catch (err) {
    if (id === sequence) { error.value = err.message; data.value = null }
  } finally {
    if (id === sequence) loading.value = false
  }
}
function preset(days) {
  end.value = today()
  start.value = daysBefore(end.value, days - 1)
  load()
}
async function inspect(user, nextPage = 1) {
  const id = ++detailSequence
  selectedUser.value = user
  details.value = null
  detailError.value = ''
  detailLoading.value = true
  try {
    const query = new URLSearchParams({ user_id: user.id, start_date: data.value.start_date, end_date: data.value.end_date, page: String(nextPage) })
    const result = await apiRequest(`/api/admin/usage/requests?${query}`)
    if (id === detailSequence) { details.value = result; detailPage.value = nextPage }
  } catch (err) {
    if (id === detailSequence) detailError.value = err.message
  } finally {
    if (id === detailSequence) detailLoading.value = false
  }
}
onMounted(() => load())
onBeforeUnmount(() => { ++sequence; ++detailSequence })
</script>

<template>
  <div class="usage-view">
    <section class="usage-panel">
      <div class="usage-heading"><div><p class="usage-eyebrow">USER ACTIVITY</p><h2>用户使用看板</h2><p>按北京时间统计 · 仅管理员可见</p></div><div class="usage-presets"><button :disabled="loading" @click="preset(7)">最近 7 天</button><button :disabled="loading" @click="preset(30)">最近 30 天</button></div></div>
      <form class="usage-filters" @submit.prevent="load()">
        <label>开始日期<input v-model="start" type="date" required :max="end" /></label>
        <label>结束日期<input v-model="end" type="date" required :min="start" /></label>
        <label>用户<input v-model="search" maxlength="100" placeholder="用户名 / 显示名称" /></label>
        <label>用户所属品牌<select v-model="brand"><option value="">全部品牌</option><option v-for="item in data?.brands || []" :key="item" :value="item">{{ item }}</option></select></label>
        <button class="usage-primary" type="submit" :disabled="loading">{{ loading ? '读取中…' : '查询 / 刷新' }}</button>
      </form>
    </section>
    <p v-if="error" role="alert" class="usage-error">{{ error }}</p>
    <p v-if="loading" role="status">正在读取使用统计…</p>
    <template v-if="data">
      <div :class="{ 'usage-loading': loading }" :aria-busy="loading">
        <p class="usage-range">当前结果：{{ data.start_date }} 至 {{ data.end_date }} · {{ data.total }} 位用户（匹配筛选条件）</p>
        <div class="usage-cards">
          <section v-for="card in cards" :key="card.label" class="usage-panel usage-card" :style="{ '--metric-color': card.color, '--metric-tint': card.tint }">
            <div class="usage-metric-heading">
              <span class="usage-metric-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><path :d="card.icon" /><circle v-if="card.circle" cx="9" cy="7" r="4" /></svg></span>
              <div class="usage-metric-main"><span class="usage-metric-label">{{ card.label }}</span><strong>{{ number(card.value) }}</strong></div>
            </div>
            <small class="usage-metric-note">{{ card.note }}</small>
            <UsageTrend v-if="card.metric" :rows="data.daily" :metric="card.metric" :label="card.trendLabel" :color="card.color" />
            <div v-else class="usage-user-snapshot">
              <div class="usage-user-track" role="img" :aria-label="`当前 ${number(data.summary.user_count)} 位用户，启用 ${number(data.summary.enabled_users)} 位`"><div :style="{ width: `${data.summary.user_count ? 100 * data.summary.enabled_users / data.summary.user_count : 0}%` }"></div></div>
              <span>当前状态 · 非历史趋势</span>
            </div>
          </section>
        </div>
        <details class="usage-daily-details"><summary>查看每日数值</summary><div class="usage-table-wrap"><table><thead><tr><th>日期</th><th>登录人数</th><th>发布任务</th><th>文案生成记录</th><th>已知 Token</th><th>模型请求</th></tr></thead><tbody><tr v-for="day in data.daily" :key="day.date"><td>{{ day.date }}</td><td>{{ number(day.login_users) }}</td><td>{{ number(day.publish_count) }}</td><td>{{ number(day.copy_count) }}</td><td>{{ number(day.total_tokens) }}</td><td>{{ number(day.request_count) }}</td></tr></tbody></table></div></details>
        <div class="usage-visual-grid">
          <section class="usage-panel"><h3>发布任务状态分布</h3><p class="usage-subtitle">按所选期间创建任务的当前状态统计</p><UsageDonut :items="publishSegments" label="发布任务状态分布" /></section>
          <section class="usage-panel">
            <div class="usage-heading"><h3>用户使用排行</h3><select v-model="rankMetric" aria-label="用户排行指标"><option v-for="(label, key) in rankMetrics" :key="key" :value="key">{{ label }}</option></select></div>
            <p class="usage-subtitle">匹配筛选条件的全部用户 · 前 10 名 · {{ rankMetrics[rankMetric] }}</p>
            <div class="usage-ranking"><div v-for="(user, index) in rankedUsers" :key="user.id" class="usage-rank-row"><span class="usage-rank-number">{{ String(index + 1).padStart(2, '0') }}</span><div class="usage-rank-content"><div><span :title="user.username">{{ user.name }}</span><b>{{ number(user.value) }}</b></div><div class="usage-bar-track"><div class="usage-bar" :style="{ width: `${100 * user.value / rankMax}%` }"></div></div></div></div><p v-if="!rankedUsers.length" class="usage-empty">所选期间暂无该指标的使用记录</p></div>
            <p v-if="rankMetric === 'total_tokens'" class="usage-subtitle">仅比较已知 Token，用量缺失可能影响排名。</p>
          </section>
          <section class="usage-panel"><h3>Token 按模型分布</h3><p class="usage-subtitle">占比以已知总 Token 为分母</p><UsageDonut :items="modelSegments" label="模型已知 Token 分布" /></section>
          <section class="usage-panel"><h3>Token 按功能分布</h3><p class="usage-subtitle">包含后台调用与连接验证</p><UsageDonut :items="featureSegments" label="功能已知 Token 分布" /></section>
        </div>
        <p v-if="data.summary.unknown_usage_count" class="usage-coverage">用量覆盖提示：{{ number(data.summary.request_count) }} 次模型请求中，有 {{ number(data.summary.unknown_usage_count) }} 次用量不完整；缺失部分未计入 Token 图表，图中占比不代表完整消耗占比。</p>
        <section class="usage-panel">
          <h3>用户明细</h3>
          <div class="usage-table-wrap"><table><thead><tr><th>用户 / 品牌</th><th>状态</th><th>最近登录</th><th>登录次数</th><th>发布 / 成功 / 失败</th><th>文案记录</th><th>输入 / 输出 Token</th><th>已知总 Token</th><th>用量不完整请求</th><th>操作</th></tr></thead><tbody><tr v-for="user in data.users" :key="user.id"><td><b>{{ user.display_name || user.username }}</b><small>{{ user.username }} · {{ user.brand_name || '未绑定品牌' }}</small></td><td>{{ statuses[user.status] || user.status }}</td><td>{{ timestamp(user.last_login_at) }}</td><td>{{ number(user.login_count) }}</td><td>{{ number(user.publish_count) }} / {{ number(user.publish_succeeded) }} / {{ number(user.publish_failed) }}</td><td>{{ number(user.copy_count) }}</td><td>{{ number(user.input_tokens) }} / {{ number(user.output_tokens) }}</td><td>{{ number(user.total_tokens) }}</td><td>{{ number(user.unknown_usage_count) }} / {{ number(user.request_count) }}</td><td><button :disabled="loading || detailLoading" @click="inspect(user)">调用明细</button></td></tr><tr v-if="!data.users.length"><td colspan="10">暂无符合条件的用户</td></tr></tbody></table></div>
          <div class="usage-pagination"><span>第 {{ page }} / {{ Math.max(1, Math.ceil(data.total / 20)) }} 页</span><button :disabled="loading || page <= 1" @click="load(page - 1)">上一页</button><button :disabled="loading || page * 20 >= data.total" @click="load(page + 1)">下一页</button></div>
        </section>
        <section v-if="selectedUser" class="usage-panel">
          <div class="usage-heading"><h3>{{ selectedUser.display_name || selectedUser.username }} · 模型调用明细</h3><button @click="selectedUser = null; ++detailSequence">收起</button></div>
          <p v-if="detailLoading" role="status">读取中…</p><p v-if="detailError" role="alert" class="usage-error">{{ detailError }}</p>
          <template v-if="details"><div class="usage-table-wrap"><table><thead><tr><th>时间（北京时间）</th><th>模型 / 功能</th><th>响应状态</th><th>输入</th><th>输出</th><th>总 Token</th><th>缓存输入</th></tr></thead><tbody><tr v-for="row in details.items" :key="row.id"><td>{{ timestamp(row.created_at) }}</td><td>{{ row.provider }} / {{ row.model }}<small>{{ features[row.feature] || row.feature }}</small></td><td>{{ statuses[row.status] || row.status }}</td><td>{{ number(row.input_tokens) }}</td><td>{{ number(row.output_tokens) }}</td><td>{{ number(row.total_tokens) }}</td><td>{{ number(row.cached_input_tokens) }}</td></tr><tr v-if="!details.items.length"><td colspan="7">所选期间暂无调用记录</td></tr></tbody></table></div><div class="usage-pagination"><span>共 {{ details.total }} 次请求 · 第 {{ detailPage }} 页</span><button :disabled="detailLoading || detailPage <= 1" @click="inspect(selectedUser, detailPage - 1)">上一页</button><button :disabled="detailLoading || detailPage * 20 >= details.total" @click="inspect(selectedUser, detailPage + 1)">下一页</button></div></template>
        </section>
        <section class="usage-panel"><h3>模型与功能用量</h3><div class="usage-table-wrap"><table><thead><tr><th>供应商 / 模型</th><th>功能</th><th>请求数</th><th>已知输入</th><th>已知输出</th><th>已知总 Token</th><th>用量不完整请求</th></tr></thead><tbody><tr v-for="row in data.token_breakdown" :key="`${row.provider}:${row.model}:${row.feature}`"><td>{{ row.provider }} / {{ row.model }}</td><td>{{ features[row.feature] || row.feature }}</td><td>{{ number(row.request_count) }}</td><td>{{ number(row.input_tokens) }}</td><td>{{ number(row.output_tokens) }}</td><td>{{ number(row.total_tokens) }}</td><td>{{ number(row.unknown_usage_count) }}</td></tr><tr v-if="!data.token_breakdown.length"><td colspan="7">所选期间暂无模型用量记录</td></tr></tbody></table></div></section>
      </div>
      <section class="usage-panel usage-notes"><h3>统计口径</h3><p>Token 采集开始于 {{ timestamp(data.collection_started_at) }}。仅统计本系统接入采集后的调用，包含后台记忆、连接验证与自动重试；缓存命中未实际调用模型时不增加请求数。</p><p>已知 Token 为服务返回的用量合计，不完整或未知用量不按零消耗解释。输入与输出仅累加已知部分，不能据此推算账单金额。</p><p>用户总数与启用数是当前状态；登录人数按成功登录去重，不能等同实际活跃人数。删除账号会影响历史统计；文案按当前保留的生成记录计数，不等于模型请求次数。品牌筛选按用户当前所属品牌，不表示每次调用的业务品牌。</p><p>发布任务按创建日期筛选、按当前状态统计，仅覆盖保留记录；已清理任务无法追溯。成功、失败以外的状态包含等待、运行、取消及结果不确定等。</p><p v-for="warning in data.warnings" :key="warning" class="usage-error">{{ warning }}</p></section>
    </template>
  </div>
</template>

<style scoped>
.usage-view { display: grid; gap: 18px; color: #183033; min-width: 0; }
.usage-view > div { min-width: 0; }
.usage-view > div > section { margin-top: 18px; }
.usage-visual-grid { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 16px; margin-top: 18px; }
.usage-subtitle { font-size: 11px; color: #6b7b70; line-height: 1.7; }
.usage-ranking { display: grid; gap: 17px; margin: 22px 0; }
.usage-rank-row { display: flex; align-items: center; gap: 12px; } .usage-rank-number { color: #8a9a8d; font-size: 12px; font-variant-numeric: tabular-nums; }
.usage-rank-content { flex: 1; min-width: 0; } .usage-rank-content > div:first-child { display: flex; justify-content: space-between; gap: 12px; margin-bottom: 8px; font-size: 12px; } .usage-rank-content span { overflow-wrap: anywhere; }
.usage-bar-track { height: 8px; background: #eaf0e5; border-radius: 5px; overflow: hidden; } .usage-bar { height: 100%; border-radius: 5px; background: linear-gradient(90deg,#548b70,#a9b86c); min-width: 2px; }
.usage-empty { font-size: 12px; color: #6b7b70; min-height: 140px; display: grid; place-items: center; }
.usage-coverage { margin-top: 16px; padding: 13px 16px; color: #82632f; background: #fbf5e7; border: 1px solid #e8dbbc; border-radius: 10px; font-size: 12px; line-height: 1.8; }
.usage-panel { padding: 22px; border: 1px solid #d8e1d9; border-radius: 15px; background: rgba(252,253,249,.94); box-shadow: 0 10px 30px rgba(29,65,56,.04); min-width: 0; }
.usage-heading { display: flex; align-items: center; justify-content: space-between; gap: 16px; flex-wrap: wrap; }
h2, h3, p { margin: 0; } h2 { font-size: 24px; } h3 { font-size: 16px; margin-bottom: 14px; }
.usage-heading p { color: #66796c; font-size: 12px; margin: 6px 0; }
.usage-heading .usage-eyebrow { font-size: 10px; letter-spacing: .15em; }
.usage-filters { display: flex; flex-wrap: wrap; align-items: end; gap: 12px; margin-top: 20px; }
label { display: grid; gap: 7px; font-size: 12px; color: #52675c; flex: 1 1 145px; }
input, select, button { font: inherit; border: 1px solid #ccd8cd; border-radius: 8px; padding: 9px 12px; background: #fff; color: #294d40; min-width: 0; }
button { cursor: pointer; font-size: 12px; } button:disabled { opacity: .5; cursor: default; } .usage-primary { color: white; background: #315e4d; }
.usage-presets { display: flex; gap: 8px; }
.usage-range { font-size: 12px; color: #66796c; margin: 0 0 12px; }
.usage-cards { display: grid; grid-template-columns: repeat(6,minmax(0,1fr)); gap: 12px; }
.usage-card { display: flex; flex-direction: column; padding: 16px 14px 12px; border-radius: 12px; gap: 10px; overflow: hidden; }
.usage-metric-heading { display: flex; align-items: flex-start; gap: 10px; min-width: 0; }
.usage-metric-icon { display: grid; place-items: center; flex: 0 0 34px; height: 34px; color: var(--metric-color); background: var(--metric-tint); border-radius: 10px; }
.usage-metric-icon svg { width: 21px; height: 21px; fill: none; stroke: currentColor; stroke-width: 1.7; stroke-linecap: round; stroke-linejoin: round; }
.usage-metric-main { min-width: 0; }
.usage-metric-label { display: block; color: #66776b; font-size: 11px; line-height: 1.5; }
.usage-card strong { display: block; margin-top: 4px; font-size: clamp(20px,1.6vw,27px); font-variant-numeric: tabular-nums; line-height: 1.15; letter-spacing: -.035em; overflow-wrap: anywhere; }
small { display: block; color: #6b7b70; font-size: 11px; margin-top: 5px; }
.usage-card .usage-metric-note { min-height: 30px; margin: 0; font-size: 10px; line-height: 1.5; overflow-wrap: anywhere; }
.usage-user-snapshot { display: flex; flex-direction: column; justify-content: end; gap: 13px; min-height: 88px; margin-top: auto; padding: 0 2px; }
.usage-user-track { height: 7px; background: #e8edf1; border-radius: 8px; overflow: hidden; margin-bottom: 14px; }
.usage-user-track > div { height: 100%; background: var(--metric-color); border-radius: inherit; }
.usage-user-snapshot > span { color: #87968b; font-size: 9px; line-height: 1.5; }
.usage-daily-details { margin-top: 10px; } .usage-daily-details[open] { padding: 12px 16px; background: #fcfdf9; border: 1px solid #d8e1d9; border-radius: 12px; }
.usage-table-wrap { overflow-x: auto; } table { width: 100%; border-collapse: collapse; text-align: left; font-size: 12px; white-space: nowrap; } th { background: #f0f4ed; color: #637668; font-size: 11px; } th, td { padding: 13px 12px; border-bottom: 1px solid #e4e9e1; }
.usage-pagination { display: flex; align-items: center; justify-content: end; flex-wrap: wrap; gap: 10px; margin-top: 16px; font-size: 12px; }
.usage-notes p { font-size: 12px; color: #6b7b70; line-height: 1.8; margin-top: 8px; }
.usage-error, .usage-notes .usage-error { color: #a53d2f; } .usage-loading { opacity: .55; pointer-events: none; } details summary { cursor: pointer; font-size: 12px; padding: 8px 0; }
@media (max-width: 1100px) { .usage-visual-grid { grid-template-columns: 1fr; } }
@media (max-width: 1399px) { .usage-cards { grid-template-columns: repeat(3,minmax(0,1fr)); } }
@media (max-width: 900px) { .usage-cards { grid-template-columns: repeat(2,minmax(0,1fr)); } .usage-panel { padding: 16px; } .usage-card { padding: 16px 14px 12px; } }
@media (max-width: 480px) { .usage-cards { grid-template-columns: 1fr; } }
</style>
