import test from 'node:test'
import assert from 'node:assert/strict'
import { productLink, productMarketLabel } from './productMarketplace.js'
import { readFirstPage } from './productSnapshot.js'

test('区域站商品保留真实来源，拒绝外部域名、伪造域名及带凭据链接', () => {
  for (const [host, label] of [['www.amazon.com', '美国站'], ['www.amazon.co.jp', '日本站'], ['www.amazon.co.uk', '英国站'], ['www.amazon.sg', '新加坡站']]) {
    const product = { asin: 'B012345678', url: `https://${host}/dp/B012345678?ref=tracking` }
    assert.equal(productLink(product), `https://${host}/dp/B012345678`)
    assert.equal(productMarketLabel(product), `Amazon ${label}`)
  }
  for (const url of ['https://www.amazon.com.evil.invalid/dp/x', 'javascript:alert(1)', 'https://user:pass@www.amazon.co.jp/dp/x', 'http://www.amazon.co.jp/dp/x']) {
    assert.equal(productLink({ asin: 'B012345678', url }), 'https://www.amazon.com/dp/B012345678')
  }
})

test('首次预览和本地缓存不能丢掉日本站来源后变成美国站链接', () => {
  const payload = { category: 'hot', sub_category: 'all', period: 'current', page: 1, pages_scanned: 1,
    fetched_at: new Date().toISOString(), products: [{ asin: 'B012345678', title: '产品', price: 500,
      currency: 'JPY', url: 'https://www.amazon.co.jp/dp/B012345678' }] }
  const result = readFirstPage('hot', 'all', payload, { getItem: () => null })
  assert.equal(result.products[0].url, 'https://www.amazon.co.jp/dp/B012345678')
})
