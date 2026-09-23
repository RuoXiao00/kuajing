import { request as fetch } from '../../api.js';
// 价格和汇率计算单独放在纯函数里，方便用固定数值验证，不依赖页面或真实汇率涨跌。
// 优先读明确币种；歧义符号结合已声明币种及真实商品站点，不能按金额大小猜。
export function detectCurrency(text, sourceUrl, declaredCurrency = null) {
  if (typeof text !== 'string') return null
  text = text.normalize('NFKC')
  const code = text.match(/\b(USD|JPY|SGD|GBP|CNY|EUR|CAD|AUD|HKD|NZD|TWD|INR|AED|SAR|MXN|BRL)\b/i)
  if (code) return code[1].toUpperCase()
  for (const [symbol, currency] of [
    ['HK$', 'HKD'], ['NZ$', 'NZD'], ['NT$', 'TWD'], ['CA$', 'CAD'], ['C$', 'CAD'],
    ['A$', 'AUD'], ['S$', 'SGD'], ['R$', 'BRL'], ['€', 'EUR'], ['£', 'GBP'], ['₹', 'INR'],
  ]) {
    if (text.includes(symbol)) return currency
  }
  if (/日元|日本円|円/.test(text)) return 'JPY'
  if (/人民币|人民幣|RMB|CN¥/i.test(text)) return 'CNY'
  let host = ''
  try {
    const url = new URL(sourceUrl)
    if (url.protocol === 'https:' && !url.username && !url.password && !url.port) host = url.hostname
  } catch { /* 旧缓存缺少来源时不根据歧义符号猜日元。 */ }
  if (text.includes('¥')) {
    if (['JPY', 'CNY'].includes(declaredCurrency)) return declaredCurrency
    // 已确认的日本站商品以 ¥ 标价；裸数字、其他站点和伪造后缀不走此规则。
    return ['amazon.co.jp', 'www.amazon.co.jp'].includes(host) ? 'JPY' : null
  }
  if (text.includes('$')) {
    if (['USD', 'SGD', 'CAD', 'AUD', 'HKD', 'NZD', 'TWD', 'MXN'].includes(declaredCurrency)) return declaredCurrency
    return ['amazon.sg', 'www.amazon.sg'].includes(host) ? 'SGD' : 'USD'
  }
  return null
}

export function parsePriceText(text) {
  if (typeof text !== 'string') return null
  // 爬虫固定请求 en_US 数字格式。千分位和小数完整匹配，避免把 19,99 截成 19。
  const numbers = text.match(/[+-]?(?:\d[\d,.]*|\.\d+)/g)
  if (numbers?.length !== 1
    || !/^(?:(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?|\.\d{1,2})$/.test(numbers[0])) return null
  const amount = Number(numbers[0].replaceAll(',', ''))
  return Number.isFinite(amount) && amount > 0 ? amount : null
}

export function getProductPrice(product) {
  const displayAmount = parsePriceText(product.price_display)
  const numericAmount = typeof product.price === 'number' && Number.isFinite(product.price)
    && product.price > 0 ? product.price : null
  // 兼容旧服务/缓存：数值字段为 0 但原价文本正常时，仍能恢复正确金额。
  // 若完整原价文本能解析，优先让金额与文本币种配套，不能用 JPY 金额配 USD 汇率。
  const amount = displayAmount ?? numericAmount
  const fieldCurrency = typeof product.currency === 'string' && /^[A-Z]{3}$/i.test(product.currency)
    ? detectCurrency(product.currency) : null
  const currency = detectCurrency(product.price_display, product.url, fieldCurrency) ?? fieldCurrency
  return { amount, currency }
}

// 列表、分页和旧快照共用规则：缺失/零值/负数/无法确认币种都过滤，
// 旧数据若能从原价文本恢复有效金额则保留；汇率暂不可用不等于商品没有价格。
export function hasValidPrice(product) {
  if (!product) return false
  const { amount, currency } = getProductPrice(product)
  return amount !== null && currency !== null
}

export function parseExchangeRates(rows) {
  if (!Array.isArray(rows)) throw new Error('汇率数据格式异常')
  const rates = {}
  for (const row of rows) {
    if (row?.base !== 'CNY' || !/^[A-Z]{3}$/.test(row.quote)
      || typeof row.rate !== 'number' || !Number.isFinite(row.rate) || row.rate <= 0
      || typeof row.date !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(row.date)) continue
    rates[row.quote] = { rate: row.rate, date: row.date }
  }
  if (Object.keys(rates).length === 0) throw new Error('暂未取得有效汇率')
  return rates
}

export function convertToCny(amount, currency, rates) {
  if (!Number.isFinite(amount) || amount <= 0 || !currency) return null
  if (currency === 'CNY') return amount
  const rate = rates?.[currency]?.rate
  if (!Number.isFinite(rate) || rate <= 0) return null
  // 接口 base=CNY 返回的是“1 人民币 = 多少外币”，所以外币转人民币要除以 rate。
  // 例如测试汇率 1 CNY = 20 JPY，2000 日元 / 20 = 100 人民币，不能反向相乘。
  const value = amount / rate
  return Number.isFinite(value) && value > 0 ? value : null
}

const EXCHANGE_API = 'https://api.frankfurter.dev/v2/rates?base=CNY'
const CACHE_TTL = 60 * 60 * 1000
let cached = null
let pending = null

export async function loadExchangeRates() {
  // 一份汇率供整页所有商品复用，翻页不会每张卡片发请求；一小时缓存仅存在内存。
  // 共用 pending 也能合并重复进入页面的请求，不读取或更改用户的本地存储。
  if (cached && Date.now() - cached.fetchedAt < CACHE_TTL) return cached.rates
  if (pending) return pending
  pending = (async () => {
    const controller = new AbortController()
    const timeoutId = setTimeout(() => controller.abort(), 10_000)
    try {
      // 只发送币种参数，不向汇率服务传商品、用户数据或凭据。
      const response = await fetch(EXCHANGE_API, { signal: controller.signal, credentials: 'omit' })
      if (!response.ok) throw new Error('汇率服务暂不可用')
      const rates = parseExchangeRates(await response.json())
      cached = { rates, fetchedAt: Date.now() }
      return rates
    } finally {
      clearTimeout(timeoutId)
    }
  })()
  try {
    return await pending
  } finally {
    pending = null
  }
}
