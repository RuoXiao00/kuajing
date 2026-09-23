import { useEffect, useRef, useState } from 'react';
import { ACTIVE, API_BASE, imageRequest, MODES, ROLES, STATUS } from './imageApi';
import './Tupian.css';

const fullUrl = (path) => `${API_BASE}${path}`;
const formatTime = (value) => new Date(value).toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' });

// 上传入口固定在底部；多种参考图通过轻量浮层选择，文件预览独立显示在提示词上方。
function ReferenceUpload({ roles, references, total, onChange, disabled }) {
  const inputs = useRef({});
  const menu = useRef(null);
  const [position, setPosition] = useState({});
  const [open, setOpen] = useState(false);
  return <div className="ig-upload-control">
    {roles.map(role => <input key={role} ref={node => { inputs.current[role] = node; }} type="file" hidden
      accept="image/jpeg,image/png,image/webp" multiple disabled={disabled}
      aria-label={`上传${ROLES[role]}`} onChange={event => {
        onChange(role, Array.from(event.target.files)); event.target.value = ''; menu.current?.hidePopover();
      }} />)}
    <button type="button" className="ig-upload-button" disabled={disabled}
      popoverTarget={roles.length > 1 ? 'ig-upload-options' : undefined}
      aria-expanded={roles.length > 1 ? open : undefined}
      onClick={event => {
        if (roles.length === 1) { inputs.current.product?.click(); return; }
        const rect = event.currentTarget.getBoundingClientRect();
        setPosition({ left: Math.min(rect.left, window.innerWidth - 256), bottom: window.innerHeight - rect.top + 8 });
      }}><span aria-hidden="true">＋</span> 上传图片</button>
    {roles.length > 1 && <div id="ig-upload-options" className="ig-upload-options" popover="auto" ref={menu}
      style={position} onToggle={event => setOpen(event.newState === 'open')}>
      <strong>选择参考图类型</strong>
      {roles.map(role => <button key={role} type="button" disabled={disabled || references[role].length >= 2 || total >= 5}
        onClick={() => inputs.current[role]?.click()}>
        <span>{ROLES[role]} <small>{role === 'product' ? '必填' : '可选'}</small></span><span>{references[role].length}/2 ＋</span>
      </button>)}
      <p>共最多 5 张 · JPG / PNG / WebP<br />每张不超过 10 MB</p>
    </div>}
  </div>;
}

function Generation({ job, onPreview, onRetrySave, onReuse }) {
  const pending = ACTIVE.has(job.status);
  const mode = MODES.find((item) => item.id === job.mode);
  const description = job.prompt || '根据产品图生成，未填写提示词';
  return <article className="ig-turn" aria-label={`生成记录：${description}`}>
    <div className="ig-user-message">
      <div className="ig-message-meta">{mode?.label} <span>· {formatTime(job.created_at)}</span></div>
      <p>{description}</p>
      <div className="ig-sent-references">{job.references.map((item) => <button type="button" key={item.slot}
        onClick={() => onPreview({ ...item, label: ROLES[item.slot.split('_img')[0]] })}>
        <img src={fullUrl(item.url)} alt={ROLES[item.slot.split('_img')[0]]} loading="lazy" />
        <span>{ROLES[item.slot.split('_img')[0]]}</span>
      </button>)}</div>
    </div>
    <div className="ig-assistant-message">
      <div className="ig-assistant-heading"><span className="ig-avatar" aria-hidden="true">✧</span><strong>图片工作室</strong><span className={`ig-status ${pending ? 'is-active' : ''}`}>{STATUS[job.status]}</span></div>
      {job.reply && <p className="ig-reply">{job.reply}</p>}
      {pending && <p className="ig-progress" role="status"><span className="ig-spinner" />{STATUS[job.status]}，完成的图片会出现在这里。你可以切换页面，稍后回来查看。</p>}
      {(job.images.length > 0 || pending) && <div className="ig-results">
        {job.images.map((item) => <figure className="ig-result" key={item.name}>
          <button className="ig-result-image" type="button" onClick={() => onPreview({ ...item, label: `生成图片 ${item.index + 1}` })} aria-label={`放大生成图片 ${item.index + 1}`}>
            <img src={fullUrl(item.url)} alt={`${job.prompt} · 方案 ${item.index + 1}`} loading="lazy" />
            <span className="ig-zoom-hint">点击查看大图 ↗</span>
          </button>
          <figcaption><span>方案 {String(item.index + 1).padStart(2, '0')}</span><a href={fullUrl(`${item.url}?download=true`)} download={item.name}>↓ 保存原图</a></figcaption>
        </figure>)}
        {pending && Array.from({ length: Math.max(0, 4 - job.images.length) }, (_, i) => <div className="ig-placeholder" key={`pending-${i}`}><span>✧</span><p>让灵感成像</p></div>)}
      </div>}
      {job.images.length > 0 && <p className="ig-saved-note">✓ {job.images.length} 张原图已保存到本机，刷新后仍可查看和下载。</p>}
      {job.error && <p className="ig-error" role="alert">{job.error}</p>}
      {!pending && <div className="ig-turn-actions">
        {job.can_retry_save && <button type="button" onClick={() => onRetrySave(job.id)}>重试保存图片</button>}
        <button type="button" onClick={() => onReuse(job)}>复用提示词</button>
      </div>}
    </div>
  </article>;
}

