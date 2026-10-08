import test from 'node:test'
import assert from 'node:assert/strict'
import { analyzeSubcategories } from './subcategory-analysis.js'
const tag = (subcategory, count, exposure, clicks, revenue) => ({ id: subcategory, category: '种草短视频', subcategory, contentCount: count, exposure, product_click_users: clicks, revenue })
test('weighted baseline separates scale from efficiency and excludes untagged rows', () => {
  const [group] = analyzeSubcategories({ tags: { video: [tag('桌面', 10, 1000, 10, 100), tag('户外', 1, 200, 20, 200), tag('', 10, 9999, 999, 999)] } })
  assert.equal(group.rows.length, 2)
  assert.equal(group.baseline.click, 30 / 1200)
  assert.ok(group.rows[0].advantages.includes('曝光规模领先'))
  assert.ok(!group.rows[0].advantages.includes('商品点击效率优势'))
  assert.ok(group.rows[1].advantages.includes('商品点击效率优势'))
  assert.ok(group.rows[1].advantages.includes('种草成交效率优势'))
  assert.match(group.rows[1].caution, /不足5篇/)
})
test('zero denominators and single subcategory do not fabricate advantages', () => {
  assert.deepEqual(analyzeSubcategories(null), [])
  const [group] = analyzeSubcategories({ tags: { image: [tag('桌面', 0, 0, 0, 0)] } })
  assert.equal(group.rows[0].metrics.click, null)
  assert.equal(group.rows[0].revenueShare, null)
  assert.deepEqual(group.rows[0].advantages, [])
  const [single] = analyzeSubcategories({ tags: { video: [tag('桌面', 10, 100, 10, 100)] } })
  assert.match(single.rows[0].assessment, /暂无同级/)
})
test('primary categories and content types stay isolated', () => {
  const groups = analyzeSubcategories({ tags: { image: [tag('桌面', 2, 50, 5, 20)], video: [tag('桌面', 10, 1000, 10, 100), { ...tag('室内', 2, 100, 20, 80), category: '其他视频' }] } })
  assert.equal(groups.length, 3)
  assert.equal(groups[0].baseline.click, 0.1)
  assert.equal(groups[1].baseline.click, 0.01)
})
