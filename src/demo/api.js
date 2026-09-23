import { answerFor, DEMO_DATE, imageJob, productPage, recommendations } from './fixtures.js';

const json = (data, status = 200) => new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } });
const abortError = () => new DOMException('演示已停止', 'AbortError');

// 用真正的 ReadableStream 播放预置事件，让原来的 SSE 解析、停止按钮和帧合并都能被体验。
// abort/cancel 都清理计时器，切换会话时不会留下仍然向旧会话写字的任务。
export function sampleStream(question, signal, interval = 35) {
  const { answer, sources } = answerFor(question);
  const frames = [['status', { message: '正在播放预置回答…' }], ['sources', { sources }],
    ...(answer.match(/[\s\S]{1,9}/g) || []).map(content => ['token', { content }]),
    ['done', { answer, rerank_used: false }]];
  let timer;
  let onAbort;
  const cleanup = () => { clearTimeout(timer); signal?.removeEventListener('abort', onAbort); };
  const body = new ReadableStream({
    start(controller) {
      let index = 0;
      onAbort = () => { cleanup(); controller.error(abortError()); };
      if (signal?.aborted) { onAbort(); return; }
      signal?.addEventListener('abort', onAbort, { once: true });
      const send = () => {
        const [event, data] = frames[index++];
        controller.enqueue(new TextEncoder().encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`));
        if (index === frames.length) { cleanup(); controller.close(); }
        else timer = setTimeout(send, interval);
      };
      timer = setTimeout(send, interval);
    },
    cancel: cleanup,
  });
  return new Response(body, { headers: { 'Content-Type': 'text/event-stream' } });
}

// 工厂便于用隔离内存测试。示例创作只活在当前标签页内存，刷新恢复默认样例。
// 不保存或上传用户文件；未知路由直接报错，不能悄悄访问真实后台。
export function createDemoApi() {
  const jobs = [imageJob()];
  return async (input, options = {}) => {
    if (options.signal?.aborted) throw abortError();
    const url = new URL(String(input), 'https://demo.invalid');
    const method = (options.method || 'GET').toUpperCase();
    if (url.hostname === 'api.frankfurter.dev') return json(['USD', 'JPY', 'GBP', 'SGD'].map((quote, i) => ({
      base: 'CNY', quote, rate: [0.14, 20, 0.11, 0.19][i], date: DEMO_DATE.slice(0, 10),
    })));
    if (method === 'GET' && url.pathname === '/api/recommendations/latest') return json(recommendations);
    if (method === 'GET' && url.pathname === '/api/remen/products') return json(productPage(url));
    if (method === 'GET' && url.pathname === '/api/remen/products/snapshot') return json({ snapshot: null });
    if (method === 'GET' && url.pathname === '/api/knowledge/health') return json({ status: 'demo', document_count: 4, chunk_count: 4 });
    if (method === 'POST' && url.pathname === '/api/knowledge/chat/stream') {
      return sampleStream(JSON.parse(options.body).question || '', options.signal);
    }
    if (method === 'GET' && url.pathname === '/api/images/history') return json({ jobs, before: null, configured: true });
    if (method === 'POST' && url.pathname === '/api/images/jobs') {
      const id = options.body.get('request_id');
      const found = jobs.find(job => job.id === id);
      if (found) return json(found);
      const job = { ...imageJob(id, String(options.body.get('prompt') || '预览四张场景示意图'), options.body.get('mode')),
        created_at: new Date().toISOString() };
      jobs.push(job);
      if (jobs.length > 12) jobs.shift();
      return json(job);
    }
    return json({ detail: '展示版不提供此接口。请在本地运行完整版。' }, 404);
  };
}
export const demoRequest = createDemoApi();
