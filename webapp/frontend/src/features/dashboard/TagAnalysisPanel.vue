<script setup>
import { computed, ref } from 'vue'

const activeType = ref('image')
const activeTag = ref('all')

const tagGroups = {
  image: {
    label: '图文内容',
    shortLabel: '图文',
    description: '参考图文内容案例，观察不同内容主题的触达和成交表现。',
    tags: [
      {
        id: 'new-arrivals',
        label: '多品上新',
        description: '新品集中展示',
        color: '#5f7ca4',
        contentCount: 128,
        exposure: 2860000,
        views: 3420000,
        interactions: 186400,
        revenue: 486000,
        delta: 0.24,
        trend: [42, 51, 48, 63, 58, 78],
        samples: [
          { title: '春夏新品九宫格', meta: '9 张图片 · 3 个商品', metric: '互动率 6.8%' },
          { title: '轻户外系列上新', meta: '6 张图片 · 5 个商品', metric: '点击率 4.2%' },
        ],
      },
      {
        id: 'list',
        label: '清单',
        description: '按场景列清单',
        color: '#76955e',
        contentCount: 96,
        exposure: 2120000,
        views: 2780000,
        interactions: 133700,
        revenue: 362000,
        delta: 0.18,
        trend: [35, 39, 47, 44, 58, 65],
        samples: [
          { title: '通勤衣橱必备清单', meta: '8 张图片 · 7 个商品', metric: '收藏率 5.4%' },
          { title: '周末出行打包指南', meta: '7 张图片 · 4 个商品', metric: '点击率 3.8%' },
        ],
      },
      {
        id: 'buyer-show',
        label: '买家秀',
        description: '真实用户穿着',
        color: '#b27a58',
        contentCount: 74,
        exposure: 1960000,
        views: 2380000,
        interactions: 142100,
        revenue: 418000,
        delta: 0.31,
        trend: [31, 45, 42, 55, 67, 73],
        samples: [
          { title: '真实买家上身反馈', meta: '5 张图片 · 2 个商品', metric: '互动率 7.1%' },
          { title: '不同身材试穿对比', meta: '6 张图片 · 3 个商品', metric: '评论率 4.6%' },
        ],
      },
      {
        id: 'kol',
        label: '明星/KOL',
        description: '人物影响力内容',
        color: '#9b6a85',
        contentCount: 42,
        exposure: 2460000,
        views: 3080000,
        interactions: 221400,
        revenue: 596000,
        delta: 0.42,
        trend: [38, 43, 56, 52, 70, 88],
        samples: [
          { title: '明星同款内容拆解', meta: '4 张图片 · 2 个商品', metric: '互动率 8.2%' },
          { title: 'KOL 周末穿搭分享', meta: '5 张图片 · 3 个商品', metric: '成交 ¥18,600' },
        ],
      },
      {
        id: 'styling',
        label: '套版搭配',
        description: '完整造型组合',
        color: '#a18d55',
        contentCount: 68,
        exposure: 1730000,
        views: 2240000,
        interactions: 126800,
        revenue: 389000,
        delta: 0.27,
        trend: [36, 41, 49, 57, 60, 71],
        samples: [
          { title: '一周套版搭配', meta: '9 张图片 · 6 个商品', metric: '加购率 3.9%' },
          { title: '同色系层次搭配', meta: '6 张图片 · 4 个商品', metric: '点击率 4.0%' },
        ],
      },
    ],
  },
  video: {
    label: '视频内容',
    shortLabel: '视频',
    description: '参考短视频类型案例，观察内容类型对播放和转化的贡献。',
    tags: [
      {
        id: 'live-cut',
        label: '直播切片',
        description: '直播高光剪辑',
        color: '#5f7ca4',
        contentCount: 86,
        exposure: 3420000,
        views: 4160000,
        interactions: 302800,
        revenue: 712000,
        delta: 0.36,
        trend: [46, 52, 61, 58, 74, 84],
        samples: [
          { title: '直播间高光切片', meta: '32 秒 · 商品讲解', metric: '完播率 42%' },
          { title: '主播试穿实录', meta: '48 秒 · 2 个商品', metric: '点击率 5.6%' },
        ],
      },
      {
        id: 'white-background',
        label: '白底主图视频',
        description: '商品细节展示',
        color: '#76955e',
        contentCount: 104,
        exposure: 2880000,
        views: 3660000,
        interactions: 254400,
        revenue: 645000,
        delta: 0.28,
        trend: [41, 48, 53, 57, 64, 76],
        samples: [
          { title: '基础款细节展示', meta: '18 秒 · 1 个商品', metric: '完播率 48%' },
          { title: '面料质感近景', meta: '22 秒 · 1 个商品', metric: '点击率 4.8%' },
        ],
      },
      {
        id: 'koc-kol',
        label: 'KOC/KOL',
        description: '达人种草测评',
        color: '#9b6a85',
        contentCount: 58,
        exposure: 3960000,
        views: 4820000,
        interactions: 432000,
        revenue: 1080000,
        delta: 0.52,
        trend: [44, 57, 55, 70, 82, 96],
        samples: [
          { title: 'Polo 松弛感怎么穿', meta: '36 秒 · 达人出镜', metric: '完播率 55%' },
          { title: '达人一周穿搭挑战', meta: '51 秒 · 4 个商品', metric: '成交 ¥36,800' },
        ],
      },
      {
        id: 'creative-styling',
        label: '创意穿搭',
        description: '场景化穿搭表达',
        color: '#b27a58',
        contentCount: 72,
        exposure: 3240000,
        views: 4380000,
        interactions: 391600,
        revenue: 926000,
        delta: 0.44,
        trend: [39, 49, 62, 60, 78, 91],
        samples: [
          { title: '夏日彩色 Polo 穿搭', meta: '43 秒 · 4 人出镜', metric: '互动率 9.6%' },
          { title: '一件单品三种场景', meta: '39 秒 · 3 个商品', metric: '点击率 6.2%' },
        ],
      },
      {
        id: 'visual-3d',
        label: '3D VISUAL',
        description: '三维视觉演示',
        color: '#758cad',
        contentCount: 31,
        exposure: 1860000,
        views: 2520000,
        interactions: 197000,
        revenue: 524000,
        delta: 0.37,
        trend: [28, 34, 43, 52, 64, 78],
        samples: [
          { title: '高效防晒科技演示', meta: '27 秒 · 3D 动画', metric: '完播率 51%' },
          { title: '功能面料可视化', meta: '31 秒 · 商品拆解', metric: '收藏率 6.1%' },
        ],
      },
    ],
  },
}

