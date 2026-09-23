import { request as fetch } from '../../api.js';
import { IS_DEMO } from '../../runtime.js';
import { useCallback, useEffect, useRef, useState } from 'react';
import './AdminDashboard.css';

const API_BASE_URL = IS_DEMO ? '' : (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '');

// 管理页的知识库链路分成三层：AdminDashboard 校验会话，AdminLogin 登录，
// KnowledgeManager 读取统计并维护上传队列。静态商品总览与入库流程无关。
const summaryCards = [
  { label: '平台商品总数', value: '12,846', change: '+12.8%', detail: '较上月' },
  { label: '本月新增商品', value: '1,284', change: '+8.4%', detail: '较上月' },
  { label: '内容浏览量', value: '286.5k', change: '+18.6%', detail: '较上月' },
  { label: '活跃用户', value: '8,492', change: '+5.2%', detail: '较上月' },
];

const trendData = [
  { month: '1月', value: 42 }, { month: '2月', value: 58 },
  { month: '3月', value: 48 }, { month: '4月', value: 76 },
  { month: '5月', value: 66 }, { month: '6月', value: 92 },
  { month: '7月', value: 84 }, { month: '8月', value: 100 },
];

const products = [
  { name: '便携式榨汁杯', category: '厨房用品', platform: 'TikTok Shop', views: '28,420', status: '已上架' },
  { name: '磁吸无线充电支架', category: '数码配件', platform: 'Amazon', views: '21,680', status: '已上架' },
  { name: '户外折叠露营灯', category: '户外运动', platform: 'Temu', views: '18,920', status: '审核中' },
  { name: '宠物智能饮水机', category: '宠物用品', platform: 'SHEIN', views: '15,306', status: '已上架' },
  { name: '多功能收纳盒', category: '家居日用', platform: 'AliExpress', views: '12,744', status: '已下架' },
];

async function readApiError(response) {
  // 管理接口既可能返回 FastAPI detail，也可能返回上传业务的 message；这里
  // 统一成一段文字，避免每个按钮重复判断响应结构。
  try {
    const body = await response.json();
    return typeof body.detail === 'string'
      ? body.detail
      : body.message || body.detail?.message || '请求失败';
  } catch {
    return '请求失败（HTTP ' + response.status + '）';
  }
}

export default function AdminDashboard() {
  // 初次渲染先显示 loading；Effect 随后请求后端验证 HttpOnly Cookie。
  // 前端不保存“已登录就永远有效”的布尔值，刷新时以后端签名校验为准。
  const [session, setSession] = useState({ loading: true, authenticated: false, error: '' });

  // 页面刷新后不能相信 sessionStorage，而要让后端校验签名 Cookie 是否仍有效。
  useEffect(() => {
    fetch(API_BASE_URL + '/api/admin/session', { credentials: 'include' })
      .then(async (response) => {
        if (!response.ok) throw new Error(await readApiError(response));
        return response.json();
      })
      .then((data) => setSession({ loading: false, authenticated: true, username: data.username, error: '' }))
      .catch((error) => setSession({ loading: false, authenticated: false, error: error.message }));
  }, []);

  if (session.loading) {
    return <main className="admin-loading"><span />正在验证管理员会话…</main>;
  }

  if (!session.authenticated) {
    return <AdminLogin initialError={session.error} onSuccess={(username) => (
      setSession({ loading: false, authenticated: true, username, error: '' })
    )} />;
  }

  async function logout() {
    try {
      await fetch(API_BASE_URL + '/api/admin/logout', {
        method: 'POST',
        credentials: 'include',
      });
    } finally {
      setSession({ loading: false, authenticated: false, error: '' });
    }
  }

  return <AdminConsole username={session.username} onLogout={logout} onUnauthorized={() => (
    setSession({ loading: false, authenticated: false, error: '登录已过期，请重新登录' })
  )} />;
}

