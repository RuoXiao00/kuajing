import assert from 'node:assert/strict';
import test from 'node:test';
import {
  KNOWLEDGE_STORAGE_KEY,
  loadConversations,
  persistConversations,
} from './knowledgeConversationStore.js';

// node:test 会执行每个 test 块；正常 Vite 页面不会加载本文件。
// storage 都是手写 Fake，只实现当前场景需要的方法，不会读写浏览器数据。
// 每条用例依次准备输入、调用函数、用 assert 验证可观察结果。

test('损坏的本地数据会被清洗而不是导致页面初始化失败', () => {
  const storage = {
    getItem: () => JSON.stringify([
      null,
      { id: 'ok', title: 123, messages: [{ role: 'bad' }, { role: 'user', content: '问题' }] },
    ]),
  };
  const result = loadConversations(storage);
  assert.equal(result.length, 1);
  assert.equal(result[0].id, 'ok');
  assert.equal(result[0].messages.length, 1);
  assert.equal(result[0].messages[0].content, '问题');
});

test('持久化最多保留每个会话最近三十轮', () => {
  let saved = '';
  const storage = { setItem: (key, value) => { assert.equal(key, KNOWLEDGE_STORAGE_KEY); saved = value; } };
  const messages = Array.from({ length: 80 }, (_, index) => ({
    id: String(index),
    role: index % 2 ? 'assistant' : 'user',
    content: `消息 ${index}`,
  }));
  const result = persistConversations(storage, [{ id: 'active', title: '测试', messages }], 'active');
  assert.equal(result.ok, true);
  assert.equal(JSON.parse(saved)[0].messages.length, 60);
});

test('localStorage 配额错误只返回提示，不向 React 抛出异常', () => {
  // 主动让 setItem 抛错，验证异常被转换成非阻断 warning。
  const storage = { setItem: () => { throw new DOMException('quota', 'QuotaExceededError'); } };
  const result = persistConversations(
    storage,
    [{ id: 'active', title: '测试', messages: [{ id: '1', role: 'user', content: '问题' }] }],
    'active',
  );
  assert.equal(result.ok, false);
  assert.match(result.warning, /仍可继续/);
});

test('连读取 localStorage 属性都被禁止时，仍能加载临时会话并显示保存警告', (t) => {
  // 普通 Fake.setItem 抛错覆盖不到“取对象就失败”的场景。用 getter 模拟浏览器权限，
  // 并在测试结束恢复描述符，避免影响其他测试或 Node 自带的 localStorage 实现。
  const original = Object.getOwnPropertyDescriptor(globalThis, 'localStorage');
  t.after(() => {
    if (original) Object.defineProperty(globalThis, 'localStorage', original);
    else delete globalThis.localStorage;
  });
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    get() { throw new DOMException('denied', 'SecurityError'); },
  });
  const conversations = loadConversations();
  assert.equal(conversations.length, 1);
  const result = persistConversations(undefined, conversations, conversations[0].id);
  assert.equal(result.ok, false);
  assert.match(result.warning, /仍可继续/);
});

test('没有存储对象不能谎报保存成功', () => {
  const result = persistConversations(null, [{ id: 'test', messages: [] }], 'test');
  assert.equal(result.ok, false);
});

test('刷新恢复半截流式答案时保留文字并标记已停止，不修改原内存消息', () => {
  let saved;
  const storage = { setItem: (_, value) => { saved = value; }, getItem: () => saved };
  const message = { id: 'a', role: 'assistant', content: '```python\nprint(', streaming: true };
  persistConversations(storage, [{ id: 'test', messages: [message] }], 'test');
  const restored = loadConversations(storage)[0].messages[0];
  assert.equal(restored.content, message.content);
  assert.equal(restored.stopped, true);
  assert.equal(restored.streaming, false);
  assert.equal(message.streaming, true);
  assert.equal(message.stopped, undefined);
});
