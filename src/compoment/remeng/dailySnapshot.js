import { IS_DEMO, storageKey } from '../../runtime.js'
import { hasValidPrice } from './productPricing.js'
import { productLink } from './productMarketplace.js'
import { prioritizeUnseen } from './productDiscovery.js'

export const PRODUCT_BATCH_SIZE = 20
// 本机缓存仅用于断网回看；所有用户的正式数据仍来自服务器同一份每日快照。
// 只保存最后查看的筛选，避免多个完整商品集合挤占 localStorage 配额。
const CACHE_KEY = storageKey('kuajing:product-daily-snapshot:v2')
const MAX_CACHE_SIZE = 2_000_000
const validDate = value => typeof value === 'string' && Number.isFinite(Date.parse(value))
const number = value => typeof value === 'number' && Number.isFinite(value) ? value : null
const text = value => typeof value === 'string' ? value : null

export function normalizeSnapshot(value, category, subCategory) {
  if (!value || value.category !== category || value.sub_category !== subCategory
    || !Array.isArray(value.products) || !validDate(value.fetched_at)) return null
  const seen = new Set()
  const products = []
  for (const item of value.products) {
    if (!item || typeof item.asin !== 'string' || !/^[A-Z0-9]{10}$/.test(item.asin)
      || typeof item.title !== 'string' || !item.title.trim() || seen.has(item.asin)
      || !hasValidPrice(item)) continue
    seen.add(item.asin)
    products.push({ asin: item.asin, title: item.title.slice(0, 1000), url: productLink(item),
      image_url: typeof item.image_url === 'string' && (item.image_url.startsWith('https://')
        || (IS_DEMO && item.image_url.startsWith('/'))) ? item.image_url : null,
      price: number(item.price), currency: text(item.currency), price_display: text(item.price_display),
      sales: text(item.sales), rating: number(item.rating), review_count: number(item.review_count) })
  }
  return { category, sub_category: subCategory, products, fetched_at: value.fetched_at,
    snapshot_id: text(value.snapshot_id) || value.fetched_at,
    snapshot_date: text(value.snapshot_date), is_stale: Boolean(value.is_stale),
    provider: text(value.provider), partial: Boolean(value.partial),
    warnings: Array.isArray(value.warnings) ? value.warnings.filter(x => typeof x === 'string') : [] }
}

export function readSavedSnapshot(category, subCategory, storage) {
  if (IS_DEMO) return null
  try {
    storage ??= globalThis.localStorage
    const raw = storage?.getItem(CACHE_KEY)
    if (!raw || raw.length > MAX_CACHE_SIZE) return null
    const record = JSON.parse(raw)
    return record.version === 2 ? normalizeSnapshot(record.data, category, subCategory) : null
  } catch { return null }
}

export function saveSnapshot(data, category, subCategory, storage) {
  if (IS_DEMO) return false
  const snapshot = normalizeSnapshot(data, category, subCategory)
  if (!snapshot) return false
  try {
    storage ??= globalThis.localStorage
    const raw = JSON.stringify({ version: 2, data: snapshot })
    if (!storage || raw.length > MAX_CACHE_SIZE) return false
    storage.setItem(CACHE_KEY, raw)
    return true
  } catch { return false }
}

export function snapshotView(previous, snapshot, seen = {}) {
  if (!snapshot) return { data: null, visibleCount: 0 }
  const sameVersion = previous?.data?.category === snapshot.category
    && previous.data.sub_category === snapshot.sub_category
    && previous.data.snapshot_id === snapshot.snapshot_id
    && previous.data.fetched_at === snapshot.fetched_at
  return { data: { ...snapshot, products: sameVersion ? previous.data.products
    : prioritizeUnseen(snapshot.products, seen) },
  visibleCount: sameVersion ? Math.min(previous.visibleCount, snapshot.products.length)
    : Math.min(PRODUCT_BATCH_SIZE, snapshot.products.length) }
}

export function revealMoreProducts(view) {
  // 下滑只扩展数组切片，不接触网络、后端页码或付费采集接口。
  return { ...view, visibleCount: Math.min(view.visibleCount + PRODUCT_BATCH_SIZE, view.data?.products.length ?? 0) }
}

export function watchSharedSnapshot({ endpoint, category, subCategory, fetcher, onResult, onError,
  setTimer = setTimeout, clearTimer = clearTimeout, requestTimeout = 15_000 }) {
  let active = true
  let controller
  let timeout
  let pollTimer
  let attempts = 0
  // 只轮询只读快照接口；后台更新尚未完成时退避，最多自动查询六次。
  const delays = [15_000, 30_000, 60_000, 60_000, 60_000]
  const query = new URLSearchParams({ category, subCategory })
  async function read() {
    if (!active) return
    controller = new AbortController()
    let timedOut = false
    timeout = setTimer(() => { timedOut = true; controller.abort() }, requestTimeout)
    try {
      const response = await fetcher(`${endpoint}?${query}`, { signal: controller.signal, cache: 'no-store' })
      const payload = await response.json().catch(() => null)
      if (!response.ok) throw new Error(`商品数据读取失败（HTTP ${response.status}），请稍后重试。`)
      if (!payload || !Object.hasOwn(payload, 'snapshot')) throw new Error('商品数据返回格式异常，请稍后重试。')
      const snapshot = payload.snapshot === null ? null : normalizeSnapshot(payload.snapshot, category, subCategory)
      if (payload.snapshot !== null && !snapshot) throw new Error('商品快照与当前筛选不匹配，请稍后重试。')
      if (!active) return
      const waiting = ['pending', 'updating'].includes(payload.update_status)
        && (!snapshot || snapshot.is_stale)
      const willPoll = waiting && attempts < delays.length
      onResult({ snapshot, updateStatus: payload.update_status || 'ready',
        lastError: text(payload.last_error) || '', nextUpdateAt: validDate(payload.next_update_at) ? payload.next_update_at : null,
        willPoll })
      if (willPoll) pollTimer = setTimer(read, delays[attempts++])
    } catch (error) {
      if (active) onError(timedOut ? '读取商品数据超时，请稍后重试。'
        : error instanceof TypeError ? '暂时无法连接服务器，可先浏览本机保存的商品。'
          : error instanceof Error ? error.message : '商品数据读取失败，请稍后重试。')
    } finally { clearTimer(timeout) }
  }
  read()
  return () => { active = false; clearTimer(timeout); clearTimer(pollTimer); controller?.abort() }
}