export default function Tupian() {
  const [jobs, setJobs] = useState([]);
  const [before, setBefore] = useState(null);
  const [ready, setReady] = useState(false);
  const [configured, setConfigured] = useState(true);
  const [error, setError] = useState('');
  const [mode, setMode] = useState('product');
  const [prompt, setPrompt] = useState('');
  const [references, setReferences] = useState({ product: [], model: [], background: [] });
  const [submitting, setSubmitting] = useState(false);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [preview, setPreview] = useState(null);
  const [showReferences, setShowReferences] = useState(true);
  const [refreshKey, setRefreshKey] = useState(0);
  const scrollRef = useRef(null);
  const textareaRef = useRef(null);
  const dialogRef = useRef(null);
  const objectUrls = useRef(new Set());
  const submissionId = useRef(null);
  const submittingRef = useRef(false);
  const selectedMode = MODES.find((item) => item.id === mode);
  const pendingIds = jobs.filter((job) => ACTIVE.has(job.status)).map((job) => job.id).join(',');
  const busy = submitting || Boolean(pendingIds);
  const totalReferences = selectedMode.roles.reduce((total, role) => total + references[role].length, 0);
  // Coze 开始节点只有 product_img1 必填；模特/背景参考图和提示词都不能阻止提交。
  // mode 仍由页面提供，后端把它转换成必填的 need_what，无需用户另填。
  const missingProduct = references.product.length === 0;
  const submitHint = !ready ? '正在连接图片服务…' : !configured ? '请先配置后端 Coze 令牌'
    : busy ? '创作进行中，参考图会保留供下次使用' : totalReferences > 5 ? '参考图合计最多 5 张'
    : missingProduct ? '请先上传产品图，提示词和其他参考图均可选' : '提示词可留空 · Ctrl / ⌘ + Enter 发送';

  // 首次进入只读历史并初始化私有 Cookie；刷新不会再次执行工作流。
  useEffect(() => {
    const controller = new AbortController();
    imageRequest('/history', { signal: controller.signal }).then((data) => {
      setJobs(data.jobs); setBefore(data.before); setConfigured(data.configured); setReady(true); setError('');
      requestAnimationFrame(() => { if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight; });
    }).catch((failure) => { if (failure.name !== 'AbortError') setError(failure.message); });
    return () => controller.abort();
  }, [refreshKey]);

  // 仅轮询运行中的任务，切回页面立即补读。后端任务不会随组件卸载而终止。
  useEffect(() => {
    if (!pendingIds) return undefined;
    const controller = new AbortController();
    let timer;
    let reading = false;
    const poll = async () => {
      if (reading || controller.signal.aborted) return;
      clearTimeout(timer); reading = true;
      try {
        const updated = await Promise.all(pendingIds.split(',').map((id) => imageRequest(`/jobs/${id}`, { signal: controller.signal })));
        setJobs((current) => current.map((job) => updated.find((item) => item.id === job.id) || job)); setError('');
      } catch (failure) { if (failure.name !== 'AbortError') setError(failure.message); }
      finally { reading = false; if (!controller.signal.aborted) timer = setTimeout(poll, document.hidden ? 10000 : 1800); }
    };
    const onVisible = () => { if (!document.hidden) void poll(); };
    void poll(); document.addEventListener('visibilitychange', onVisible);
    return () => { controller.abort(); clearTimeout(timer); document.removeEventListener('visibilitychange', onVisible); };
  }, [pendingIds]);

  // Object URL 只是待上传参考图的临时预览，离开页面后释放以免占用内存。
  useEffect(() => {
    const urls = objectUrls.current;
    return () => { urls.forEach((url) => URL.revokeObjectURL(url)); urls.clear(); };
  }, []);
  useEffect(() => { if (preview && dialogRef.current && !dialogRef.current.open) dialogRef.current.showModal(); }, [preview]);

  function changeReferences(role, incoming, removeIndex) {
    submissionId.current = null;
    if (incoming === null) {
      const removed = references[role][removeIndex]; URL.revokeObjectURL(removed.url); objectUrls.current.delete(removed.url);
      setReferences((current) => ({ ...current, [role]: current[role].filter((_, index) => index !== removeIndex) })); return;
    }
    if (references[role].length + incoming.length > 2 || totalReferences + incoming.length > 5) { setError('每种参考图最多 2 张，每次合计最多 5 张。'); return; }
    if (incoming.some((file) => !['image/jpeg', 'image/png', 'image/webp'].includes(file.type) || file.size > 10 * 1024 * 1024)) { setError('请选择不超过 10 MB 的 JPG、PNG 或 WebP 图片。'); return; }
    const items = incoming.map((file) => { const url = URL.createObjectURL(file); objectUrls.current.add(url); return { file, url }; });
    setReferences((current) => ({ ...current, [role]: [...current[role], ...items] })); setShowReferences(true); setError('');
  }

  async function submit(event) {
    event.preventDefault();
    if (submittingRef.current || busy || !ready) return;
    if (missingProduct || totalReferences > 5) { setError('请上传至少 1 张产品图，参考图合计最多 5 张。提示词可留空。'); return; }
    submittingRef.current = true; setSubmitting(true); setError('');
    // 网络重试沿用 request_id，后端会返回原任务，避免重复执行收费工作流。
    submissionId.current ||= crypto.randomUUID();
    const form = new FormData();
    form.append('request_id', submissionId.current); form.append('prompt', prompt.trim()); form.append('mode', mode);
    selectedMode.roles.forEach((role) => references[role].forEach((item, index) => form.append(`${role}_img${index + 1}`, item.file)));
    try {
      const job = await imageRequest('/jobs', { method: 'POST', body: form });
      setJobs((current) => current.some((item) => item.id === job.id) ? current : [...current, job]);
      submissionId.current = null; setPrompt(''); setShowReferences(false);
      requestAnimationFrame(() => { scrollRef.current?.querySelector('.ig-turn:last-child')?.scrollIntoView({ block: 'start', behavior: 'smooth' }); });
    } catch (failure) { setError(failure.message); }
    finally { submittingRef.current = false; setSubmitting(false); }
  }

  async function retrySave(id) {
    try { const job = await imageRequest(`/jobs/${id}/retry-save`, { method: 'POST' }); setJobs((current) => current.map((item) => item.id === id ? job : item)); setError(''); }
    catch (failure) { setError(failure.message); }
  }
  async function loadOlder() {
    setLoadingOlder(true); const scroll = scrollRef.current; const height = scroll.scrollHeight;
    try {
      const data = await imageRequest(`/history?before=${encodeURIComponent(before)}`);
      setJobs((current) => [...data.jobs.filter((job) => !current.some((item) => item.id === job.id)), ...current]); setBefore(data.before);
      requestAnimationFrame(() => { scroll.scrollTop += scroll.scrollHeight - height; });
    } catch (failure) { setError(failure.message); }
    finally { setLoadingOlder(false); }
  }

  return <div className="ig-page">
    <header className="ig-header"><div><span className="ig-eyebrow">IMAGE STUDIO</span><h1>图片工作室 <span>让产品，多一种可能。</span></h1></div><span className="ig-local-badge"><i /> 原图本地保存</span></header>
    <div className="ig-conversation" ref={scrollRef}><div className="ig-thread">
      {before && <button className="ig-history-button" type="button" disabled={loadingOlder} onClick={loadOlder}>{loadingOlder ? '正在读取…' : '查看更早的创作'}</button>}
      {!ready && !error && <p className="ig-loading" role="status">正在打开你的工作室…</p>}
      {ready && !jobs.length && <section className="ig-welcome">
        <div className="ig-welcome-mark" aria-hidden="true">✧</div><span className="ig-eyebrow">从一张产品图开始</span>
        <h2>把你的想法，<br />变成产品的下一张好图。</h2>
        <p>上传产品图即可开始，也可以补充你想要的画面。<br />一次创作四张，灵感和原图都留在这里。</p>
        <div className="ig-suggestions">{[
          ['干净白底', '为产品制作干净的白底电商主图，保留产品结构、颜色与品牌细节，使用柔和棚拍光线。'],
          ['自然光影', '以自然光影呈现产品的材质和细节，构图简洁，保留产品原本的颜色和外观，画面不要添加文字。'],
          ['质感特写', '为产品制作具有高级质感的细节特写，用细腻的光线突出材质，保留产品真实结构。'],
        ].map(([label, text]) => <button type="button" key={label} onClick={() => { setPrompt(text); submissionId.current = null; textareaRef.current?.focus(); }}>{label} ↗</button>)}</div>
      </section>}
      {jobs.map((job) => <Generation key={job.id} job={job} onPreview={setPreview} onRetrySave={retrySave}
        onReuse={(item) => { setPrompt(item.prompt); setMode(item.mode); submissionId.current = null; setShowReferences(true); textareaRef.current?.focus(); }} />)}
    </div></div>
    <div className="ig-composer-wrap">
      {!configured && ready && <p className="ig-error" role="alert">后端尚未配置 Coze 令牌，请配置后重新打开页面。</p>}
      {error && <div className="ig-error" role="alert">{error} {!ready && <button type="button" onClick={() => setRefreshKey((key) => key + 1)}>重新连接</button>}</div>}
      {/* 只在有图片时显示上方预览；上传、生成类型和发送集中在底部一行。 */}
      <form className="ig-composer" onSubmit={submit}>
        {totalReferences > 0 && <div className="ig-reference-bar">
          {showReferences && <div className="ig-references" aria-label="已上传参考图">
            {selectedMode.roles.flatMap(role => references[role].map((item, index) => <div className="ig-reference-preview" key={item.url}>
              <img src={item.url} alt={`${ROLES[role]} ${index + 1}`} />
              <span className="ig-reference-kind">{ROLES[role]}</span>
              <button type="button" disabled={busy} aria-label={`移除${ROLES[role]} ${index + 1}`}
                onClick={() => changeReferences(role, null, index)}>×</button>
            </div>))}
          </div>}
          <button type="button" className="ig-reference-toggle" aria-expanded={showReferences}
            onClick={() => setShowReferences(value => !value)}>参考图片 <span>{totalReferences}/5</span> {showReferences ? '⌃' : '⌄'}</button>
        </div>}
        <textarea ref={textareaRef} rows={2} value={prompt} maxLength={3000} disabled={submitting} aria-label="图片提示词" aria-describedby="ig-submit-hint" placeholder="提示词（可选）：描述光线、构图或材质，留空也能生成…"
          onChange={(event) => { setPrompt(event.target.value); submissionId.current = null; }}
          onKeyDown={(event) => { if (event.key === 'Enter' && (event.ctrlKey || event.metaKey) && !event.nativeEvent.isComposing) { event.preventDefault(); event.currentTarget.form.requestSubmit(); } }} />
        <div className="ig-composer-bottom">
          <ReferenceUpload key={mode} roles={selectedMode.roles} references={references} total={totalReferences} onChange={changeReferences} disabled={busy} />
          <span id="ig-submit-hint" role="status">{submitHint}</span>
          <div className="ig-controls"><label>生成类型<select value={mode} disabled={busy} onChange={(event) => { setMode(event.target.value); submissionId.current = null; setShowReferences(true); }}>{MODES.map((item) => <option value={item.id} key={item.id}>{item.label}</option>)}</select></label>
            <button className="ig-send" type="submit" title={submitHint} disabled={!ready || !configured || busy || missingProduct || totalReferences > 5}>{submitting ? '正在提交…' : pendingIds ? '正在创作…' : '生成 4 张'} <span aria-hidden="true">↑</span></button>
          </div>
        </div>
      </form>
      <p className="ig-footer-note">图片保存在运行后端的电脑上。本浏览器可查看历史；重要作品也可以下载留存。</p>
    </div>
    {preview && <dialog className="ig-lightbox" ref={dialogRef} onCancel={() => setPreview(null)} onClick={(event) => { if (event.target === event.currentTarget) setPreview(null); }}>
      <div className="ig-lightbox-toolbar"><span>{preview.label}</span><a href={fullUrl(`${preview.url}?download=true`)} download={preview.name}>↓ 保存原图</a><button type="button" aria-label="关闭大图" onClick={() => setPreview(null)}>×</button></div>
      <img src={fullUrl(preview.url)} alt={preview.label} />
    </dialog>}
  </div>;
}
