import { request as fetch } from '../../api.js';
import { IS_DEMO } from '../../runtime.js';
import { useEffect, useRef, useState } from 'react';
import './Tuijian.css';

// 同源 /api 由现有 Vite 代理转发。页面只读每日快照，绝不触发模型或抓取。
const API_BASE_URL = IS_DEMO ? '' : (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '');
const categoryKey = (category) => category?.candidate_id || category?.keyword || category?.title || '';

function displayTime(value) {
  const date = value ? new Date(value) : null;
  return date && !Number.isNaN(date.getTime())
    ? date.toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false }) : '尚未生成';
}

export default function Tuijian() {
  const [data, setData] = useState(null);
  const [selection, setSelection] = useState({ index: 0, key: '' });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const refreshRef = useRef(null);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const detailsRef = useRef(null);
  const detailsButtonRef = useRef(null);
  const detailsPanelRef = useRef(null);
  const categories = data?.categories ?? [];
  // 翻页直接记录下标；旧记录有重复/缺失关键词时，也不会被 findIndex 拉回第一类。
  // 新快照中类别位置改变时再按稳定标识定位，同一期刷新保持当前页。
  const safePage = categories[selection.index] && categoryKey(categories[selection.index]) === selection.key
    ? selection.index : Math.max(0, categories.findIndex(item => categoryKey(item) === selection.key));
  const category = categories[safePage] || null;

  function closeDetails(returnFocus = false) {
    setDetailsOpen(false);
    if (returnFocus) detailsButtonRef.current?.focus();
  }

  useEffect(() => {
    if (!detailsOpen) return undefined;
    // 悬浮层不占用商品布局；点击外部/移走键盘焦点时收起，Esc 回到触发按钮。
    detailsPanelRef.current?.focus();
    const dismissOutside = event => {
      if (!detailsRef.current?.contains(event.target)) setDetailsOpen(false);
    };
    const onKeyDown = event => {
      if (event.key === 'Escape') {
        event.preventDefault();
        setDetailsOpen(false);
        detailsButtonRef.current?.focus();
      }
    };
    document.addEventListener('pointerdown', dismissOutside);
    document.addEventListener('focusin', dismissOutside);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('pointerdown', dismissOutside);
      document.removeEventListener('focusin', dismissOutside);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [detailsOpen]);

  useEffect(() => {
    let active = true;
    let busy = false;
    let controller = null;
    let timeoutId = null;

    async function readSnapshot(showLoading = false) {
      // 定时轮询、焦点事件和点击可能同时到达；同步锁避免相同页面并发请求。
      if (!active || busy) return;
      busy = true;
      if (showLoading) setLoading(true);
      controller = new AbortController();
      timeoutId = window.setTimeout(() => controller.abort(), 15_000);
      try {
        const response = await fetch(`${API_BASE_URL}/api/recommendations/latest`, {
          signal: controller.signal, cache: 'no-store',
        });
        if (!response.ok) throw new Error(`读取推荐失败（HTTP ${response.status}）`);
        const snapshot = await response.json();
        if (!Array.isArray(snapshot.categories)) throw new Error('每日推荐返回格式异常');
        if (!active) return;
        // 同一期只刷新任务状态，保留卡片对象与当前类别；新一期按 keyword 保留类别，
        // 如果新一期没有这个类别，safePage 自动回到第一类。轮询不会把用户翻页重置。
        setData(previous => previous?.snapshot_id && previous.snapshot_id === snapshot.snapshot_id
          && previous.presentation_version === snapshot.presentation_version
          ? { ...snapshot, categories: previous.categories } : snapshot);
        setError('');
      } catch (cause) {
        if (active) setError(cause.name === 'AbortError' ? '读取推荐超时，请刷新展示重试。'
          : cause instanceof TypeError ? '暂时无法连接推荐服务，已加载内容仍可查看。' : cause.message);
      } finally {
        window.clearTimeout(timeoutId);
        busy = false;
        if (active) setLoading(false);
      }
    }

    refreshRef.current = () => readSnapshot(true);
    readSnapshot();
    // 后台页面不轮询；可见页面每分钟检查快照，跨过05:00后也能发现新一期。
    const poll = () => { if (document.visibilityState === 'visible') readSnapshot(); };
    const intervalId = window.setInterval(poll, 60_000);
    document.addEventListener('visibilitychange', poll);
    window.addEventListener('focus', poll);
    return () => {
      active = false;
      controller?.abort();
      window.clearTimeout(timeoutId);
      window.clearInterval(intervalId);
      document.removeEventListener('visibilitychange', poll);
      window.removeEventListener('focus', poll);
      refreshRef.current = null;
    };
  }, []);

  const updateText = {
    demo: '预置演示快照 · 非实时推荐',
    pending: '等待后台生成每日推荐', updating: '后台正在更新，已有结果仍可查看',
    ready: '每日推荐已更新', update_failed: '上次更新未完成，保留最近可用结果',
  }[data?.update_status] || '正在读取每日推荐';

  return <main className="tuijian">
    {/* 更新和来源按需展开，不挤占产品区，也不触发新的生成任务。 */}
    <div className="recommendation-info" ref={detailsRef}>
      <button className="recommendation-info-trigger" type="button" ref={detailsButtonRef}
        aria-expanded={detailsOpen} aria-controls="recommendation-info-panel"
        onClick={() => setDetailsOpen(open => !open)}>
        更新与来源 <span aria-hidden="true">{detailsOpen ? '⌃' : '⌄'}</span>
      </button>
      {detailsOpen && <section className="recommendation-details" id="recommendation-info-panel"
        aria-labelledby="recommendation-info-title" ref={detailsPanelRef} tabIndex={-1}>
        <div className="recommendation-info-heading">
          <h2 id="recommendation-info-title">更新与资料来源</h2>
          <button className="recommendation-info-close" type="button" aria-label="关闭更新与来源"
            onClick={() => closeDetails(true)}>×</button>
        </div>
      <section className="recommendation-snapshot" aria-label="每日推荐更新状态">
        <div>
          <strong>{IS_DEMO ? '产品推荐 · 交互展示' : '每日推荐 · 北京时间 05:00 开始更新'}</strong>
          <p role="status">{updateText}{data?.partial ? ' · 当前展示部分结果' : ''}{data?.is_stale ? ' · 当前为历史结果' : ''}</p>
          <p>{IS_DEMO ? '样例日期' : '实际生成时间'}：{displayTime(data?.generated_at)}</p>
          {data?.next_update_at && <p>下次定时更新：{displayTime(data.next_update_at)}</p>}
          {data?.retry_at && <p>后台补试时间：{displayTime(data.retry_at)}</p>}
          {data?.last_error && <p className="recommendation-job-error">{data.last_error}</p>}
        </div>
        <button type="button" onClick={() => refreshRef.current?.()} disabled={loading}>
          {loading ? '正在读取…' : '刷新展示'}
        </button>
      </section>
      {/* 来源随快照发布，不在浏览器里另行联网查趋势，刷新不会触发后台生成。 */}
      {data?.evidence?.scope && <section className="recommendation-evidence" aria-label="推荐数据来源">
        <strong>先采集资料，再筛选推荐</strong>
        <p>{data.evidence.scope}</p>
        <p>本期采样 {data.evidence.sampled_categories ?? 0} 个领域，
          {data.evidence.available_categories ?? 0} 个有商品数据，
          共 {data.evidence.candidate_products ?? 0} 件不同候选商品。</p>
        <ul>{data.evidence.sources?.map(source => <li key={source.id}>
          <a href={source.url} target="_blank" rel="noopener noreferrer">{source.name}</a>
          {' · '}{source.status === 'ok' ? `取得 ${source.items.length} 条资料` : '本期未取得可用资料'}
          {' · '}{displayTime(source.fetched_at)}
        </li>)}</ul>
      </section>}
      </section>}
    </div>
    {error && <p className="recommendation-notice" role="alert">{error}</p>}
    {!category ? <div className="recommendation-empty" role="status">
      {loading ? '正在读取已保存的推荐…' : '暂时没有可展示的每日推荐。后端会自动生成，完成后此页面自动更新。'}
    </div> : <>
      <header className="category-heading">
        <span className="category-index">CATEGORY {String(safePage + 1).padStart(2, '0')}</span>
        <h1>{category.title || '未命名产品类别'}</h1>
        {category.status === 'partial' && <span className="category-status">部分数据可用</span>}
        {category.status === 'error' && <span className="category-status">{category.error || '商品数据暂不可用'}</span>}
        {category.warnings?.map((warning, index) => <p className="category-status" key={index}>{warning}</p>)}
      </header>
      <section className="category-products" aria-label={`${category.title || '当前类别'}的推荐商品`}>
        {category.products?.slice(0, 5).map(product => <a className="product-tile"
          href={product.url || '#'} target="_blank" rel="noopener noreferrer" key={product.asin}>
          {product.image_url ? <img src={product.image_url} alt={product.title || '推荐商品'} />
            : <div className="image-placeholder">暂无图片</div>}
          <span className="product-title">{product.title || '暂无标题'}</span>
        </a>)}
      </section>
      <section className="ai-analysis" aria-labelledby="analysis-title">
        <div className="analysis-label" id="analysis-title">推荐依据</div>
        <p>{category.answer || category.error || '分析尚未完成，等待后台补试。'}</p>
        {category.analysis_warning && <p className="category-status">{category.analysis_warning}</p>}
        {category.selection_reason && <p>入选依据：{category.selection_reason}</p>}
        {Number.isInteger(category.recent_repeat_count) && <p>
          近 7 天未推荐：{category.new_product_count} 件；重复推荐：{category.recent_repeat_count} 件。
          重复项来自热度保留或新候选不足，不代表新品。
        </p>}
        {category.source_url && <p><a href={category.source_url} target="_blank" rel="noopener noreferrer">
          查看商品采样来源</a> · {displayTime(category.fetched_at)}</p>}
        {category.evidence_links?.map(item => <p key={item.evidence_id}>
          辅助资料：<a href={item.url} target="_blank" rel="noopener noreferrer">{item.title}</a>
          {' · '}{item.source_name}
        </p>)}
      </section>
      <nav className="page-controls" aria-label="产品类别翻页" translate="no">
        <button type="button" disabled={safePage === 0}
          onClick={() => setSelection({ index: safePage - 1, key: categoryKey(categories[safePage - 1]) })}>↑ 上一类</button>
        {/* 每次翻页替换计数节点，避免浏览器翻译产生的旧文本节点停留在 1/10。 */}
        <output key={`${safePage}:${categories.length}`} aria-live="polite" aria-label="当前类别序号">{safePage + 1} / {categories.length}</output>
        <button type="button" disabled={safePage >= categories.length - 1}
          onClick={() => setSelection({ index: safePage + 1, key: categoryKey(categories[safePage + 1]) })}>下一类 ↓</button>
      </nav>
    </>}
  </main>;
}
