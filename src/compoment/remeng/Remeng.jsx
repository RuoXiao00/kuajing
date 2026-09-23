import { request as fetch } from '../../api.js';
import { IS_DEMO } from '../../runtime.js';
import './Remeng.css'
import { useEffect, useMemo, useRef, useState } from 'react'
import { convertToCny, getProductPrice, hasValidPrice, loadExchangeRates } from './productPricing'
import { readFirstPage, saveFirstPage } from './productSnapshot'
import { readDiscovery, rememberDiscovery, prioritizeUnseen } from './productDiscovery'
import { productLink, productMarketLabel } from './productMarketplace'
import { usePreferences } from '../shezhi/usePreferences'

// 热门、推荐和知识库统一使用8000，开发环境由Vite代理，不再额外依赖8001。
const API_BASE_URL = IS_DEMO ? '' : (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '')
const PRODUCTS_API = `${API_BASE_URL}/api/remen/products`
const REQUEST_TIMEOUT = 180_000 // 后端有 120 秒软预算，还要留出最后一页的等待时间。
const EMPTY_PRODUCTS = []

// 文案给用户看，键名发给后端，必须与 pachon.py 的 CATEGORIES 一致。
// 配置放在组件外，不必每次重新渲染都创建一次；以后新增品类也在这里统一维护。
const SUB_CATEGORIES = [
  ['all', '全部品类'], ['shuma', '消费电子与数码'], ['fuzhuan', '服装时尚'],
  ['jiaju', '家具园艺'], ['meir', '美容健康'], ['muying', '母婴玩具'],
  ['qimo', '汽摩配件'], ['shipin', '食品保健品'], ['qita', '其他特色品类'],
]

function ProductImage({ src, title }) {
  // 地址存在也可能加载失败；用文字占位，不请求项目中不存在的 placeholder.png。
  // 记录失败地址，而非永久的 true：同一商品换了图片地址后仍可重新加载。
  const [failedSrc, setFailedSrc] = useState(null)
  if (!src || failedSrc === src) return <div className="rm-image-placeholder">暂无商品图片</div>
  return <img src={src} alt={title} loading="lazy" onError={() => setFailedSrc(src)} />
}

