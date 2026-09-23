import test from 'node:test';
import assert from 'node:assert/strict';
import { createDemoApi, sampleStream } from './api.js';
import { products, recommendations } from './fixtures.js';
import { probeBackend } from '../runtime.js';

test('样例分页不重复，结束明确，筛选与价格有效', async () => {
  const api = createDemoApi();
  const found = [];
  let page = 1;
  while (page) {
    const data = await (await api(`/api/remen/products?page=${page}`)).json();
    found.push(...data.products);
    page = data.next_page;
    assert.ok(found.length <= 96);
  }
  assert.equal(found.length, products.length);
  assert.equal(new Set(found.map(p => p.asin)).size, found.length);
  assert.ok(found.every(p => p.price > 0 && p.currency));
  const niche = await (await api('/api/remen/products?category=niche&subCategory=jiaju')).json();
  assert.ok(niche.products.length > 0);
  assert.ok(niche.products.every(p => p.group === 'jiaju' && p.review_count <= 100));
  assert.ok(recommendations.categories.every(c => c.products.length === 5 && c.answer));
});

test('图片预览四张、请求幂等、未知接口拒绝，不请求网络', async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = () => { throw Error('展示适配器不能联网'); };
  try {
    const api = createDemoApi();
    const form = new FormData();
    form.set('request_id', 'test-job');
    form.set('prompt', '不会发送');
    form.set('product_img1', new Blob(['private']), 'private.png');
    const first = await (await api('/api/images/jobs', { method: 'POST', body: form })).json();
    const second = await (await api('/api/images/jobs', { method: 'POST', body: form })).json();
    assert.equal(first.images.length, 4);
    assert.deepEqual(first, second);
    assert.deepEqual(first.references, []);
    assert.equal((await (await api('/api/images/history')).json()).jobs.length, 2);
    assert.equal((await api('/api/admin/login', { method: 'POST' })).status, 404);
  } finally { globalThis.fetch = originalFetch; }
});

test('SSE 输出引用、token 和完成事件；取消后终止读取', async () => {
  const text = await sampleStream('FBA', undefined, 0).text();
  assert.match(text, /event: sources/);
  assert.match(text, /event: token/);
  assert.match(text, /event: done/);
  assert.match(text, /预置演示回答/);
  const controller = new AbortController();
  const reader = sampleStream('FBA', controller.signal, 1).body.getReader();
  await reader.read();
  controller.abort();
  await assert.rejects(reader.read(), { name: 'AbortError' });
});

test('连接检测确认协议和健康正文，拒绝错误页、故障、超时', async () => {
  const base = 'https://api.example.test';
  let requested;
  assert.equal(await probeBackend(async (url, options) => {
    requested = { url, options };
    return Response.json({ status: 'ok', document_count: 0 });
  }, base), true);
  assert.equal(requested.url, `${base}/api/knowledge/health`);
  assert.equal(requested.options.credentials, 'include');
  for (const response of [new Response('ICP blocked', { status: 403 }), new Response('<html/>'), Response.json({ status: 'demo' })]) {
    assert.equal(await probeBackend(async () => response, base), false);
  }
  assert.equal(await probeBackend(async () => { throw TypeError('CORS'); }, base), false);
  assert.equal(await probeBackend((_url, { signal }) => new Promise((_resolve, reject) => {
    signal.addEventListener('abort', () => reject(new DOMException('timeout', 'AbortError')));
  }), base, 5), false);
});
