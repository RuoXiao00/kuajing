// 页面只访问本项目后端，Coze 令牌和临时图片地址不会写进前端。
export const API_BASE = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '');
export const MODES = [
  { id: 'product', label: '产品图', roles: ['product'] },
  { id: 'model', label: '产品 + 模特', roles: ['product', 'model'] },
  { id: 'background', label: '产品 + 背景', roles: ['product', 'background'] },
  { id: 'views', label: '产品多视图', roles: ['product'] },
  { id: 'model_views', label: '产品 + 模特 · 多视图', roles: ['product', 'model'] },
  { id: 'background_views', label: '产品 + 背景 · 多视图', roles: ['product', 'background'] },
  { id: 'all_views', label: '产品 + 模特 + 背景 · 多视图', roles: ['product', 'model', 'background'] },
];
export const ROLES = { product: '产品图', model: '模特图', background: '背景图' };
export const ACTIVE = new Set(['queued', 'uploading', 'generating', 'saving']);
export const STATUS = { queued: '等待生成', uploading: '正在上传参考图', generating: '正在为你创作', saving: '正在保存原图', completed: '已完成', partial: '部分结果', failed: '生成未完成', interrupted: '任务已中断' };

export async function imageRequest(path, options = {}) {
  let response;
  try { response = await fetch(`${API_BASE}/api/images${path}`, { credentials: 'include', ...options }); }
  catch (error) {
    if (error.name === 'AbortError') throw error;
    throw new Error('暂时连接不上图片服务，请确认后端正在运行。');
  }
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : '请求未完成，请稍后重试。');
  return body;
}