const priceFormatter = new Intl.NumberFormat('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

function ProductPrice({ product, exchange }) {
  const { amount, currency } = getProductPrice(product)
  // 对 0、负数、缺失或非数字统一兜底；这里不把无价格的商品伪装成“免费”。
  if (amount === null || currency === null) return null
  const cny = convertToCny(amount, currency, exchange.rates)
  const original = `${currency} ${priceFormatter.format(amount)}`
  return <div className="rm-product-price">
    <p className="rm-price">{cny === null ? original
      : `人民币${currency === 'CNY' ? '' : '约'} ${cny < 0.01 ? '< ¥0.01' : `¥${priceFormatter.format(cny)}`}`}</p>
    {currency !== 'CNY' && <>
      {cny !== null && <p>原价：{original}</p>}
      <p className="rm-rate-note">{cny !== null ? `汇率日期：${exchange.rates[currency].date}`
          : exchange.status === 'loading' ? '正在获取人民币汇率…' : '暂无可用汇率，保留原币价格'}</p>
    </>}
  </div>
}

export default function Remeng() {
  const { preferences } = usePreferences()
  const [category, setCategory] = useState('hot')
  const [subCategory, setSubCategory] = useState('all')
  const [retryCount, setRetryCount] = useState(0)
  const scrollRef = useRef(null)
  const sentinelRef = useRef(null)
  const loadMoreRef = useRef(null)
  const [exchangeRetry, setExchangeRetry] = useState(0)
  const [exchange, setExchange] = useState({ status: 'loading', rates: null })

  useEffect(() => {
    // 汇率与商品独立加载，失败不会阻塞商品和滚动翻页。离开页面后只停止更新状态；
    // 请求由共享缓存管理，最多等待 10 秒，避免一个组件卸载取消其他组件共用的请求。
    let active = true
    loadExchangeRates().then(rates => {
      if (active) setExchange({ status: 'success', rates })
    }).catch(() => {
      if (active) setExchange({ status: 'error', rates: null })
    })
    return () => { active = false }
  }, [exchangeRetry])
  // 一次请求的状态一起更新。requestKey 标记数据属于哪组筛选；切换按钮后，
  // 即使 effect 尚未执行，也不显示旧结果，避免“新筛选标题配旧商品”。
  const requestKey = `${category}:${subCategory}:${retryCount}`
  // 先显示本地最新快照；新浏览器快速读服务器共享快照，不再绑定固定的商品文件。
  const [result, setResult] = useState(() => {
    const preview = readFirstPage('hot', 'all')
    const history = readDiscovery('hot', 'all')
    return { requestKey: 'hot:all:0', status: 'loading', data: preview
      ? { ...preview, products: prioritizeUnseen(preview.products, history.seen) } : null,
    error: '', nextPage: history.nextPage }
  })
  const currentResult = result.requestKey === requestKey
  // 首屏加载才隐藏列表；翻页加载保留已有卡片和滚动位置，只在底部显示进度。
  const data = currentResult ? result.data : null
  const loading = !currentResult || (result.status === 'loading' && !data)
  const loadingMore = currentResult && result.status === 'loading' && Boolean(data)
  // 显示层也做兜底，让已打开页面中保留的旧状态和旧缓存立即遵守价格过滤规则。
  const products = useMemo(() => data?.products?.filter(hasValidPrice) ?? EMPTY_PRODUCTS, [data?.products])
  const error = currentResult ? result.error : ''

  useEffect(() => {
    // 组件负责同步返回 JSX，不能在函数体里直接 await fetch 或 setState。
    // effect 在首次进入和依赖变化后运行；内部另写 async 函数，才能保留清理函数。
    let active = true
    let inFlight = false
    let controller = null
    let timeoutId = null
    let accumulated = null
    const history = readDiscovery(category, subCategory)
    const startPage = history.nextPage
    let preview = readFirstPage(category, subCategory)
    if (preview) preview = { ...preview, products: prioritizeUnseen(preview.products, history.seen) }
    const snapshotController = new AbortController()
    const snapshotTimeout = window.setTimeout(() => snapshotController.abort(), 5000)
    let nextPage = startPage
    // 每组筛选都有独立的数据、游标和请求锁。切换筛选从第一页开始并回到顶部。
    scrollRef.current?.scrollTo({ top: 0 })

    async function loadProducts() {
      // IntersectionObserver 可能连续通知；同步锁比等待 React 更新 loading 更及时，
      // 保证同一组筛选最多有一个请求，点击“继续加载”也不会重复请求同一页。
      if (!active || inFlight || nextPage === null) return
      inFlight = true
      const page = nextPage
      controller = new AbortController()
      let timedOut = false
      timeoutId = window.setTimeout(() => {
        timedOut = true
        controller.abort()
      }, REQUEST_TIMEOUT)
      setResult({ requestKey, status: 'loading', data: accumulated ?? preview, error: '', nextPage })
      try {
        // URLSearchParams 拼接并编码参数。只传 current，因为后端没有历史销量。
        // 每次只扫描一张搜索页，减小滚动等待；limit 用接口允许的 200，尽量避免
        // 一页商品被低 limit 截掉后，next_page 已前进导致剩余商品无法展示。
        const query = new URLSearchParams({
          category, subCategory, period: 'current', page: String(page), limit: '200', max_pages: '1',
          refresh: String(page === startPage && retryCount > 0),
        })
        const response = await fetch(`${PRODUCTS_API}?${query}`, { signal: controller.signal, cache: 'no-store' })
        // fetch 遇到 429/503 等状态不会自动抛错，必须检查 ok。
        const payload = await response.json().catch(() => null)
        if (!response.ok) {
          const detail = payload?.detail
          const message = typeof detail === 'string' ? detail : detail?.message
          throw new Error(typeof message === 'string' && message
            ? message : `商品加载失败（HTTP ${response.status}），请稍后重试。`)
        }
        if (!payload || !Array.isArray(payload.products)) {
          throw new Error('商品接口返回格式异常，请稍后重试。')
        }
        // 返回值是 { products, warnings, partial, ... }，不是数组本身。
        // 防止异常响应里的 null 或非字符串标题让整个页面渲染崩溃。
        if (payload.products.some(product => !product || typeof product.asin !== 'string'
          || typeof product.title !== 'string')) {
          throw new Error('商品数据格式异常，请稍后重试。')
        }
        if (!active) return

        if (page === 1) saveFirstPage(payload, category, subCategory)

        // next_page 是后端实际扫描后的游标，不能按“已有商品数 / 每页数量”推算。
        // 后端搜索页上限为 50；空游标、倒退游标或越界游标都停止，避免死循环。
        nextPage = Number.isInteger(payload.next_page) && payload.next_page > page
          && payload.next_page <= 50 ? payload.next_page : null
        // 成功之后才记下下次的起点。请求中断/失败不推进，StrictMode重跑也不会跳页。
        rememberDiscovery(category, subCategory, { nextPage: payload.partial ? page : nextPage })
        // preview 仅用于等待时展示，不合并进实时数据。第一页成功后整体替换，
        // 后续页继续按原逻辑追加/去重，旧快照商品不会混入最新第一页或打乱游标。
        const previousProducts = accumulated?.products ?? []
        const byAsin = new Map(previousProducts.map(product => [product.asin, product]))
        // 先过滤再合并/计数，整页无有效价格时暂停自动扫页，仍保留继续加载入口。
        for (const product of prioritizeUnseen(payload.products.filter(hasValidPrice), history.seen)) {
          if (!byAsin.has(product.asin)) byAsin.set(product.asin, product)
        }
        const addedCount = byAsin.size - previousProducts.length
        // 只向尾部追加，不重新排序旧卡片，避免用户阅读时位置跳动。排序是每页内的排序。
        // 累积说明和 partial 标志；混合缓存与新数据时不能把整份列表标成“来自缓存”。
        const previousWarnings = accumulated?.warnings ?? []
        const batchWarnings = Array.isArray(payload.warnings)
          ? payload.warnings.filter(message => typeof message === 'string') : []
        accumulated = {
          ...payload,
          products: [...byAsin.values()],
          warnings: [...new Set([...previousWarnings, ...batchWarnings])],
          partial: Boolean(accumulated?.partial || payload.partial),
          from_cache: Boolean(payload.from_cache && (!accumulated || accumulated.from_cache)),
        }
        // 部分失败或整页没有新增商品时暂停自动请求，保留“继续加载”。尤其小众筛选
        // 可能只是在这一页无匹配，不能谎称后面无商品，也不能自动连续扫完几十页。
        const pauseReason = nextPage !== null && (payload.partial || addedCount === 0)
          ? payload.partial ? '本次抓取未完成，请稍后继续加载。' : '本页没有新增商品，可以继续查找。'
          : ''
        setResult({ requestKey, status: 'success', data: accumulated, error: '', nextPage, pauseReason })
      } catch (cause) {
        if (!active) return
        const message = timedOut
          ? '商品加载超时，请稍后重试。'
          : cause instanceof TypeError
            ? '暂时无法连接后端，已保存的商品仍可浏览。请确认后端运行后重试。'
            : cause instanceof Error ? cause.message : '商品加载失败，请稍后重试。'
        // 请求失败不推进 nextPage，也不清空旧商品；重试仍从失败的那一页开始。
        setResult({ requestKey, status: 'error', data: accumulated ?? preview, error: message, nextPage })
      } finally {
        window.clearTimeout(timeoutId)
        inFlight = false
      }
    }

    // 共享快照只读磁盘，通常远快于抓取。和实时请求并行，任何一方失败不阻塞另一方。
    // 如果实时第一页先返回，慢到的旧快照绝不能覆盖它或打乱后续分页。
    async function readServerSnapshot() {
      try {
        const query = new URLSearchParams({ category, subCategory })
        const response = await fetch(`${PRODUCTS_API}/snapshot?${query}`, {
          signal: snapshotController.signal, cache: 'no-store',
        })
        if (!response.ok) return
        const payload = await response.json()
        if (!active || accumulated) return
        const candidate = readFirstPage(category, subCategory, payload.snapshot)
        if (!candidate) return
        preview = { ...candidate, products: prioritizeUnseen(candidate.products, history.seen) }
        if (candidate.preview_source === 'server') saveFirstPage(payload.snapshot, category, subCategory)
        setResult(previous => previous.requestKey === requestKey ? { ...previous, data: preview } : previous)
      } catch { /* 离线时保留本地首屏；实时请求仍按自己的重试/错误逻辑处理。 */ }
      finally { window.clearTimeout(snapshotTimeout) }
    }

    loadMoreRef.current = loadProducts
    loadProducts()
    readServerSnapshot()
    return () => {
      // 切换品类、离开页面或开发模式重新执行 effect 时，旧请求不应再更新界面。
      // abort 停止浏览器等待，active 再拦截旧响应；不保证后端抓取立即停止。
      active = false
      window.clearTimeout(timeoutId)
      controller?.abort()
      snapshotController.abort()
      window.clearTimeout(snapshotTimeout)
      loadMoreRef.current = null
    }
  }, [category, subCategory, requestKey, retryCount])

  useEffect(() => {
    // 底部的 sentinel 是一个观察点；进入滚动容器底部外 600px 时提前取下一页。
    // root 必须是实际滚动的 .rm，而非 window。每批完成后重新观察，首屏不够高
    // 时也会继续补充；失败/暂停时不观察，避免在视口内无限重试。
    if (!preferences.autoLoadProducts || !currentResult || result.status !== 'success' || result.nextPage === null
      || result.pauseReason || !sentinelRef.current || !('IntersectionObserver' in window)) return
    const observer = new IntersectionObserver(entries => {
      if (entries.some(entry => entry.isIntersecting)) loadMoreRef.current?.()
    }, { root: scrollRef.current, rootMargin: '0px 0px 600px 0px' })
    observer.observe(sentinelRef.current)
    return () => observer.disconnect()
  }, [currentResult, result, preferences.autoLoadProducts])

  useEffect(() => {
    if (!currentResult || !products.length || !('IntersectionObserver' in window)) return
    const observer = new IntersectionObserver(entries => {
      const asins = entries.filter(entry => entry.isIntersecting).map(entry => entry.target.dataset.asin)
      if (asins.length) rememberDiscovery(category, subCategory, { asins })
      for (const entry of entries) if (entry.isIntersecting) observer.unobserve(entry.target)
    }, { root: scrollRef.current, threshold: 0.25 })
    scrollRef.current?.querySelectorAll('[data-product-card]').forEach(card => observer.observe(card))
    return () => observer.disconnect()
  }, [category, subCategory, currentResult, products])

  const warnings = Array.isArray(data?.warnings)
    ? data.warnings.filter(message => typeof message === 'string') : []
  const fetchedAt = data?.fetched_at ? new Date(data.fetched_at) : null
  const fetchedAtText = fetchedAt && !Number.isNaN(fetchedAt.getTime())
    ? fetchedAt.toLocaleString('zh-CN', { hour12: false }) : ''

  return <div className="rm" ref={scrollRef}>
    <header className="rm1">
      <div className="rm1_1">
        <h1>商品发现</h1>
        <div className="rm-mode" role="group" aria-label="商品筛选方式">
          <button type="button" className={category === 'hot' ? 'is-active' : ''}
            aria-pressed={category === 'hot'} onClick={() => setCategory('hot')}>热门</button>
          <button type="button" className={category === 'niche' ? 'is-active' : ''}
            aria-pressed={category === 'niche'} onClick={() => setCategory('niche')}>小众</button>
        </div>
        <button type="button" className="rm-refresh" disabled={loading || loadingMore}
          onClick={() => setRetryCount(count => count + 1)}>更新并换一批</button>
      </div>
      <p className="rm-description">
        {IS_DEMO ? '商品与指标均为人工构造，非实时榜单。可体验品类筛选、币种换算与滚动分页。'
          : <>{category === 'hot' ? '按公开近月购买提示及评论热度筛选。' : '筛选公开评论数不超过 100 的商品。'}
            当前数据来自 Amazon 搜索页，不代表全站榜单。仅展示有有效价格的商品。
            优先展示近7天未浏览的商品，再次进入会接着发现后续页面。</>}
      </p>
      <p className="rm-exchange-note">
        {IS_DEMO ? '汇率采用固定模拟值，只演示转换过程，不供实际交易参考。' : <>人民币为参考换算价，实际付款以商品页为准。
        汇率来源：<a href="https://frankfurter.dev/" target="_blank" rel="noopener noreferrer">Frankfurter</a>。</>}
        {exchange.status === 'error' && <>
          汇率暂不可用，当前显示原币价格。
          <button type="button" onClick={() => {
            setExchange({ status: 'loading', rates: null })
            setExchangeRetry(count => count + 1)
          }}>重试汇率</button>
        </>}
      </p>
      {/* button 代替可点击 span，键盘 Tab / Enter 也可以操作；全部品类对应默认 all。 */}
      <div className="rm1_2" role="group" aria-label="商品品类">
        {SUB_CATEGORIES.map(([value, label]) => <button key={value} type="button"
          className={subCategory === value ? 'is-active' : ''} aria-pressed={subCategory === value}
          onClick={() => setSubCategory(value)}>{label}</button>)}
      </div>
    </header>

    <section className="rm-results" aria-label="商品结果" aria-busy={loading || loadingMore}>
      {loading && <div className="rm-status" role="status">正在读取最新商品…</div>}
      {error && !data && <div className="rm-status rm-error" role="alert">
        <p>{error}</p>
        <button type="button" onClick={() => setRetryCount(count => count + 1)}>重试</button>
      </div>}
      {data && <>
        <div className="rm-summary" role="status">
          <span>已加载 {products.length} 件商品{data.partial ? ' · 含部分抓取结果' : ''}</span>
          <span>{IS_DEMO ? '项目内置样例 · 非真实抓取' : data.is_preview ? `${data.preview_source === 'saved' ? '上次保存的商品' : '服务器最近更新的商品'} · ${loadingMore ? '正在获取最新数据' : '更新暂未成功，保留快照'}`
            : data.from_cache ? '来自近期缓存' : '含本次抓取数据'}{fetchedAtText ? ` · 最近一批快照时间：${fetchedAtText}` : ''}</span>
        </div>
        {/* 中途失败时后端仍可能返回商品。保留结果并展示 warnings，不伪装完整成功。 */}
        {warnings.length > 0 && <details className="rm-notice" open={Boolean(data.partial)}>
          <summary>{data.partial ? '部分数据未能获取，查看说明' : '数据说明'}</summary>
          <ul>{warnings.map((message, index) => <li key={index}>{message}</li>)}</ul>
        </details>}
        {products.length === 0
          ? <div className="rm-status" role="status">当前已扫描的页面没有符合条件且有有效价格的商品。</div>
          : <div className="rm2">
            {/* JSX 里的 JavaScript 表达式必须放在花括号内；ASIN 是去重后的稳定商品 ID。 */}
            {products.map(product => <article className="rm-product" key={product.asin} data-product-card data-asin={product.asin}>
              <div className="rm-product-image"><ProductImage src={product.image_url} title={product.title} /></div>
              <div className="rm-product-body">
                <h2>{product.title}</h2>
                <ProductPrice product={product} exchange={exchange} />
                {/* sales 是页面原文的近月购买提示，不是精确销量；缺失不能显示成 0。 */}
                <p>近月购买提示：{product.sales || '未公开'}</p>
                <p>评分：{product.rating ?? '未公开'} · 评论数：{product.review_count ?? '未公开'}</p>
                <p>来源：{IS_DEMO ? '人工构造的演示商品' : productMarketLabel(product)}</p>
                {/* 校验区域站白名单，保留原站点；日本站的价格不能链接到美国站商品。 */}
                <a href={IS_DEMO ? product.image_url : productLink(product)}
                  target="_blank" rel="noopener noreferrer">{IS_DEMO ? '查看示意图' : '查看商品'} ↗</a>
              </div>
            </article>)}
          </div>}
        {/* 底部始终保留观察点；网络失败时只重试下一页，已加载商品仍然可浏览。 */}
        <div className="rm-load-more" ref={sentinelRef}>
          {loadingMore ? <p role="status">{data.is_preview ? '正在更新商品，可先浏览已保存的内容…' : '正在加载更多商品…'}</p>
            : error ? <div role="alert">
              <p>{error}</p>
              <button type="button" onClick={() => loadMoreRef.current?.()}>{data.is_preview ? '重试更新商品' : '重试加载更多'}</button>
            </div>
              : result.nextPage === null ? <p role="status">已到当前可浏览结果的末尾，可切换品类继续发现商品。</p>
                : <>
                  <p role="status">{result.pauseReason || (preferences.autoLoadProducts
                    ? '继续向下滑动，自动加载更多商品' : '自动加载已关闭，点击下方按钮加载更多商品')}</p>
                  <button type="button" onClick={() => loadMoreRef.current?.()}>继续加载</button>
                </>}
        </div>
      </>}
    </section>
  </div>
}
