<script setup>
import { computed } from 'vue'
import { analyzeSubcategories } from './subcategory-analysis.js'
const props = defineProps({ data: { type: Object, default: null } })
const groups = computed(() => analyzeSubcategories(props.data))
const number = (value) => value == null ? '暂无' : new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 2 }).format(value)
const percent = (value) => value == null ? '暂无' : `${(value * 100).toFixed(1)}%`
const money = (value) => value == null ? '暂无' : `¥${number(value)}`
</script>

<template>
  <article v-if="groups.length" class="subcategory-panel">
    <header><h3>本周期二级类目优势分析</h3><p>按一级分类比较各二级类目的规模与效率，辅助选择值得继续投入的内容方向。</p></header>
    <section v-for="group in groups" :key="group.id" class="category-group">
      <h4>{{ group.label }} <small>{{ group.type === 'image' ? '图文' : '视频' }} · {{ group.rows.length }} 个二级类目</small></h4>
      <p class="baseline">同级整体基准：单篇曝光人数 {{ number(group.baseline.reach) }} · 商品点击人数/曝光人数 {{ percent(group.baseline.click) }} · 千人曝光种草成交金额 {{ money(group.baseline.revenue) }}</p>
      <div class="category-grid">
        <div v-for="row in group.rows" :key="row.id" class="category-card">
          <h5>{{ row.label }} <small>{{ number(row.count) }} 篇内容</small></h5>
          <div class="advantages"><span v-for="advantage in row.advantages" :key="advantage">{{ advantage }}</span><span v-if="!row.advantages.length">{{ group.rows.length < 2 ? '待积累比较样本' : '暂未确认相对优势' }}</span></div>
          <dl><div><dt>曝光人数 / 同级占比</dt><dd>{{ number(row.exposure) }} / {{ percent(row.exposureShare) }}</dd></div><div><dt>单篇曝光人数</dt><dd>{{ number(row.metrics.reach) }}</dd></div><div><dt>商品点击人数 / 曝光人数</dt><dd>{{ number(row.clicks) }} / {{ percent(row.metrics.click) }}</dd></div><div><dt>种草成交金额 / 同级占比</dt><dd>{{ money(row.revenue) }} / {{ percent(row.revenueShare) }}</dd></div><div><dt>千人曝光种草成交金额</dt><dd>{{ money(row.metrics.revenue) }}</dd></div></dl>
          <p>{{ row.assessment }}</p><p><strong>建议：</strong>{{ row.action }}</p><p class="caution">{{ row.caution }}</p>
        </div>
      </div>
    </section>
    <footer>基于当前周期数据的规则评估；仅比较同一一级分类下有二级标签的类目，基准按内容数量或曝光人数加权。人数跨内容未去重；商品点击比率不是购买转化率；种草成交不等于直接购买归因；千人曝光成交金额不是 GPM。</footer>
  </article>
</template>

<style scoped>
.subcategory-panel { padding: 22px; border: 1px solid #dce6b9; border-radius: 15px; background: #f8faf1; }
h3, h4, h5 { margin: 0; color: #35594a; } h3 { font-size: 18px; } h4 { font-size: 16px; } h5 { display: flex; justify-content: space-between; gap: 12px; font-size: 15px; }
header p, .baseline, footer, .caution { color: #7c8f7f; font-size: 12px; line-height: 1.6; } small { color: #81927b; font-size: 12px; font-weight: 400; }
.category-group { margin-top: 22px; } .category-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.category-card { padding: 16px; border: 1px solid #e0e8d5; border-radius: 12px; background: white; }
.advantages { display: flex; flex-wrap: wrap; gap: 5px; margin: 12px 0; } .advantages span { padding: 4px 7px; border-radius: 5px; color: #5b784a; background: #edf4d8; font-size: 11px; }
dl { margin: 0; } dl div { display: flex; justify-content: space-between; gap: 12px; padding: 7px 0; border-bottom: 1px solid #edf1e9; font-size: 12px; } dt { color: #80917e; } dd { margin: 0; color: #46664d; text-align: right; }
.category-card p { font-size: 13px; line-height: 1.7; color: #627b68; } .category-card .caution { font-size: 11px; color: #8a977f; } footer { margin-top: 18px; }
@media (max-width: 700px) { .category-grid { grid-template-columns: 1fr; } .subcategory-panel { padding: 16px; } }
</style>
