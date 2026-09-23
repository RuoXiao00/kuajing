import { Link } from 'react-router-dom';
import { useEffect, useState } from 'react';
import { AUTO_CONNECT, probeBackend } from '../runtime.js';
import './demo.css';

export default function DemoBanner() {
  const [ready, setReady] = useState(false);
  useEffect(() => {
    if (!AUTO_CONNECT) return undefined;
    let disposed = false;
    let checking = false;
    let recovered = false;
    let interacted = false;
    const markInteraction = () => { interacted = true; };
    const check = async () => {
      if (checking || document.hidden || recovered) return;
      checking = true;
      const available = await probeBackend();
      checking = false;
      if (!disposed && available) {
        recovered = true;
        setReady(true);
        // 无操作时自动恢复；正在输入的访客不被打断，下一次切页再切换。
        if (!interacted) window.location.reload();
      }
    };
    const onNavigate = () => { if (recovered) window.location.reload(); };
    const onVisible = () => { if (!document.hidden) void check(); };
    const timer = setInterval(check, 60000);
    document.addEventListener('pointerdown', markInteraction);
    document.addEventListener('keydown', markInteraction);
    document.addEventListener('visibilitychange', onVisible);
    window.addEventListener('hashchange', onNavigate);
    return () => {
      disposed = true;
      clearInterval(timer);
      document.removeEventListener('pointerdown', markInteraction);
      document.removeEventListener('keydown', markInteraction);
      document.removeEventListener('visibilitychange', onVisible);
      window.removeEventListener('hashchange', onNavigate);
    };
  }, []);
  return <aside className="demo-banner" aria-label="展示版说明">
    <div><span className="demo-badge">交互展示</span><span>{AUTO_CONNECT ? '服务暂未连通，展示内置样例 · ' : ''}预置回答与插画，不调用真实 AI</span></div>
    {ready && <button type="button" onClick={() => window.location.reload()}>真实服务已恢复 · 立即连接</button>}
    <a href="https://github.com/RuoXiao00/kuajing#readme" target="_blank" rel="noreferrer">项目源码与说明 ↗</a>
  </aside>;
}
export function DemoAdmin() {
  return <main className="demo-admin"><span className="demo-badge">展示版</span><h1>知识库管理在本地完整版中使用</h1>
    <p>管理员登录、文档上传和入库需要 FastAPI 后端。公开展示版不收集账号密码，也不上传文件。</p>
    <Link to="/zhishiku">体验知识库问答 →</Link><a href="https://github.com/RuoXiao00/kuajing#本地运行完整版">查看启动说明 ↗</a></main>;
}

// github.io 与业务域名不属于同一站点，Strict Cookie 不会随请求发送。
// 提前说明并阻止收费生图，避免创建任务后因身份丢失而无法读取结果。
export function CookieOriginNotice() {
  return <main className="demo-admin"><h1>请从项目域名使用此功能</h1>
    <p>真实后端已连接。图片历史和管理登录使用 Cookie，请从同一主域名下的前端访问。</p>
    <a href="https://app.qiyuange.online">打开 app.qiyuange.online →</a>
    <p>产品浏览和知识问答仍可在当前页面使用；如果项目域名尚未启用，可先体验其他功能。</p>
    <Link to="/tuijian">返回产品推荐</Link></main>;
}