const activeGroup = computed(() => tagGroups[activeType.value])
const tags = computed(() => activeGroup.value.tags)
const selectedTag = computed(() => tags.value.find((tag) => tag.id === activeTag.value) || null)
const trendTarget = computed(() => selectedTag.value || tags.value.reduce((best, tag) => tag.exposure > best.exposure ? tag : best, tags.value[0]))
const visibleSamples = computed(() => {
  if (selectedTag.value) return selectedTag.value.samples.map((sample) => ({ ...sample, tag: selectedTag.value }))
  return tags.value.flatMap((tag) => tag.samples.slice(0, 1).map((sample) => ({ ...sample, tag }))).slice(0, 5)
})
const summary = computed(() => {
  if (selectedTag.value) return selectedTag.value
  return tags.value.reduce((total, tag) => ({
    contentCount: total.contentCount + tag.contentCount,
    exposure: total.exposure + tag.exposure,
    views: total.views + tag.views,
    interactions: total.interactions + tag.interactions,
    revenue: total.revenue + tag.revenue,
  }), { contentCount: 0, exposure: 0, views: 0, interactions: 0, revenue: 0 })
})
const engagementRate = computed(() => summary.value.views ? summary.value.interactions / summary.value.views : 0)
const maxExposure = computed(() => Math.max(...tags.value.map((tag) => tag.exposure)))
const maxTrend = computed(() => Math.max(...trendTarget.value.trend))
const trendLabels = computed(() => activeType.value === 'image' ? ['第1周', '第2周', '第3周', '第4周', '第5周', '本周'] : ['第1周', '第2周', '第3周', '第4周', '第5周', '本周'])

function selectType(type) {
  activeType.value = type
  activeTag.value = 'all'
}

function formatNumber(value) {
  return new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 0 }).format(Number(value || 0))
}

