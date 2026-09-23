/**
 * 知识库会话的本地存储边界。
 *
 * 浏览器 localStorage 容量通常只有数 MiB，并且在隐私模式、企业策略或用户
 * 禁止站点存储时可能直接抛异常。本模块把“不可信的旧数据”和“可能失败的
 * 写入”都隔离起来，React 组件只接收结构稳定的数据，存储失败也不会卸载页面。
 */
export const KNOWLEDGE_STORAGE_KEY = 'kuajing-knowledge-conversations-v2';
export const MAX_CONVERSATIONS = 20;
export const MAX_PERSISTED_MESSAGES = 60; // 30 轮问答 = 60 条 user/assistant 消息。
const MAX_SERIALIZED_CHARACTERS = 3_800_000;

// 这些函数不依赖 React，是纯存储边界。把读写和数据清洗从组件中拆出，
// 可以用 Node 直接测试，也避免每个页面重复处理损坏 JSON。
export function uid() {
  // 优先使用浏览器标准 UUID；后面的组合只兼容缺少 randomUUID 的旧环境。
  return globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`;
}

export function newConversation() {
  const now = new Date().toISOString();
  return { id: uid(), title: '新会话', createdAt: now, updatedAt: now, messages: [] };
}

function safeText(value, fallback = '', maxLength = 200_000) {
  return typeof value === 'string' ? value.slice(0, maxLength) : fallback;
}

function sanitizeSource(source, index) {
  if (!source || typeof source !== 'object') return null;
  return {
    id: typeof source.id === 'number' || typeof source.id === 'string' ? source.id : index + 1,
    source: safeText(source.source, '未知文件', 300),
    title: safeText(source.title, '未命名资料', 300),
    category: safeText(source.category, '未分类', 100),
    published_at: safeText(source.published_at, '', 80),
    excerpt: safeText(source.excerpt, '', 1_000),
  };
}

function sanitizeMessage(message) {
  // localStorage 可能来自旧版本或被手工修改，读取时要视为不可信输入。
  // 返回 null 表示消息无效，调用方随后用 filter(Boolean) 移除。
  if (!message || typeof message !== 'object') return null;
  if (message.role !== 'user' && message.role !== 'assistant') return null;

  const content = safeText(message.content);
  const error = safeText(message.error, '', 1_000);
  const stopped = Boolean(message.stopped);
  // 刷新页面时，原 SSE 连接已经不存在。空占位和仍在生成的半截答案都标成已停止，
  // 避免假装旧请求还活着，或把未闭合的 Markdown 当成完整答案渲染。
  // 清洗只生成保存/读取用的副本，不会停止内存中真正运行的 SSE。
  const interrupted = message.role === 'assistant'
    && (Boolean(message.streaming) || (!content && !error && !stopped));
  return {
    id: safeText(message.id, uid(), 100),
    role: message.role,
    content,
    sources: Array.isArray(message.sources)
      ? message.sources.map(sanitizeSource).filter(Boolean).slice(0, 10)
      : [],
    status: '',
    error,
    stopped: stopped || interrupted,
    streaming: false,
    retryQuestion: safeText(message.retryQuestion, '', 2_000),
    rerankUsed: Boolean(message.rerankUsed),
  };
}

export function sanitizeConversation(value) {
  if (!value || typeof value !== 'object') return null;
  const messages = Array.isArray(value.messages)
    ? value.messages.map(sanitizeMessage).filter(Boolean).slice(-MAX_PERSISTED_MESSAGES)
    : [];
  const fallbackTitle = messages.find((message) => message.role === 'user')?.content || '新会话';
  const now = new Date().toISOString();
  return {
    id: safeText(value.id, uid(), 100),
    title: safeText(value.title, fallbackTitle.slice(0, 24), 80) || '新会话',
    createdAt: safeText(value.createdAt, now, 80),
    updatedAt: safeText(value.updatedAt, now, 80),
    messages,
  };
}

export function loadConversations(storage) {
  // 不传 storage 时使用浏览器存储；测试可传只实现 getItem 的 Fake。
  // 不能写在默认参数里：某些浏览器连“拿到 localStorage 对象”都会抛权限错误，
  // 默认参数在进入函数体前执行，那时下面的 try 还没开始保护它。
  try {
    const target = storage === undefined ? globalThis.localStorage : storage;
    const saved = JSON.parse(target?.getItem(KNOWLEDGE_STORAGE_KEY) || '[]');
    if (Array.isArray(saved)) {
      const sanitized = saved
        .map(sanitizeConversation)
        .filter(Boolean)
        .slice(0, MAX_CONVERSATIONS);
      if (sanitized.length) return sanitized;
    }
  } catch {
    // JSON 损坏、读取被禁用都回退到新会话，不让存储问题变成白屏。
  }
  return [newConversation()];
}

function shrinkSnapshot(snapshot) {
  // 只裁剪准备写入的副本，不修改 React 内存中的当前聊天。
  // 优先丢最旧会话，再从唯一会话头部按一轮两条消息裁剪。
  if (snapshot.length > 1) {
    snapshot.pop();
    return true;
  }
  if (snapshot[0]?.messages.length > 2) {
    snapshot[0] = { ...snapshot[0], messages: snapshot[0].messages.slice(2) };
    return true;
  }
  return false;
}

/**
 * 尝试保存最近会话。返回提示文字而不是抛异常，让界面可以继续聊天。
 * 当前会话排在第一位；遇到配额不足时先移除最旧会话，再裁剪当前会话最早轮次。
 */
export function persistConversations(storage, conversations, activeId) {
  const safe = conversations
    .map(sanitizeConversation)
    .filter(Boolean)
    .slice(0, MAX_CONVERSATIONS);
  const active = safe.find((conversation) => conversation.id === activeId);
  const snapshot = active
    ? [active, ...safe.filter((conversation) => conversation.id !== activeId)]
    : safe;
  let trimmed = false;

  while (snapshot.length) {
    // 每次缩小一点后重试，兼顾预估大小和浏览器真实配额异常；
    // 最终失败也只返回 warning，不向 React 抛异常。
    const serialized = JSON.stringify(snapshot);
    if (serialized.length > MAX_SERIALIZED_CHARACTERS) {
      if (!shrinkSnapshot(snapshot)) break;
      trimmed = true;
      continue;
    }
    try {
      // undefined 表示使用浏览器；显式传入 Fake 则仍走同一套保存逻辑。
      // 属性读取和 setItem 必须都放在 try 内，不能先在调用方取对象再传进来。
      const target = storage === undefined ? globalThis.localStorage : storage;
      // 存储不存在也是失败，不能用 ?. 跳过写入却返回 ok:true。
      if (!target) throw new Error('浏览器存储不可用');
      target.setItem(KNOWLEDGE_STORAGE_KEY, serialized);
      return {
        ok: true,
        warning: trimmed ? '浏览器存储空间有限，较早会话未保存；当前聊天仍可继续。' : '',
      };
    } catch {
      if (!shrinkSnapshot(snapshot)) break;
      trimmed = true;
    }
  }

  return {
    ok: false,
    warning: '浏览器暂时无法保存会话；当前聊天仍可继续，刷新后部分记录可能丢失。',
  };
}
