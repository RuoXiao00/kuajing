import test from 'node:test'
import assert from 'node:assert/strict'
import { readFirstPage, saveFirstPage } from './productSnapshot.js'

const page = (date = '2026-09-21T08:00:00Z') => ({ category: 'hot', sub_category: 'all', period: 'current',
  page: 1, pages_scanned: 1, partial: false, fetched_at: date, next_page: 2,
  products: [{ asin: 'B012345678', title: '真实商品', price: 25, currency: 'USD', rating: 4.5 }] })
const storage = () => {
  const records = new Map()
  return { getItem: key => records.get(key), setItem: (key, value) => records.set(key, value) }
}

test('旧快照恢复日本站日元，只保留金额与币种都有效的商品', () => {
  const data = page()
  data.products = [
    { asin: 'B012345678', title: '日元旧缓存', price: 968, price_display: '¥968', url: 'https://www.amazon.co.jp/dp/B012345678' },
    { asin: 'B012345679', title: '无法确定币种', price: 968 },
  ]
  const store = storage()
  assert.equal(saveFirstPage(data, 'hot', 'all', store), true)
  const saved = readFirstPage('hot', 'all', null, store)
  assert.equal(saved.products.length, 1)
  assert.equal(saved.products[0].asin, 'B012345678')
})

test('首次无浏览记录使用服务器首屏，且不沿用旧游标、不跨筛选显示', () => {
  const store = storage()
  const data = readFirstPage('hot', 'all', page(), store)
  assert.equal(data.products.length, 1)
  assert.equal(data.preview_source, 'server')
  assert.equal(data.next_page, undefined)
  assert.equal(readFirstPage('niche', 'all', page(), store), null)
  assert.equal(readFirstPage('hot', 'shuma', page(), store), null)
})

test('保存真实第一页，下次读取较新的快照；后续页、空页和部分失败不能覆盖', () => {
  const store = storage()
  assert.equal(saveFirstPage(page(), 'hot', 'all', store), true)
  const older = page('2026-09-20T08:00:00Z')
  assert.equal(readFirstPage('hot', 'all', older, store).preview_source, 'saved')
  for (const change of [{ page: 2 }, { partial: true }, { products: [] }, { pages_scanned: 2 }]) {
    assert.equal(saveFirstPage({ ...page(), ...change }, 'hot', 'all', store), false)
  }
  assert.equal(readFirstPage('hot', 'all', older, store).fetched_at, page().fetched_at)
  assert.equal(readFirstPage('hot', 'all', page('2026-09-22T08:00:00Z'), store).preview_source, 'server')
})

test('损坏缓存、存储被禁用或配额满不妨碍服务器首屏', () => {
  for (const store of [
    { getItem: () => '{broken', setItem: () => { throw Error('quota') } },
    { getItem: () => { throw Error('denied') }, setItem: () => { throw Error('denied') } },
  ]) {
    assert.equal(readFirstPage('hot', 'all', page(), store).products.length, 1)
    assert.equal(saveFirstPage(page(), 'hot', 'all', store), false)
  }
})

test('缓存过滤无价商品，保留能从原价恢复金额的商品，并清洗字段及去重', () => {
  const dirty = page()
  dirty.products[0].rating = { value: 5 }
  dirty.products[0].price = null
  dirty.products[0].sales = { text: 'bad' }
  dirty.products.push(null, { asin: 'x' }, dirty.products[0])
  assert.equal(readFirstPage('hot', 'all', dirty, storage()), null)
  dirty.products[0].price_display = 'JPY 2,000'
  const data = readFirstPage('hot', 'all', dirty, storage())
  assert.equal(data.products.length, 1)
  assert.equal(data.products[0].price, null)
  assert.equal(data.products[0].rating, null)
  assert.equal(data.products[0].sales, null)
})