function AdminLogin({ initialError, onSuccess }) {
  // account/password 只存在组件内存；提交后由后端 bcrypt 校验。
  // onSuccess 是父组件传入的回调，用于把页面从登录表单切换到控制台。
  const [account, setAccount] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState(initialError === '请先登录管理员账号' ? '' : initialError);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event) {
    event.preventDefault();
    setSubmitting(true);
    setError('');
    try {
      // 接口接收 JSON；登录成功后 Set-Cookie 写入 HttpOnly 会话。前端不会接触
      // token，也不再保存 admin/admin123 这类可从源码查看的凭据。
      // credentials: 'include' 是让浏览器按 Cookie 规则携带/接收会话凭据，
      // 不是把密码每次都发一遍。HttpOnly 的意思是页面 JS 不能读取该 Cookie，
      // 不代表浏览器不能带它请求接口；后端仍要验证签名，不能只相信“页面显示已登录”。
      const response = await fetch(API_BASE_URL + '/api/admin/login', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: account, password }),
      });
      if (!response.ok) throw new Error(await readApiError(response));
      const data = await response.json();
      onSuccess(data.username);
    } catch (requestError) {
      setError(requestError.message || '登录失败，请稍后重试');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="admin-login-page">
      <div className="login-accent" />
      <section className="login-card">
        <div className="login-brand"><span>跨境阁</span><small>ADMIN CONSOLE</small></div>
        <p className="admin-eyebrow">SECURE ACCESS / 01</p>
        <h1>管理员登录</h1>
        <p className="login-copy">登录后台，维护跨境电商知识库与查看平台数据。</p>
        <form onSubmit={handleSubmit}>
          <label>管理员账号<input value={account} onChange={(event) => setAccount(event.target.value)} autoComplete="username" placeholder="请输入管理员账号" /></label>
          <label>登录密码<input value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" type="password" placeholder="请输入登录密码" /></label>
          {error && <p className="login-error">{error}</p>}
          <button className="login-button" disabled={submitting} type="submit">
            {submitting ? '正在验证…' : '进入管理后台'} <span>→</span>
          </button>
        </form>
        <p className="login-footnote">会话有效 8 小时 · 此区域仅限授权管理员</p>
      </section>
    </main>
  );
}

function AdminConsole({ username, onLogout, onUnauthorized }) {
  // “数据总览”和“知识库管理”共享同一后端 Cookie 会话；切换标签不会
  // 重新登录，也不会把任何凭据保存在浏览器可读存储中。
  const [tab, setTab] = useState('overview');
  return (
    <main className="admin-page">
      <header className="admin-hero">
        <div>
          <p className="admin-eyebrow">OPERATIONS CENTER / 2026</p>
          <h1>{tab === 'overview' ? '数据总览' : '知识库管理'}</h1>
          <p className="admin-subtitle">
            {tab === 'overview'
              ? '掌握平台商品、用户与内容表现，做出更快的运营决策。'
              : '上传业务资料、查看入库结果，并核对 Chroma 中的真实数据统计。'}
          </p>
        </div>
        <div className="admin-actions">
          <span className="admin-user">管理员 · {username}</span>
          <button className="logout-button" onClick={onLogout} type="button">退出</button>
        </div>
      </header>
      <nav className="admin-tabs" aria-label="管理后台页面">
        <button className={tab === 'overview' ? 'active' : ''} onClick={() => setTab('overview')} type="button">数据总览</button>
        <button className={tab === 'knowledge' ? 'active' : ''} onClick={() => setTab('knowledge')} type="button">知识库管理</button>
      </nav>
      {tab === 'overview'
        ? <AdminOverview />
        : <KnowledgeManager onUnauthorized={onUnauthorized} />}
    </main>
  );
}

