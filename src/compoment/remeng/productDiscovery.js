// 浏览偏好只保存在本机，不发送账号或浏览记录给模型/商品站。
// “看过”由卡片进入可视区域决定，不把只下载但没浏览的整页商品标为已看。
const PREFIX = 'kuajing:product-discovery:v1:'
const WEEK = 7 * 24 * 60 * 60 * 1000

export function readDiscovery(category, subCategory, storage, now = Date.now()) {
  try {
    const raw = (storage ?? globalThis.localStorage)?.getItem(`${PREFIX}${category}:${subCategory}`)
    const data = raw && raw.length < 100_000 ? JSON.parse(raw) : null
    const seen = Object.fromEntries(Object.entries(data?.seen ?? {}).filter(([asin, time]) =>
      /^[A-Z0-9]{10}$/.test(asin) && Number.isFinite(time) && time > now - WEEK && time <= now))
    return { seen, nextPage: Number.isInteger(data?.nextPage) && data.nextPage >= 1
      && data.nextPage <= 50 && data.updatedAt > now - WEEK ? data.nextPage : 1 }
  } catch { return { seen: {}, nextPage: 1 } }
}

export function rememberDiscovery(category, subCategory, { asins = [], nextPage } = {}, storage, now = Date.now()) {
  try {
    const target = storage ?? globalThis.localStorage
    const data = readDiscovery(category, subCategory, target, now)
    for (const asin of asins) if (/^[A-Z0-9]{10}$/.test(asin)) data.seen[asin] = now
    // 限制历史大小；最近7天最多记600件，旧记录淘汰后允许重新发现。
    data.seen = Object.fromEntries(Object.entries(data.seen).sort((a, b) => b[1] - a[1]).slice(0, 600))
    if (nextPage !== undefined) data.nextPage = Number.isInteger(nextPage) && nextPage >= 1 && nextPage <= 50 ? nextPage : 1
    target?.setItem(`${PREFIX}${category}:${subCategory}`, JSON.stringify({ ...data, updatedAt: now }))
  } catch { /* 隐私模式禁用存储时仍可实时浏览，不阻塞请求。 */ }
}

export function prioritizeUnseen(products, seen) {
  // 只在每批到达时按本次进入前的历史排序，已显示卡片不会因滚动被标记而突然跳位。
  // 未浏览商品保持原热度顺序；都看过时优先较早看过的，不伪装成全是新品。
  return [...products].sort((a, b) => (seen[a.asin] ?? 0) - (seen[b.asin] ?? 0))
}
