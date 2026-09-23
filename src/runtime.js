// 在页面模块加载前确定数据源，切换时重新加载，避免真实记录和演示缓存混合。
export const CONNECTION_MODE = import.meta.env?.VITE_CONNECTION_MODE || 'live';
export const AUTO_CONNECT = CONNECTION_MODE === 'auto';
export const BACKEND_URL = (import.meta.env?.VITE_API_BASE_URL || '').replace(/\/$/, '');
export let IS_DEMO = import.meta.env?.VITE_DEMO_MODE === 'true' || AUTO_CONNECT;
export const BASE_URL = import.meta.env?.BASE_URL || '/';
export const storageKey = key => IS_DEMO ? `demo:${key}` : key;

// 只读健康检查同时验证 TLS、网络和 CORS；不调用模型或启动商品抓取。
export async function probeBackend(fetcher = globalThis.fetch, base = BACKEND_URL, timeout = 2500) {
  if (!base) return false;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  try {
    const response = await fetcher(`${base}/api/knowledge/health`, {
      signal: controller.signal, cache: 'no-store', credentials: 'include',
    });
    if (!response.ok) return false;
    const body = await response.json();
    return ['ok', 'degraded'].includes(body.status) && Number.isFinite(body.document_count);
  } catch { return false; }
  finally { clearTimeout(timer); }
}
export async function initializeRuntime() {
  if (AUTO_CONNECT) IS_DEMO = !(await probeBackend());
}