function AdminOverview() {
  const [range, setRange] = useState('近 8 个月');
  const [category, setCategory] = useState('全部品类');

  return (
    <div className="admin-content">
      <section className="summary-grid" aria-label="核心指标">
        {summaryCards.map((card) => (
          <article className="summary-card" key={card.label}>
            <div className="summary-card-top"><span>{card.label}</span><span className="summary-mark">↗</span></div>
            <strong>{card.value}</strong><p><b>{card.change}</b> {card.detail}</p>
          </article>
        ))}
      </section>
      <section className="analytics-grid">
        <article className="panel trend-panel">
          <div className="panel-heading">
            <div><span className="panel-kicker">PRODUCT DISCOVERY</span><h2>商品发现趋势</h2></div>
            <div className="range-tabs">{['近 8 个月', '近 30 天'].map((item) => (
              <button className={range === item ? 'selected' : ''} onClick={() => setRange(item)} type="button" key={item}>{item}</button>
            ))}</div>
          </div>
          <div className="chart-area">
            <div className="chart-y-axis"><span>100k</span><span>75k</span><span>50k</span><span>25k</span><span>0</span></div>
            <div className="bar-chart">
              {[25, 50, 75, 100].map((line) => <div className="grid-line" style={{ bottom: line + '%' }} key={line} />)}
              {trendData.map((item) => <div className="bar-column" key={item.month}><div className="bar-value" style={{ height: item.value + '%' }} title={item.month + ' ' + item.value + 'k'} /><span>{item.month}</span></div>)}
            </div>
          </div>
        </article>
        <article className="panel platform-panel">
          <div className="panel-heading"><div><span className="panel-kicker">TRAFFIC SOURCE</span><h2>平台分布</h2></div></div>
          <div className="platform-content"><div className="donut"><div><strong>286.5k</strong><span>总浏览量</span></div></div>
            <div className="platform-list"><p><i className="dot tiktok" />TikTok Shop <b>38%</b></p><p><i className="dot amazon" />Amazon <b>27%</b></p><p><i className="dot temu" />Temu <b>21%</b></p><p><i className="dot other" />其他平台 <b>14%</b></p></div>
          </div>
        </article>
      </section>
      <section className="panel table-panel">
        <div className="panel-heading table-heading"><div><span className="panel-kicker">CATALOG MONITOR</span><h2>商品表现</h2></div>
          <div className="table-filters"><select value={category} onChange={(event) => setCategory(event.target.value)}><option>全部品类</option><option>厨房用品</option><option>数码配件</option><option>户外运动</option></select></div>
        </div>
        <div className="table-wrap"><table><thead><tr><th>商品名称</th><th>品类</th><th>平台</th><th>浏览量</th><th>状态</th></tr></thead>
          <tbody>{products.map((product) => <tr key={product.name}><td className="product-name">{product.name}</td><td>{product.category}</td><td>{product.platform}</td><td>{product.views}</td><td><span className={'status ' + (product.status === '已上架' ? 'live' : product.status === '审核中' ? 'review' : 'offline')}>{product.status}</span></td></tr>)}</tbody>
        </table></div>
      </section>
    </div>
  );
}

function uploadOne(file, category, onProgress) {
  // XMLHttpRequest 提供 upload.progress；fetch 目前不能稳定报告浏览器上传进度。
  // Promise 把 XHR 的事件式 API 包装成 async/await 可用的形式：
  // 2xx 时 resolve，网络/业务失败时 reject，401 额外携带 unauthorized 标志。
  // 仿写思路：把“成功回调”接到 resolve，把“失败回调”接到 reject，上层就能
  // await uploadOne(...)，不用把后续入库结果处理一层层嵌套进 XHR 回调里。
  return new Promise((resolve, reject) => {
    const form = new FormData();
    form.append('file', file);
    form.append('category', category);
    // FormData 会把文件和分类打包成 multipart。不要手写 Content-Type，浏览器
    // 还需要生成 boundary 分隔不同字段；手写缺 boundary 时后端可能读不到 file。
    const xhr = new XMLHttpRequest();
    xhr.open('POST', API_BASE_URL + '/api/admin/knowledge/files');
    xhr.withCredentials = true;
    xhr.upload.onprogress = (event) => {
      // 这只表示“文件字节传到服务端”的进度，不是 LangGraph/Embedding 的进度。
      // 即使到 100%，后端可能还在解析、切块和向量化；要等 onload 的业务结果，
      // 才能显示 indexed 或 duplicate。千万别见 100% 就宣称“已成功入库”。
      if (event.lengthComputable) onProgress(Math.round((event.loaded / event.total) * 100));
    };
    xhr.onload = () => {
      let body = {};
      try { body = JSON.parse(xhr.responseText); } catch { body = {}; }
      if (xhr.status === 401) {
        // unauthorized 是我们附在 Error 上的标记，不是浏览器内置属性。
        // 上层据此回到登录页并停止队列，不要拿过期 Cookie 一直重试剩余文件。
        reject(Object.assign(new Error('登录已过期，请重新登录'), { unauthorized: true }));
      } else if (xhr.status >= 200 && xhr.status < 300) {
        resolve(body);
      } else {
        reject(new Error(body.message || body.detail || '上传失败（HTTP ' + xhr.status + '）'));
      }
    };
    xhr.onerror = () => reject(new Error('网络连接失败，请检查后端服务'));
    xhr.send(form);
  });
}

