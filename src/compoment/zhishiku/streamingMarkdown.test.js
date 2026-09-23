import assert from 'node:assert/strict';
import test from 'node:test';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { prepareMarkdown } from './streamingMarkdown.js';
import { createTokenBuffer } from './tokenBuffer.js';

// node:test 执行纯函数 + React 服务端渲染，不请求模型，不读写用户聊天记录。
const render = (text, incomplete = true) => renderToStaticMarkup(createElement(
  ReactMarkdown, { remarkPlugins: [remarkGfm], skipHtml: true }, prepareMarkdown(text, incomplete),
));

test('生成期间就显示标题与加粗，结束后不需要切换渲染方式', () => {
  const input = '### 物流\n\n**包装要求';
  assert.match(render(input), /<h3>物流<\/h3>/);
  assert.match(render(input), /<strong>包装要求<\/strong>/);
  const complete = input + '**';
  assert.equal(render(complete), render(complete, false));
  assert.equal(prepareMarkdown(complete, false), complete);
});

test('逐字符拆包时不闪现未成形的标题/加粗标记', () => {
  const text = '### 物流\n\n这是 **重要提示**';
  for (let length = 1; length <= text.length; length++) {
    const html = render(text.slice(0, length));
    assert.ok(!html.includes('**'), `第 ${length} 个字符露出了标记：${html}`);
    assert.ok(!html.includes('###'));
  }
});

test('代码块、行内代码、转义字符与美元价格不能被误删', () => {
  assert.match(render('```js\nconst s = "**##";'), /const s = &quot;\*\*##&quot;;/);
  assert.match(render('`**##`'), /<code>\*\*##<\/code>/);
  assert.match(render('literal \\*\\*'), /literal \*\*/);
  assert.match(render('价格 $25，范围 20~25'), /价格 \$25/);
});

test('不完整链接不生成可点击地址，完整链接恢复，原始 HTML 不执行', () => {
  assert.ok(!render('[官方](https://exa').includes('<a'));
  assert.match(render('[官方](https://example.com)'), /href="https:\/\/example.com"/);
  assert.ok(!render('<script>alert(1)</script>').includes('<script'));
  assert.ok(!render('[坏链接](javascript:alert)').includes('href="javascript:'));
});

test('长表格及停止/断流的半截答案均可渲染，原文没有被改写', () => {
  const content = '| 项目 | 费用 |\n| --- | --- |\n| FBA | $10 |\n\n**未结束';
  assert.match(render(content), /<table>/);
  assert.match(render(content), /<strong>未结束<\/strong>/);
  assert.ok(content.endsWith('**未结束'));
  assert.ok(render(('正文\n\n' + content + '**\n\n').repeat(100)).length > 10000);
});

function clock() {
  let time = 0;
  let id = 0;
  const frames = new Map();
  const output = [];
  const buffer = createTokenBuffer({
    onFlush: text => output.push(text), now: () => time,
    requestFrame: callback => { frames.set(++id, callback); return id; },
    cancelFrame: frame => frames.delete(frame),
  });
  return { buffer, output, frames, advance(ms) {
    time += ms;
    const pending = [...frames.values()]; frames.clear(); pending.forEach(callback => callback());
  } };
}

test('100 个 token 每 50ms 合并，不创建多份动画帧', () => {
  const fake = clock();
  for (let i = 0; i < 100; i++) {
    fake.buffer.push('字');
    assert.equal(fake.frames.size, 1);
    fake.advance(5);
  }
  assert.equal(fake.output.length, 10);
  assert.equal(fake.output.join(''), '字'.repeat(100));
  assert.equal(fake.frames.size, 0);
});

test('完成/停止/失败立即补齐尾字，销毁后不会产生残余更新', () => {
  for (const reason of ['done', 'stop', 'error']) {
    const fake = clock();
    fake.buffer.push(reason);
    fake.buffer.flush(); fake.buffer.dispose(); fake.buffer.push('不应出现'); fake.advance(100);
    assert.deepEqual(fake.output, [reason]);
    assert.equal(fake.frames.size, 0);
  }
});
