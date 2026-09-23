import { IS_DEMO, storageKey } from '../../runtime.js';
import { hasValidPrice } from './productPricing.js'
import { productLink } from './productMarketplace.js'

// 首屏快照只负责“先有商品可看”，不接管爬虫分页。新请求仍从第一页开始，
// 因此不能把预存数据的 next_page 当成实时请求游标，否则会漏掉最新第一页。
const PREFIX = storageKey('kuajing:product-first-page:v1:')
const MAX_BYTES = 300_000
const text = value => typeof value === 'string' ? value : null
const number = value => typeof value === 'number' && Number.isFinite(value) ? value : null

function cleanPage(value, category, subCategory) {
  if (!value || value.category !== category || value.sub_category !== subCategory
    || value.period !== 'current' || value.page !== 1 || value.pages_scanned !== 1
    || value.partial || !Array.isArray(value.products) || !value.products.length
    || value.products.length > 200 || typeof value.fetched_at !== 'string'
    || !Number.isFinite(Date.parse(value.fetched_at))) return null
  const seen = new Set()
  const products = []
  for (const item of value.products) {
    if (!item || typeof item.asin !== 'string' || !/^[A-Z0-9]{10}$/.test(item.asin) || typeof item.title !== 'string'
      || !item.title.trim() || seen.has(item.asin) || !hasValidPrice(item)) continue
    seen.add(item.asin)
    // localStorage 可以被手工修改，只取页面需要的字段，防止对象被直接渲染导致白屏。
    products.push({ asin: item.asin, title: item.title.slice(0, 1000), url: productLink(item),
      image_url: typeof item.image_url === 'string' && item.image_url.startsWith('https://') ? item.image_url : null,
      price: number(item.price), currency: text(item.currency), price_display: text(item.price_display),
      sales: text(item.sales), rating: number(item.rating), review_count: number(item.review_count) })
  }
  if (!products.length) return null
  return { category, sub_category: subCategory, period: 'current', page: 1, pages_scanned: 1,
    products, fetched_at: value.fetched_at, partial: false, from_cache: true,
    warnings: Array.isArray(value.warnings) ? value.warnings.filter(x => typeof x === 'string').slice(0, 10) : [] }
}

export function readFirstPage(category, subCategory, serverSnapshot, storage) {
  // 服务器快照与本地缓存比较时间，始终选较新的同筛选结果。
  // 全新浏览器由只读接口拿到共享快照；不再从发布包里的固定商品文件取数据。
  if (IS_DEMO) return null
  let saved = null
  try {
    const raw = (storage ?? globalThis.localStorage)?.getItem(`${PREFIX}${category}:${subCategory}`)
    if (raw && raw.length <= MAX_BYTES) {
      const record = JSON.parse(raw)
      if (record.version === 1) saved = cleanPage(record.data, category, subCategory)
    }
  } catch { /* 浏览器禁用存储、JSON 损坏时继续使用服务器快照，不阻止实时请求。 */ }
  const shared = cleanPage(serverSnapshot, category, subCategory)
  const useSaved = saved && (!shared || Date.parse(saved.fetched_at) >= Date.parse(shared.fetched_at))
  const data = useSaved ? saved : shared
  return data ? { ...data, is_preview: true, preview_source: useSaved ? 'saved' : 'server' } : null
}

export function saveFirstPage(payload, category, subCategory, storage) {
  // 只保存一张完整的真实第一页；空响应、部分失败和后续页不能覆盖上次可用首屏。
  // 固定页面筛选组合，最多18份快照，不把无限滚动累积的全部商品写入浏览器。
  if (IS_DEMO) return false
  const data = cleanPage(payload, category, subCategory)
  if (!data) return false
  try {
    const raw = JSON.stringify({ version: 1, data })
    if (raw.length > MAX_BYTES) return false
    const target = storage ?? globalThis.localStorage
    if (!target) return false
    target.setItem(`${PREFIX}${category}:${subCategory}`, raw)
    return true
  } catch { return false } // 配额满或隐私模式不影响列表、汇率和继续翻页。
}
