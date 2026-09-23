import test from 'node:test'
import assert from 'node:assert/strict'
import { readDiscovery, rememberDiscovery, prioritizeUnseen } from './productDiscovery.js'

const memory = () => {
  const values = new Map()
  return { getItem: k => values.get(k), setItem: (k, v) => values.set(k, v) }
}

test('仅已浏览卡片后移，不修改原数据或未看商品的热度顺序', () => {
  const list = ['B000000001', 'B000000002', 'B000000003'].map(asin => ({ asin }))
  const sorted = prioritizeUnseen(list, { B000000001: 100 })
  assert.deepEqual(sorted.map(p => p.asin), ['B000000002', 'B000000003', 'B000000001'])
  assert.equal(list[0].asin, 'B000000001')
})

test('浏览与下一页分别保存，各筛选隔离；7天后历史失效，末页回到起点', () => {
  const store = memory(), now = 1000000000
  rememberDiscovery('hot', 'all', { nextPage: 2 }, store, now)
  rememberDiscovery('hot', 'all', { asins: ['B000000001'] }, store, now + 1)
  assert.equal(readDiscovery('hot', 'all', store, now + 2).nextPage, 2)
  assert.deepEqual(readDiscovery('hot', 'shuma', store, now + 2), { seen: {}, nextPage: 1 })
  assert.deepEqual(readDiscovery('hot', 'all', store, now + 8 * 86400000), { seen: {}, nextPage: 1 })
  rememberDiscovery('hot', 'all', { nextPage: null }, store, now + 2)
  assert.equal(readDiscovery('hot', 'all', store, now + 3).nextPage, 1)
})

test('禁用或损坏存储不影响浏览', () => {
  const store = { getItem: () => { throw Error('denied') }, setItem: () => { throw Error('denied') } }
  assert.doesNotThrow(() => rememberDiscovery('hot', 'all', { asins: ['B000000001'] }, store))
  assert.deepEqual(readDiscovery('hot', 'all', store), { seen: {}, nextPage: 1 })
})
