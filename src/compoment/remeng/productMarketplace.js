// 只使用明确支持的亚马逊站点，不能把区域站商品链接硬改成美国站。
const MARKETS = { 'www.amazon.com': '美国站', 'www.amazon.co.jp': '日本站', 'www.amazon.co.uk': '英国站', 'www.amazon.sg': '新加坡站' }
export function productMarketplace(product) {
  try {
    const url = new URL(product?.url)
    if (url.protocol === 'https:' && !url.username && !url.password && !url.port && MARKETS[url.hostname]) return url.hostname
  } catch { /* 旧快照没有来源时沿用原来的美国站。 */ }
  return 'www.amazon.com'
}
export const productLink = product => `https://${productMarketplace(product)}/dp/${encodeURIComponent(product.asin)}`
export const productMarketLabel = product => `Amazon ${MARKETS[productMarketplace(product)]}`
