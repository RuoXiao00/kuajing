import test from 'node:test'
import assert from 'node:assert/strict'
import { convertToCny, detectCurrency, getProductPrice, hasValidPrice, parseExchangeRates, parsePriceText } from './productPricing.js'

// 固定汇率只用于测试计算方向，绝不作为生产兜底汇率。
const rows = [
  ['JPY', 20], ['SGD', 0.2], ['USD', 0.125], ['GBP', 0.1],
].map(([quote, rate]) => ({ base: 'CNY', quote, rate, date: '2026-09-18' }))
const rates = parseExchangeRates(rows)

test('旧日本站快照的 ¥968 恢复日元，明确币种优先，并可换算人民币', () => {
  const product = { price: 968, price_display: '¥968', currency: null, url: 'https://www.amazon.co.jp/dp/B012345678' }
  assert.deepEqual(getProductPrice(product), { amount: 968, currency: 'JPY' })
  assert.equal(hasValidPrice(product), true)
  assert.equal(convertToCny(968, getProductPrice(product).currency, rates), 48.4)
  assert.equal(getProductPrice({ ...product, price_display: '￥968' }).currency, 'JPY')
  assert.equal(getProductPrice({ ...product, currency: 'CNY' }).currency, 'CNY')
  assert.equal(getProductPrice({ ...product, price_display: 'CNY 968' }).currency, 'CNY')
  assert.equal(getProductPrice({ ...product, price_display: 'SGD 968' }).currency, 'SGD')
  for (const url of [undefined, 'https://www.amazon.com/dp/B012345678', 'https://www.amazon.co.jp.evil.test/dp/B012345678']) {
    assert.equal(hasValidPrice({ ...product, url }), false)
  }
  assert.equal(hasValidPrice({ ...product, price_display: '968' }), false)
  assert.equal(hasValidPrice({ price: 968, currency: 'XXX' }), false)
})

test('新加坡站美元形符号与后端已声明币种不会被默认 USD 覆盖', () => {
  assert.equal(getProductPrice({ price: 10, price_display: '$10', url: 'https://www.amazon.sg/dp/B012345678' }).currency, 'SGD')
  assert.equal(getProductPrice({ price: 10, price_display: '$10', currency: 'SGD' }).currency, 'SGD')
  assert.equal(getProductPrice({ price: 10, price_display: 'USD 10', currency: 'SGD' }).currency, 'USD')
})

test('日元、新加坡元、美元、英镑按各自汇率转人民币，人民币保持原值', () => {
  for (const [amount, currency, expected] of [
    [2000, 'JPY', 100], [20, 'SGD', 100], [10, 'USD', 80], [10, 'GBP', 100], [88, 'CNY', 88],
  ]) assert.equal(convertToCny(amount, currency, rates), expected)
  assert.equal(convertToCny(1, 'JPY', rates), 0.05)
})

test('原价文字解析保留千分位、小数，不把零值/负数/区间/歧义数字当有效价格', () => {
  for (const [text, amount] of [['JPY 2,333', 2333], ['S$19.99', 19.99], ['$0.99', .99], ['$.99', .99], ['£12.50', 12.5]]) {
    assert.equal(parsePriceText(text), amount)
  }
  for (const text of [null, '', '$0.00', 'JPY 0', '$-1', 'EUR 19,99', '$10 - $20', 'unknown']) {
    assert.equal(parsePriceText(text), null)
  }
})

test('币种前缀优先于美元符号，单独 ¥ 不猜币种', () => {
  for (const [text, currency] of [['S$10', 'SGD'], ['SGD 10', 'SGD'], ['$10', 'USD'], ['£10', 'GBP'], ['JPY 10', 'JPY'], ['HK$10', 'HKD'], ['NZ$10', 'NZD'], ['C$10', 'CAD']]) {
    assert.equal(detectCurrency(text), currency)
  }
  assert.equal(detectCurrency('¥100'), null)
})

test('兼容旧缓存的 price=0 和缺失文本，同时防止币种错配', () => {
  assert.deepEqual(getProductPrice({ price: 0, price_display: 'JPY 2,000', currency: 'USD' }), { amount: 2000, currency: 'JPY' })
  assert.deepEqual(getProductPrice({ price: 12.5, currency: 'GBP' }), { amount: 12.5, currency: 'GBP' })
  assert.equal(getProductPrice({ price: 0, price_display: '$0.00' }).amount, null)
  assert.equal(getProductPrice({ price: null }).amount, null)
  assert.equal(getProductPrice({ price: Infinity }).amount, null)
  assert.equal(getProductPrice({ price: -1 }).amount, null)
})

test('错误基准、无效汇率、无日期数据不参与计算，不兜底成汇率 1', () => {
  const invalid = [
    { base: 'USD', quote: 'JPY', rate: 20, date: '2026-09-18' },
    { base: 'CNY', quote: 'SGD', rate: 0, date: '2026-09-18' },
    { base: 'CNY', quote: 'GBP', rate: Infinity, date: '2026-09-18' },
    { base: 'CNY', quote: 'USD', rate: 0.125 },
  ]
  assert.throws(() => parseExchangeRates(invalid))
  assert.throws(() => parseExchangeRates({ rates: rows }))
  assert.equal(convertToCny(100, 'EUR', rates), null)
  assert.equal(convertToCny(100, null, rates), null)
  assert.equal(convertToCny(0, 'JPY', rates), null)
  assert.equal(convertToCny(100, 'USD', null), null)
  assert.equal(convertToCny(100, 'CNY', null), 100)
})

test('整页共享汇率请求与缓存；请求失败后允许重新获取', async () => {
  const originalFetch = globalThis.fetch
  try {
    let calls = 0
    globalThis.fetch = async () => {
      calls += 1
      return { ok: true, json: async () => rows }
    }
    const shared = await import('./productPricing.js?shared-test')
    const [first, second] = await Promise.all([shared.loadExchangeRates(), shared.loadExchangeRates()])
    assert.deepEqual(first, second)
    await shared.loadExchangeRates()
    assert.equal(calls, 1)

    const retry = await import('./productPricing.js?retry-test')
    globalThis.fetch = async () => ({ ok: false })
    await assert.rejects(retry.loadExchangeRates())
    globalThis.fetch = async () => ({ ok: true, json: async () => rows })
    assert.deepEqual(await retry.loadExchangeRates(), rates)
  } finally {
    globalThis.fetch = originalFetch
  }
})