function KnowledgeManager({ onUnauthorized }) {
  // items 是纯前端上传队列：每个文件分别保存进度与结果。后端接口坚持
  // 一次接收一个文件，才能精确返回 indexed / duplicate / error。
  const [stats, setStats] = useState(null);
  const [statsError, setStatsError] = useState('');
  const [category, setCategory] = useState('');
  const [items, setItems] = useState([]);
  const [uploading, setUploading] = useState(false);
  const fileInput = useRef(null);

  // useCallback 保持 loadStats 的函数引用稳定，Effect 才不会因每次渲染得到
  // 新函数而反复请求。依赖 onUnauthorized 改变时才创建新版本。
  const loadStats = useCallback(async () => {
    try {
      // credentials=include 让浏览器携带 HttpOnly Cookie；前端不需要也无法读取它。
      const response = await fetch(API_BASE_URL + '/api/admin/knowledge/stats', {
        credentials: 'include',
      });
      if (response.status === 401) {
        onUnauthorized();
        return;
      }
      if (!response.ok) throw new Error(await readApiError(response));
      setStatsError('');
      setStats(await response.json());
    } catch (error) {
      setStatsError(error.message || '统计加载失败');
    }
  }, [onUnauthorized]);

  // loadStats 的状态更新发生在 fetch 完成后；这里的 Effect 只负责首次同步后端。
  // oxlint-disable-next-line react/set-state-in-effect
  useEffect(() => { loadStats(); }, [loadStats]);

  function addFiles(fileList) {
    // accept 只是文件选择器提示，拖拽仍可能带入其他格式，所以这里先给出
    // 即时错误；真正的安全校验仍由后端根据大小、扩展名和文件结构完成。
    const allowed = ['.docx', '.pdf', '.txt'];
    const additions = [...fileList].map((file) => {
      const suffix = file.name.slice(file.name.lastIndexOf('.')).toLowerCase();
      return {
        id: crypto.randomUUID ? crypto.randomUUID() : file.name + Date.now(),
        file,
        name: file.name,
        size: file.size,
        progress: 0,
        status: allowed.includes(suffix) ? 'queued' : 'error',
        message: allowed.includes(suffix) ? '等待上传' : '仅支持 DOCX、PDF、TXT',
      };
    });
    setItems((current) => [...current, ...additions]);
  }

  async function uploadAll() {
    // 顺序上传可防止多个大文件同时占满带宽或触发 Embedding 限流；每个文件
    // 失败只更新自己的状态，不会阻止队列中后续文件继续处理。
    // pending 是本轮开始时选中的待传文件快照，await 每次等一份文件的结果。
    // 对比：pending.forEach(async ...) 不会逐个等待，容易意外变成全部同时上传。
    const pending = items.filter((item) => item.status === 'queued');
    if (!pending.length || uploading) return;
    setUploading(true);
    for (const pendingItem of pending) {
      setItems((current) => current.map((item) => item.id === pendingItem.id
        ? { ...item, status: 'uploading', progress: 1, message: '正在上传和向量化…' }
        : item));
      try {
        const result = await uploadOne(pendingItem.file, category || '未分类', (progress) => {
          setItems((current) => current.map((item) => item.id === pendingItem.id
            ? { ...item, progress }
            : item));
        });
        setItems((current) => current.map((item) => item.id === pendingItem.id
          ? {
            ...item,
            progress: 100,
            status: result.status,
            message: result.message,
            chunks: result.chunk_count,
          }
          : item));
      } catch (error) {
        if (error.unauthorized) {
          onUnauthorized();
          break;
        }
        setItems((current) => current.map((item) => item.id === pendingItem.id
          ? { ...item, status: 'error', message: error.message }
          : item));
      }
    }
    setUploading(false);
    await loadStats();
  }

  function handleDrop(event) {
    // 浏览器默认会直接打开拖入文件，必须 preventDefault 后才能接管上传。
    event.preventDefault();
    addFiles(event.dataTransfer.files);
  }

  return (
    <div className="knowledge-admin admin-content">
      <section className="knowledge-stats">
        <article><span>唯一文档</span><strong>{stats?.document_count ?? '—'}</strong></article>
        <article><span>知识块</span><strong>{stats?.chunk_count ?? '—'}</strong></article>
        <article><span>分类数</span><strong>{stats?.category_count ?? '—'}</strong></article>
        <article><span>最后更新</span><strong className="date-value">{stats?.last_updated_at ? new Date(stats.last_updated_at).toLocaleString() : '暂无'}</strong></article>
      </section>
      {statsError && <p className="knowledge-alert">{statsError}</p>}
      <section className="panel upload-panel">
        <div className="upload-heading">
          <div><span className="panel-kicker">KNOWLEDGE INGESTION</span><h2>上传知识文件</h2><p>支持 DOCX、PDF、TXT，单文件最大 25 MiB；相同正文会自动跳过。</p></div>
          <button type="button" className="reload-stats" onClick={loadStats}>重新加载统计</button>
        </div>
        <label className="category-field">统一分类（可选）
          <input value={category} maxLength={80} onChange={(event) => setCategory(event.target.value)} placeholder="例如：税务要求 / 亚马逊物流" />
        </label>
        <div
          className="drop-zone"
          onClick={() => fileInput.current?.click()}
          onDragOver={(event) => event.preventDefault()}
          onDrop={handleDrop}
          onKeyDown={(event) => {
            if (event.key === 'Enter' || event.key === ' ') fileInput.current?.click();
          }}
          role="button"
          tabIndex={0}
        >
          <input ref={fileInput} type="file" accept=".docx,.pdf,.txt" multiple onChange={(event) => addFiles(event.target.files)} />
          <span className="upload-icon">↑</span>
          <strong>拖拽文件到这里，或点击选择</strong>
          <small>可以一次选择多个文件，系统会逐个显示真实上传进度</small>
        </div>
        {items.length > 0 && (
          <div className="upload-queue">
            {items.map((item) => (
              <div className="upload-item" key={item.id}>
                <div className="file-badge">{item.name.split('.').pop().toUpperCase()}</div>
                <div className="upload-file-info">
                  <strong>{item.name}</strong>
                  <span>{(item.size / 1024 / 1024).toFixed(2)} MiB · {item.message}</span>
                  <div className="upload-progress"><i style={{ width: item.progress + '%' }} /></div>
                </div>
                <span className={'upload-result ' + item.status}>
                  {item.status === 'indexed' ? '已入库 ' + item.chunks + ' 块'
                    : item.status === 'duplicate' ? '重复跳过'
                      : item.status === 'uploading' ? item.progress + '%'
                        : item.status === 'error' ? '失败' : '等待'}
                </span>
              </div>
            ))}
          </div>
        )}
        <div className="upload-actions">
          <button type="button" className="clear-files" disabled={uploading} onClick={() => setItems([])}>清空列表</button>
          <button type="button" className="start-upload" disabled={uploading || !items.length} onClick={uploadAll}>
            {uploading ? '正在处理…' : '开始上传'}
          </button>
        </div>
      </section>
    </div>
  );
}