function formatCompact(value) {
  const number = Number(value || 0)
  if (number >= 10000) return `${(number / 10000).toFixed(number >= 100000 ? 0 : 1)}万`
  return formatNumber(number)
}

function formatMoney(value) {
  const number = Number(value || 0)
  if (number >= 10000) return `¥${(number / 10000).toFixed(number >= 100000 ? 0 : 1)}万`
  return `¥${formatNumber(number)}`
}

function formatPercent(value) {
  return `${(Number(value || 0) * 100).toFixed(1)}%`
}
</script>

<template>
  <section class="tag-analysis-panel" aria-labelledby="tag-analysis-title">
    <header class="tag-analysis-header">
      <div>
        <p class="tag-analysis-eyebrow">CONTENT TAG LAB · MOCK DATA</p>
        <h3 id="tag-analysis-title">按内容标签看清每种内容的表现</h3>
        <p>{{ activeGroup.description }} 目前使用演示数据，后续可直接接入视频标签字段。</p>
      </div>
      <div class="tag-analysis-status"><i></i><span>演示数据</span><small>待接入标签字段</small></div>
    </header>

    <div class="tag-type-switch" role="tablist" aria-label="内容大分类">
      <button :class="{ active: activeType === 'image' }" role="tab" :aria-selected="activeType === 'image'" type="button" @click="selectType('image')">
        <span class="tag-type-icon image-icon">图</span>
        <span><strong>图文</strong><small>内容案例 · 5 个小类</small></span>
      </button>
      <button :class="{ active: activeType === 'video' }" role="tab" :aria-selected="activeType === 'video'" type="button" @click="selectType('video')">
        <span class="tag-type-icon video-icon">视</span>
        <span><strong>视频</strong><small>短视频类型 · 5 个小类</small></span>
      </button>
    </div>

    <div class="tag-analysis-layout">
      <aside class="tag-category-rail">
        <div class="tag-rail-heading"><span>小分类</span><strong>{{ activeGroup.shortLabel }}内容</strong></div>
        <button class="tag-all-option" :class="{ active: activeTag === 'all' }" type="button" @click="activeTag = 'all'">
          <span class="tag-all-mark">总</span><span><strong>全部{{ activeGroup.shortLabel }}</strong><small>汇总全部标签表现</small></span><em>{{ formatCompact(tags.reduce((sum, tag) => sum + tag.contentCount, 0)) }}篇</em>
        </button>
        <div class="tag-category-list">
          <button v-for="tag in tags" :key="tag.id" :class="['tag-category-item', { active: activeTag === tag.id }]" type="button" @click="activeTag = tag.id">
            <i :style="{ background: tag.color }"></i><span><strong>{{ tag.label }}</strong><small>{{ tag.description }}</small></span><em>{{ formatCompact(tag.exposure) }}</em>
          </button>
        </div>
      </aside>

      <div class="tag-analysis-content">
        <div class="tag-summary-grid">
          <article class="tag-summary-card featured-summary"><span>内容篇数</span><strong>{{ formatNumber(summary.contentCount) }}</strong><small>{{ activeTag === 'all' ? '全部小分类' : selectedTag.label }} · 较上周期 <b>+{{ formatPercent(selectedTag?.delta || 0.32) }}</b></small></article>
          <article class="tag-summary-card"><span>累计曝光</span><strong>{{ formatCompact(summary.exposure) }}</strong><small>内容曝光人数 <b>+18.6%</b></small></article>
          <article class="tag-summary-card"><span>互动率</span><strong>{{ formatPercent(engagementRate) }}</strong><small>互动 {{ formatCompact(summary.interactions) }} 次</small></article>
          <article class="tag-summary-card money-summary"><span>引导成交</span><strong>{{ formatMoney(summary.revenue) }}</strong><small>较上周期 <b>+27.4%</b></small></article>
        </div>

        <div class="tag-insight-strip"><span class="tag-insight-mark">↗</span><div><strong>{{ trendTarget.label }}是当前{{ activeGroup.shortLabel }}里最值得复制的类型</strong><p>演示数据显示曝光 {{ formatCompact(trendTarget.exposure) }}、互动率 {{ formatPercent(trendTarget.interactions / trendTarget.views) }}，建议优先扩大这一类型的内容供给。</p></div><em>+{{ formatPercent(trendTarget.delta) }}</em></div>

        <div class="tag-analysis-charts">
          <article class="tag-chart-card">
            <header><div><p>TAG RANKING</p><h4>{{ activeGroup.shortLabel }}标签表现排名</h4></div><span>按曝光量</span></header>
            <div class="tag-ranking-list">
              <div v-for="(tag, index) in [...tags].sort((a, b) => b.exposure - a.exposure)" :key="tag.id" class="tag-ranking-row" :class="{ selected: activeTag === tag.id }" @click="activeTag = tag.id">
                <b class="tag-ranking-index">{{ String(index + 1).padStart(2, '0') }}</b><i :style="{ background: tag.color }"></i><span>{{ tag.label }}</span><div class="tag-ranking-bar"><b :style="{ width: `${tag.exposure / maxExposure * 100}%`, background: tag.color }"></b></div><strong>{{ formatCompact(tag.exposure) }}</strong>
              </div>
            </div>
          </article>

          <article class="tag-chart-card tag-trend-card">
            <header><div><p>CONTENT TREND · MOCK</p><h4>{{ trendTarget.label }}近 6 周趋势</h4></div><span>相对指数</span></header>
            <div class="tag-trend-chart">
              <div class="tag-trend-y-axis"><span>100</span><span>75</span><span>50</span><span>25</span><span>0</span></div>
              <div class="tag-trend-plot"><div class="tag-trend-grid"></div><div class="tag-trend-bars"><div v-for="(point, index) in trendTarget.trend" :key="`${trendTarget.id}-${index}`" class="tag-trend-bar-wrap"><b :style="{ height: `${point / maxTrend * 100}%`, background: trendTarget.color }"></b><small>{{ trendLabels[index] }}</small></div></div></div>
            </div>
            <footer><span><i :style="{ background: trendTarget.color }"></i>{{ trendTarget.label }}</span><strong>本周指数 {{ trendTarget.trend[trendTarget.trend.length - 1] }}</strong></footer>
          </article>
        </div>

        <div class="tag-sample-heading"><div><p>CONTENT EXAMPLES · MOCK</p><h4>{{ activeTag === 'all' ? '内容案例预览' : `${selectedTag.label}案例预览` }}</h4></div><span>示例数据 · {{ visibleSamples.length }} 条</span></div>
        <div class="tag-sample-grid">
          <article v-for="(sample, index) in visibleSamples" :key="`${sample.tag.id}-${sample.title}`" class="tag-sample-card">
            <div class="tag-mock-cover" :class="[`mock-cover-${sample.tag.id}`, { 'mock-cover-video': activeType === 'video' }]">
              <span class="mock-cover-type">{{ activeGroup.shortLabel }}</span><div class="mock-cover-art"><i v-for="dot in 4" :key="dot"></i></div><strong>{{ sample.title }}</strong><small>{{ sample.tag.label }} · {{ index + 1 }}/{{ visibleSamples.length }}</small><b v-if="activeType === 'video'" class="mock-play">▶</b>
            </div>
            <div class="tag-sample-info"><strong>{{ sample.title }}</strong><small>{{ sample.meta }}</small><span>{{ sample.metric }}</span></div>
          </article>
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
.tag-analysis-content { display: grid; gap: 13px; min-width: 0; }.tag-summary-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 9px; }.tag-summary-card { min-width: 0; padding: 13px 14px; border: 1px solid #dce6df; border-radius: 11px; background: rgba(255,255,255,.75); }.tag-summary-card.featured-summary { border-color: #ceda83; background: linear-gradient(135deg, #f0f5c1, #f7f9e5); }.tag-summary-card.money-summary { border-color: #eadbbd; background: linear-gradient(135deg, #fffdf8, #fbf4e2); }.tag-summary-card span { color: #789087; font-size: 10px; }.tag-summary-card strong { display: block; margin-top: 7px; overflow: hidden; color: #294c42; font-size: clamp(20px, 2vw, 27px); letter-spacing: -.045em; text-overflow: ellipsis; white-space: nowrap; }.tag-summary-card small { display: block; margin-top: 5px; overflow: hidden; color: #9ba79f; font-size: 9px; text-overflow: ellipsis; white-space: nowrap; }.tag-summary-card b { color: #4c9a6e; font-weight: 850; }.money-summary strong { color: #8c6b2c; }
.tag-insight-strip { display: flex; align-items: center; gap: 10px; padding: 11px 13px; border: 1px solid #e0e9bf; border-radius: 10px; background: #f7f9e9; }.tag-insight-mark { display: grid; flex: 0 0 26px; width: 26px; height: 26px; place-items: center; border-radius: 8px; color: #668444; background: #e3edb9; font-size: 17px; font-weight: 900; }.tag-insight-strip div { min-width: 0; }.tag-insight-strip strong { color: #557145; font-size: 11px; }.tag-insight-strip p { margin: 3px 0 0; overflow: hidden; color: #879675; font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }.tag-insight-strip em { margin-left: auto; color: #4d996c; font-size: 12px; font-style: normal; font-weight: 900; white-space: nowrap; }
.tag-analysis-charts { display: grid; grid-template-columns: minmax(0, 1.02fr) minmax(0, 1fr); gap: 11px; }.tag-chart-card { min-width: 0; padding: 14px; border: 1px solid #dde7df; border-radius: 12px; background: rgba(255,255,255,.72); }.tag-chart-card header { display: flex; justify-content: space-between; gap: 10px; align-items: flex-start; }.tag-chart-card header p { color: #a0ada4; }.tag-chart-card h4, .tag-sample-heading h4 { margin: 0; color: #34584d; font-size: 14px; }.tag-chart-card header > span, .tag-sample-heading > span { color: #a0aaa3; font-size: 9px; white-space: nowrap; }.tag-ranking-list { display: grid; gap: 8px; margin-top: 15px; }.tag-ranking-row { display: grid; grid-template-columns: 20px 9px minmax(58px, .45fr) minmax(70px, 1fr) 45px; gap: 6px; align-items: center; padding: 5px 5px; border-radius: 7px; cursor: pointer; }.tag-ranking-row.selected { background: #f0f4df; }.tag-ranking-index { color: #a5b0a8; font-size: 9px; font-weight: 750; }.tag-ranking-row > i { width: 8px; height: 8px; border-radius: 50%; }.tag-ranking-row > span { overflow: hidden; color: #60776f; font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }.tag-ranking-bar { height: 5px; overflow: hidden; border-radius: 8px; background: #ecf1ea; }.tag-ranking-bar b { display: block; height: 100%; border-radius: inherit; }.tag-ranking-row > strong { color: #516e64; font-size: 10px; text-align: right; }.tag-trend-card { background: linear-gradient(135deg, #fbfcf7, #f5f8eb); }.tag-trend-chart { display: grid; grid-template-columns: 25px minmax(0, 1fr); gap: 7px; height: 136px; margin-top: 13px; }.tag-trend-y-axis { display: flex; flex-direction: column; justify-content: space-between; padding-bottom: 18px; color: #a5b0a8; font-size: 8px; text-align: right; }.tag-trend-plot { position: relative; min-width: 0; }.tag-trend-grid { position: absolute; inset: 0 0 18px; background: repeating-linear-gradient(to bottom, #e4ece0 0, #e4ece0 1px, transparent 1px, transparent 25%); }.tag-trend-bars { position: absolute; inset: 0 3px 0; display: flex; align-items: end; justify-content: space-around; gap: 7px; }.tag-trend-bar-wrap { display: flex; flex: 1; height: 100%; flex-direction: column; align-items: center; justify-content: end; gap: 5px; }.tag-trend-bar-wrap b { display: block; width: min(25px, 70%); min-height: 8px; border-radius: 5px 5px 2px 2px; opacity: .82; }.tag-trend-bar-wrap small { color: #a3afa7; font-size: 8px; white-space: nowrap; }.tag-trend-card footer { display: flex; justify-content: space-between; align-items: center; margin-top: 2px; color: #94a29a; font-size: 9px; }.tag-trend-card footer span { display: inline-flex; align-items: center; gap: 5px; }.tag-trend-card footer i { width: 12px; height: 3px; border-radius: 5px; }.tag-trend-card footer strong { color: #638164; font-size: 10px; }
.tag-sample-heading { display: flex; justify-content: space-between; align-items: end; gap: 10px; padding-top: 2px; }.tag-sample-grid { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 9px; }.tag-sample-card { min-width: 0; overflow: hidden; border: 1px solid #dee8e0; border-radius: 11px; background: #fff; }.tag-mock-cover { position: relative; min-height: 142px; overflow: hidden; padding: 12px 11px; color: #f7f9ef; background: linear-gradient(145deg, #5a6f91, #becb9c); }.mock-cover-list { background: linear-gradient(145deg, #637c68, #d4dba1); }.mock-cover-buyer-show { background: linear-gradient(145deg, #9c6e52, #ead8a5); }.mock-cover-kol, .mock-cover-koc-kol { background: linear-gradient(145deg, #745e78, #e2b58e); }.mock-cover-styling { background: linear-gradient(145deg, #8d7c46, #d8c88b); }.mock-cover-live-cut { background: linear-gradient(145deg, #9b635d, #d9b577); }.mock-cover-white-background { background: linear-gradient(145deg, #738a78, #d9dfbd); }.mock-cover-creative-styling { background: linear-gradient(145deg, #a65e55, #e4b18b); }.mock-cover-visual-3d { background: linear-gradient(145deg, #7089ae, #c6d7dc); }.mock-cover-type { position: relative; z-index: 2; padding: 3px 6px; border: 1px solid rgba(255,255,255,.48); border-radius: 4px; background: rgba(28,48,50,.16); font-size: 8px; }.mock-cover-art { position: absolute; inset: 25px 12px 31px; display: flex; gap: 5px; align-items: center; justify-content: center; transform: rotate(-8deg); }.mock-cover-art i { display: block; width: 28%; height: 65%; border-radius: 46% 46% 15% 15%; background: rgba(255,255,255,.68); box-shadow: 14px 11px 0 rgba(255,255,255,.15); }.mock-cover-art i:nth-child(2) { height: 83%; background: rgba(38,62,76,.3); }.mock-cover-art i:nth-child(3) { height: 54%; background: rgba(255,236,194,.75); }.mock-cover-art i:nth-child(4) { height: 72%; background: rgba(255,255,255,.38); }.tag-mock-cover strong { position: absolute; right: 11px; bottom: 27px; left: 11px; overflow: hidden; color: #fff; font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }.tag-mock-cover > small { position: absolute; right: 11px; bottom: 11px; left: 11px; color: rgba(255,255,255,.74); font-size: 8px; }.mock-play { position: absolute; top: 50%; left: 50%; display: grid; width: 31px; height: 31px; place-items: center; border: 1px solid rgba(255,255,255,.6); border-radius: 50%; color: #fff; background: rgba(33,53,56,.35); font-size: 11px; transform: translate(-50%, -50%); }.tag-sample-info { display: grid; gap: 4px; padding: 10px; }.tag-sample-info strong { overflow: hidden; color: #45655a; font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }.tag-sample-info small { overflow: hidden; color: #9aa89f; font-size: 9px; text-overflow: ellipsis; white-space: nowrap; }.tag-sample-info span { color: #6a916a; font-size: 9px; font-weight: 800; }
@media (max-width: 1050px) { .tag-analysis-layout { grid-template-columns: 1fr; }.tag-category-rail { padding: 10px; }.tag-rail-heading { padding-bottom: 7px; }.tag-all-option, .tag-category-list { display: flex; flex-wrap: wrap; gap: 5px; }.tag-all-option, .tag-category-item { width: auto; flex: 1 1 160px; }.tag-category-item em, .tag-all-option em { margin-left: auto; }.tag-sample-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
@media (max-width: 700px) { .tag-analysis-panel { padding: 15px; }.tag-analysis-header { flex-direction: column; }.tag-analysis-status { width: fit-content; }.tag-type-switch, .tag-summary-grid, .tag-analysis-charts { grid-template-columns: 1fr; }.tag-summary-card strong { font-size: 25px; }.tag-insight-strip { align-items: flex-start; }.tag-insight-strip p { white-space: normal; line-height: 1.45; }.tag-sample-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }.tag-mock-cover { min-height: 128px; }.tag-ranking-row { grid-template-columns: 18px 9px minmax(52px, .55fr) minmax(50px, 1fr) 40px; }.tag-type-switch button { min-height: 58px; } }
</style>
