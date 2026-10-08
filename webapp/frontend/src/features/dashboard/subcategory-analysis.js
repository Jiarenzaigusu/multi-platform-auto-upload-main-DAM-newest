const numeric = (value) => Number.isFinite(Number(value)) ? Number(value) : 0
const divide = (value, total) => total > 0 ? value / total : null

export function analyzeSubcategories(data) {
  const groups = []
  for (const type of ['image', 'video']) {
    const parents = new Map()
    for (const tag of data?.tags?.[type] || []) {
      if (!tag.subcategory?.trim()) continue
      const parent = tag.category || tag.label
      if (!parents.has(parent)) parents.set(parent, [])
      parents.get(parent).push(tag)
    }
    for (const [label, tags] of parents) {
      const totals = tags.reduce((sum, tag) => {
        for (const key of ['contentCount', 'exposure', 'product_click_users', 'revenue']) sum[key] += numeric(tag[key])
        return sum
      }, { contentCount: 0, exposure: 0, product_click_users: 0, revenue: 0 })
      const baseline = {
        reach: divide(totals.exposure, totals.contentCount),
        click: divide(totals.product_click_users, totals.exposure),
        revenue: divide(totals.revenue * 1000, totals.exposure),
      }
      const rows = tags.map((tag) => {
        const count = numeric(tag.contentCount)
        const exposure = numeric(tag.exposure)
        const clicks = numeric(tag.product_click_users)
        const revenue = numeric(tag.revenue)
        const metrics = {
          reach: divide(exposure, count),
          click: divide(clicks, exposure),
          revenue: divide(revenue * 1000, exposure),
        }
        const advantages = []
        if (tags.length > 1) {
          if (metrics.reach > baseline.reach) advantages.push('单篇曝光优势')
          if (metrics.click > baseline.click) advantages.push('商品点击效率优势')
          if (metrics.revenue > baseline.revenue) advantages.push('种草成交效率优势')
          if (exposure > 0 && tags.every((peer) => exposure >= numeric(peer.exposure))) advantages.push('曝光规模领先')
          if (revenue > 0 && tags.every((peer) => revenue >= numeric(peer.revenue))) advantages.push('种草成交贡献领先')
        }
        const assessment = !count || !exposure ? '有效内容或曝光不足，暂不能评估效率优势。'
          : tags.length < 2 ? '当前仅有一个二级类目，暂无同级比较对象。'
            : advantages.length ? `相较同级类目整体基准，具备${advantages.join('、')}。`
              : '当前未显示高于同级整体基准的效率优势，可保留小规模测试。'
        const action = metrics.revenue > baseline.revenue && tags.length > 1
          ? '优先复盘高成交作品的商品与承接，增加同类内容测试并跟踪千人曝光种草成交金额。'
          : metrics.click > baseline.click && tags.length > 1
            ? '复用高点击作品的表达，固定商品测试不同场景，以商品点击比率验证。'
            : metrics.reach > baseline.reach && tags.length > 1
              ? '保留曝光表现较好的题材，测试商品露出与点击引导，观察商品点击比率。'
              : '固定商品、小规模测试内容表达，比较单篇曝光和商品点击比率后再决定投入。'
        return { id: tag.id, label: tag.subcategory, count, exposure, clicks, revenue, metrics,
          exposureShare: divide(exposure, totals.exposure), revenueShare: divide(revenue, totals.revenue),
          advantages, assessment, action, caution: count < 5 ? '内容不足5篇，结论仅作探索参考。' : '类目差异可能受商品、投流与内容数量影响，需通过测试验证。' }
      })
      groups.push({ id: `${type}:${label}`, label, type, baseline, rows })
    }
  }
  return groups
}
