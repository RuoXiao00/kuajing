import { request as fetch } from '../../api.js';
import { IS_DEMO } from '../../runtime.js';
import './Remeng.css'
import { useEffect, useMemo, useRef, useState } from 'react'
import { convertToCny, getProductPrice, loadExchangeRates } from './productPricing'
import { readSavedSnapshot, saveSnapshot, snapshotView, revealMoreProducts, watchSharedSnapshot } from './dailySnapshot'
import { readDiscovery, rememberDiscovery } from './productDiscovery'
import { productLink, productMarketLabel } from './productMarketplace'
import { usePreferences } from '../shezhi/usePreferences'

// 热门、推荐和知识库统一使用8000，开发环境由Vite代理，不再额外依赖8001。
const API_BASE_URL = IS_DEMO ? '' : (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '')
const PRODUCTS_API = `${API_BASE_URL}/api/remen/products`
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
  const requestKey = `${category}:${subCategory}:${retryCount}`
  const [result, setResult] = useState(() => ({ requestKey: 'hot:all:0', status: 'loading',
    ...snapshotView(null, readSavedSnapshot('hot', 'all'), readDiscovery('hot', 'all').seen), error: '' }))
  const currentResult = result.requestKey === requestKey
  const data = currentResult ? result.data : null
  const loading = !currentResult || (result.status === 'loading' && !data)
  const loadingMore = currentResult && result.status === 'loading' && Boolean(data)
  const products = useMemo(() => data?.products?.slice(0, result.visibleCount) ?? EMPTY_PRODUCTS,
    [data?.products, result.visibleCount])
  const hasMore = Boolean(data && result.visibleCount < data.products.length)
  const error = currentResult ? result.error : ''

  useEffect(() => {
    // 一次读取整份共享快照；切换筛选后丢弃旧响应，不沿用旧版 Amazon 页码。
    const seen = readDiscovery(category, subCategory).seen
    const preview = snapshotView(null, readSavedSnapshot(category, subCategory), seen)
    scrollRef.current?.scrollTo({ top: 0 })
    // 此状态来自切换筛选后的外部存储快照，与当前请求一起替换。
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setResult({ requestKey, status: 'loading', ...preview, error: '' })
    loadMoreRef.current = () => setResult(previous => previous.requestKey === requestKey
      ? revealMoreProducts(previous) : previous)
    const stop = watchSharedSnapshot({ endpoint: `${PRODUCTS_API}/snapshot`, category, subCategory, fetcher: fetch,
      onResult: ({ snapshot, updateStatus, lastError, willPoll }) => {
        if (snapshot) saveSnapshot(snapshot, category, subCategory)
        setResult(previous => {
          if (previous.requestKey !== requestKey) return previous
          const view = snapshot ? snapshotView(previous, snapshot, seen) : previous
          return { ...view, requestKey, status: 'success', updateStatus,
            error: updateStatus === 'update_failed' ? lastError || '今日更新暂未成功，稍后重试读取。'
              : !snapshot && !willPoll ? '共享商品数据尚未准备好，请稍后刷新展示。' : '',
            waiting: willPoll }
        })
      },
      onError: message => setResult(previous => previous.requestKey === requestKey
        ? { ...previous, status: 'error', waiting: false, error: message } : previous),
    })
    return () => { stop(); loadMoreRef.current = null }
  }, [category, subCategory, requestKey])

  useEffect(() => {
    // 下滑只增加可见条数，不调用网络。每次默认展示 20 件，直到当前快照展示完毕。
    if (!preferences.autoLoadProducts || !hasMore || !sentinelRef.current
      || !('IntersectionObserver' in window)) return
    const observer = new IntersectionObserver(entries => {
      if (entries.some(entry => entry.isIntersecting)) loadMoreRef.current?.()
    }, { root: scrollRef.current, rootMargin: '0px 0px 600px 0px' })
    observer.observe(sentinelRef.current)
    return () => observer.disconnect()
  }, [hasMore, result.visibleCount, preferences.autoLoadProducts])

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
          onClick={() => setRetryCount(count => count + 1)}>刷新展示</button>
      </div>
      <p className="rm-description">
        {IS_DEMO ? '商品与指标均为人工构造，非实时榜单。可体验品类筛选、币种换算与滚动分页。'
          : <>{category === 'hot' ? '按公开近月购买提示及评论热度筛选。' : '筛选公开评论数不超过 100 的商品。'}
            当前数据来自 Amazon 搜索页，不代表全站榜单。仅展示有有效价格的商品。
            每日共享更新，优先展示近7天未浏览的商品，下滑分批显示已保存的结果。</>}
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
      {!loading && !data && !error && <div className="rm-status" role="status">今日共享数据正在准备，稍后自动读取…</div>}
      {error && !data && <div className="rm-status rm-error" role="alert">
        <p>{error}</p>
        <button type="button" onClick={() => setRetryCount(count => count + 1)}>重试</button>
      </div>}
      {data && <>
        <div className="rm-summary" role="status">
          <span>已展示 {products.length} / {data.products.length} 件商品</span>
          <span>{IS_DEMO ? '项目内置样例 · 非真实抓取' : data.is_stale ? '上次成功保存的数据 · 今日更新待完成'
            : '每日共享数据'}{fetchedAtText ? ` · 采集时间：${fetchedAtText}` : ''}</span>
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
        <div className="rm-load-more" ref={sentinelRef}>
          {loadingMore && <p role="status">正在读取服务器快照，可先浏览已保存的内容…</p>}
          {error && <div role="alert"><p>{error}</p>
            <button type="button" onClick={() => setRetryCount(count => count + 1)}>重试读取</button></div>}
          {result.waiting && <p role="status">今日数据正在准备，稍后自动读取更新。</p>}
          {hasMore ? <>
            <p>{preferences.autoLoadProducts ? '向下滑动，继续展示已保存的商品' : '点击下方按钮展示更多商品'}</p>
            <button type="button" onClick={() => loadMoreRef.current?.()}>显示更多</button>
          </> : <p role="status">本期商品已全部展示，可切换品类继续浏览。</p>}
        </div>
      </>}
    </section>
  </div>
}
