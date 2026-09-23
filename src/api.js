import { IS_DEMO } from './runtime.js';

// 保留 Response / SSE 协议，让展示版复用真正的页面交互，而不是复制一套截图页面。
// 演示适配器拒绝未知接口，绝不回退到云端；正常模式仍直接使用浏览器 fetch。
export async function request(input, options) {
  if (IS_DEMO) {
    const { demoRequest } = await import('./demo/api.js');
    return demoRequest(input, options);
  }
  return globalThis.fetch(input, options);
}
