const number = (value) => new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 2 }).format(Number(value || 0))
const money = (value) => `¥${Number(value || 0).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
const percent = (value) => `${(value * 100).toFixed(1)}%`
const ratio = (value, total) => total > 0 ? percent(value / total) : '暂无可计算数据'

export function analyzeContent(data) {
  const current = data?.summary?.current
  if (!current) return { summary: '连接品牌数据库后，将根据具体内容、分类与成交数据生成分析。', cards: [] }
  const brand = data.brand?.name || '当前品牌'
  const categories = [...(data.tags?.image || []), ...(data.tags?.video || [])]
  const samples = [...new Map(categories.flatMap((item) => item.samples || []).map((item) => [item.content_id, item])).values()]
  const clickLeader = [...samples].sort((a, b) => b.product_click_users - a.product_click_users)[0]
  const revenueLeader = [...samples].sort((a, b) => b.revenue - a.revenue)[0]
  const categoryLeader = [...categories].sort((a, b) => b.revenue - a.revenue)[0]
  const quote = (item) => `《${item.title.replace(/\s+/g, ' ').trim()}》`
  const delta = data.summary.deltas?.content_viewers
  const reference = data.summary.previous?.label || '上一可用下载周期'
  const reach = delta == null ? '缺少可比周期，暂不判断触达趋势' : `查看人数合计较${reference}${delta < 0 ? '下降' : '增长'} ${percent(Math.abs(delta))}`
  const summary = `${brand}本周期${reach}。${revenueLeader?.revenue > 0 ? `${quote(revenueLeader)}贡献 ${ratio(revenueLeader.revenue, current.revenue)} 的种草成交，建议优先复盘其选品与表达。` : '暂无正向成交样本，建议先核查商品点击后的承接。'}`
  return { summary, cards: [
    { icon: '总', tag: '品牌表现', title: `${brand}：触达与成交分别评估`, text: `点击人数 / 曝光人数为 ${ratio(current.product_click_users, current.impression_users)}，可用于观察点击承接；不能当作购买转化率。` },
    { icon: '机', tag: '具体内容', title: '优先复盘带来商品点击的作品', text: clickLeader?.product_click_users > 0 ? `${quote(clickLeader)}商品点击人数 ${number(clickLeader.product_click_users)}。以它为参照测试封面或商品利益点，每次只改变一个变量。` : '本周期暂无有效商品点击样本；先补齐内容级点击数据。' },
    { icon: '链', tag: '成交贡献', title: '围绕成交作品验证选品与场景', text: revenueLeader?.revenue > 0 ? `${quote(revenueLeader)}带来 ${money(revenueLeader.revenue)} 种草成交。${clickLeader?.content_id === revenueLeader.content_id ? '它也是点击领先作品，可优先复测。' : '点击与成交领先作品不同，需分别评估。'}复用前核对商品、价格和活动。` : '暂无正向种草成交记录；先核对成交数据与对应商品。' },
    { icon: '!', tag: '分类与趋势', title: '区分存量内容贡献与新增供给', text: `${categoryLeader?.revenue > 0 ? `${categoryLeader.label}贡献总种草成交的 ${ratio(categoryLeader.revenue, current.revenue)}。` : ''}下载周期包含往期作品，需核对新增作品和同一作品跨期表现。` },
    { icon: '下', tag: '执行建议', title: '下一下载周期的测试安排', text: revenueLeader?.revenue > 0 ? `围绕${quote(revenueLeader)}测试两版内容，仅改变封面或开场。${brand.includes('星巴克') ? '杯具可优先测试细节实拍与送礼场景。' : ''}对比商品点击与种草成交，再决定是否扩量。` : '固定商品与活动条件，仅改变封面或开场；对比商品点击和种草成交后再扩量。' },
  ] }
}
