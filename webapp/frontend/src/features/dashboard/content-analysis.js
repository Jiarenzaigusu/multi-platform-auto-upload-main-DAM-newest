const number = (value) => new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 2 }).format(Number(value || 0))
const money = (value) => `¥${Number(value || 0).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
const percent = (value) => `${(value * 100).toFixed(1)}%`
const ratio = (value, total) => total > 0 ? percent(value / total) : '暂无可计算数据'

export function analyzeContent(data) {
  const current = data?.summary?.current
  if (!current) return { summary: '连接品牌数据库后，将按五个维度展示分析与数据覆盖情况。', cards: [] }
  const brand = data.brand?.name || '当前品牌'
  const categories = [...(data.tags?.image || []), ...(data.tags?.video || [])]
  const samples = [...new Map(categories.flatMap((item) => item.samples || []).map((item) => [item.content_id, item])).values()]
  const revenueLeader = [...samples].sort((a, b) => b.revenue - a.revenue)[0]
  const clickLeader = [...samples].filter((item) => item.product_click_users > 0).sort((a, b) => b.product_click_users - a.product_click_users)[0]
  const videoSamples = [...new Map((data.tags?.video || []).flatMap((item) => item.samples || []).map((item) => [item.content_id, item])).values()]
  const videoTarget = [...videoSamples].filter((item) => item.exposure > 0).sort((a, b) => b.exposure - a.exposure)[0]
  const clickCategory = [...categories].filter((item) => item.exposure > 0 && item.product_click_users > 0).sort((a, b) => b.product_click_users / b.exposure - a.product_click_users / a.exposure)[0]
  const quote = (item) => `《${String(item.title || item.content_id).replace(/\s+/g, ' ').trim()}》`
  const sampleEvidence = (item) => `${quote(item)}：曝光人数 ${number(item.exposure)}；商品点击人数 ${number(item.product_click_users)}；种草成交金额 ${money(item.revenue)}。所选样本来自分类指标榜单，不代表全量作品排名。`
  const retentionText = videoTarget
    ? `${quote(videoTarget)}曝光人数 ${number(videoTarget.exposure)}，商品点击人数/曝光人数 ${ratio(videoTarget.product_click_users, videoTarget.exposure)}。优先固定商品测试开场版本，以点击比率观察后链路变化；现有数据不能定位留存掉点。`
    : `当前缺少有曝光的视频样本，先核对${brand}视频供给与曝光记录；获得样本后固定商品测试开场，以商品点击比率比较版本，暂不能判断完播或节奏。`
  const searchText = clickLeader
    ? `${quote(clickLeader)}商品点击人数 ${number(clickLeader.product_click_users)}，可作为品牌词引导测试样本。固定商品与开场，仅改变品牌词提示，比较点击比率；点击只反映商品探索，不能证明看后搜。`
    : `本周期商品点击人数合计 ${number(current.product_click_users)}，${current.product_click_users > 0 ? '但缺少可定位的点击作品；先补齐作品映射，再选择品牌词引导测试样本' : '尚无正向点击信号；先固定商品测试卖点表达，观察是否产生商品点击'}。搜索增量需单独验证。`
  const interactionContext = clickCategory
    ? `${clickCategory.label}商品点击人数/曝光人数 ${ratio(clickCategory.product_click_users, clickCategory.exposure)}，可优先选择该分类测试提问文案；以互动密度及点击比率对比。`
    : `本周期商品点击人数合计 ${number(current.product_click_users)}；先固定商品测试提问文案，观察整体互动与点击变化。`
  const delta = data.summary.deltas?.content_viewers
  const reference = data.summary.previous?.label || '上一可用下载周期'
  const reach = delta == null ? '缺少可比周期，暂不判断查看趋势' : `查看人数合计较${reference}${delta < 0 ? '下降' : '增长'} ${percent(Math.abs(delta))}`
  const exposureEvidence = [`曝光次数 ${number(current.impressions)}；曝光人数合计 ${number(current.impression_users)}；查看人数合计 ${number(current.content_viewers)}。人数跨作品未去重，曝光次数不能当作播放量。`]
  const conversionEvidence = [`商品点击人数合计 ${number(current.product_click_users)}；种草成交金额 ${money(current.revenue)}。种草成交不等于直接购买归因。`]
  if (revenueLeader) conversionEvidence.push(`《${String(revenueLeader.title || revenueLeader.content_id).replace(/\s+/g, ' ').trim()}》：种草成交金额 ${money(revenueLeader.revenue)}。`)
  if (current.impressions > 0) {
    conversionEvidence.push(`千次曝光种草成交金额 ${money(current.revenue / current.impressions * 1000)}（不是GPM）。`)
    if (current.product_clicks != null) conversionEvidence.push(`商品点击次数 / 曝光次数 ${ratio(current.product_clicks, current.impressions)}（PV比率）。`)
  }
  const interactionAvailable = current.interactions != null
  return {
    summary: `${brand}${reach}。${revenueLeader?.revenue > 0 ? `${quote(revenueLeader)}贡献 ${ratio(revenueLeader.revenue, current.revenue)} 的种草成交金额，优先核对其商品与承接。` : '暂无正向种草成交样本，优先核查点击后的商品承接。'}留存与搜索维度根据已有作品表现确定测试对象，效果仍需验证。`,
    cards: [
      { icon: '1', dimension: '流量与传播表现', tag: '部分可分析', title: '评估曝光与查看规模', text: `${reach}。缺少自然/投流、粉丝来源、分享及主页访问，无法判断公域推荐或出圈潜力；先比较作品及分类的曝光表现。`, evidence: exposureEvidence },
      { icon: '2', dimension: '播放留存与内容节奏', tag: '定制测试建议', title: videoTarget ? '从高曝光视频验证开场与承接' : '先建立可测试的视频样本', text: retentionText, evidence: [...(videoTarget ? [sampleEvidence(videoTarget)] : exposureEvidence), '缺少逐秒留存与内容时间点，无法确认开场、植入或CTA效果。'] },
      { icon: '3', dimension: '互动与共鸣深度', tag: '定制测试建议', title: clickCategory ? `优先验证${clickCategory.label}的互动表达` : '结合商品点击测试互动表达', text: `${interactionAvailable ? `互动次数 ${number(current.interactions)}。` : ''}${interactionContext}缺少互动拆分，不能判定收藏或购买意向。`, evidence: [interactionAvailable ? `互动次数 ${number(current.interactions)}。${current.impressions > 0 ? `每千次曝光互动次数 ${number(current.interactions / current.impressions * 1000)}。` : '曝光分母为零或缺失，暂不计算互动密度。'}互动次数不等于互动人数。` : '当前无可用互动总次数；需补齐后比较互动密度。', ...(clickCategory ? [`分类 ${clickCategory.label}：曝光人数 ${number(clickCategory.exposure)}；商品点击人数 ${number(clickCategory.product_click_users)}。点击比率只能辅助选择测试对象，不能衡量共鸣。`] : conversionEvidence.slice(0, 1))] },
      { icon: '4', dimension: '搜索与后验种草', tag: '定制测试建议', title: clickLeader ? '用点击作品测试品牌词引导' : '先验证商品探索信号', text: searchText, evidence: [...(clickLeader ? [sampleEvidence(clickLeader)] : conversionEvidence.slice(0, 1)), '缺少看后搜及品牌/单品搜索指数；测试需另采搜索基线与发布后24–72小时变化，不能将商品点击当作搜索转化。'] },
      { icon: '5', dimension: '商业转化与带货效率', tag: '部分可分析', title: '评估商品点击与种草成交效率', text: `商品点击人数 / 曝光人数为 ${ratio(current.product_click_users, current.impression_users)}。可比较作品的点击与种草成交贡献；缺少订单、成本及归因，暂不能计算购买CVR、ROI/ROAS或GPM。`, evidence: conversionEvidence },
    ],
  }
}
