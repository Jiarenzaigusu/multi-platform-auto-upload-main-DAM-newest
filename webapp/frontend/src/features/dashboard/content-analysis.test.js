import assert from 'node:assert/strict'
import { analyzeContent } from './content-analysis.js'

assert.deepEqual(analyzeContent(null).cards, [])
const data = {
  brand: { name: '星巴克' },
  summary: { current: { content_count: 2, content_viewers: 100, product_click_users: 20, impression_users: 200, revenue: 100 }, deltas: { content_viewers: -.3 }, previous: { label: '2026年7月' } },
  tags: { video: [{ label: '往期视频', revenue: 100, samples: [
    { content_id: '1', title: '甜品杯', revenue: 100, product_click_users: 5 },
    { content_id: '2', title: '流金杯', revenue: 0, product_click_users: 15 },
  ] }] },
}
const result = analyzeContent(data)
assert.match(result.summary, /星巴克.*2026年7月下降 30.0%/)
assert.match(result.summary, /甜品杯.*100.0%/)
assert.match(result.cards[1].text, /流金杯.*商品点击人数 15.*每次只改变一个变量/)
assert.match(result.cards[2].text, /点击与成交领先作品不同/)
assert.match(result.cards[0].text, /10.0%/)
assert.match(result.cards[4].text, /细节实拍与送礼场景/)
data.summary.current = { content_count: 0, revenue: 0, impression_users: 0 }
data.summary.deltas = {}
data.tags = {}
const empty = analyzeContent(data)
assert.match(empty.summary, /缺少可比周期/)
assert.match(empty.cards[2].text, /暂无正向种草成交/)
assert.ok(!JSON.stringify(empty).match(/NaN|Infinity/))
console.log('Content analysis checks passed')
