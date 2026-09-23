import { request as fetch } from '../../api.js';
import { IS_DEMO } from '../../runtime.js';
import { useEffect, useState } from 'react';
import AnswerMarkdown from './AnswerMarkdown';
import { createTokenBuffer } from './tokenBuffer';
import { useKnowledgeConversations } from './KnowledgeConversationContext';
import { uid } from './knowledgeConversationStore';
import { useChatAutoScroll } from './useChatAutoScroll';
import './Zhishiku.css';

// 本组件只负责浏览器交互；检索、Rerank 和模型生成都在后端。
// 运行顺序：组件渲染 → 用户发送 → fetch 建立 SSE → 解析事件 → 更新 Context。
const API_BASE_URL = IS_DEMO ? '' : (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '');
const SUGGESTIONS = [
  '亚马逊 FBA 物流有哪些主要费用？',
  '欧洲站 VAT 注册和申报要注意什么？',
  '品牌备案需要准备哪些材料？',
  '新品上架后如何规划站内广告？',
];

async function responseError(response) {
  // FastAPI 的失败正文可能是字符串 detail、结构化 detail 或普通 message。
  // 在协议边界统一整理后，聊天逻辑只需要处理一条可展示的错误消息。
  try {
    const data = await response.json();
    return typeof data.detail === 'string'
      ? data.detail
      : data.message || data.detail?.message || '请求失败，请稍后重试';
  } catch {
    return '请求失败（HTTP ' + response.status + '）';
  }
}

export default function Zhishiku() {
  // 函数组件会在状态或 Context 改变时重新执行。useState 保存输入框等界面状态，
  // 滚动 DOM 由专用 Hook 保存；真正长期会话由外层 Provider 管理。
  const {
    activeConversation,
    isGenerating,
    storageWarning,
    updateConversation,
    beginGeneration,
    finishGeneration,
    stopGeneration,
  } = useKnowledgeConversations();
  const [input, setInput] = useState('');
  const [serviceStatus, setServiceStatus] = useState(null);
  const { scrollContainerRef, followLatest } = useChatAutoScroll(
    activeConversation?.id, activeConversation?.messages,
  );

  useEffect(() => {
    fetch(API_BASE_URL + '/api/knowledge/health')
      .then((response) => response.json())
      .then(setServiceStatus)
      .catch(() => setServiceStatus({ status: 'unavailable' }));
  }, []);

  useEffect(() => {
    // 用户离开知识库路由时关闭当前 SSE，后端生成器也会在 finally 中释放并发位。
    return () => stopGeneration();
  }, [stopGeneration]);

  function updateAssistant(conversationId, messageId, change) {
    // conversationId + messageId 是双重定位键：即使用户切换会话，旧请求也只会
    // 尝试更新原消息；切换动作本身还会 abort 请求，形成双重保护。
    updateConversation(conversationId, (conversation) => ({
      ...conversation,
      updatedAt: new Date().toISOString(),
      messages: conversation.messages.map((message) => (
        message.id === messageId ? { ...message, ...change } : message
      )),
    }));
  }

  function appendAssistant(conversationId, messageId, content) {
    if (!content) return;
    updateConversation(conversationId, (conversation) => ({
      ...conversation,
      updatedAt: new Date().toISOString(),
      messages: conversation.messages.map((message) => (
        message.id === messageId
          ? { ...message, content: message.content + content, status: '正在生成…', streaming: true }
          : message
      )),
    }));
  }

  async function runQuestion(question, conversationId, baseMessages) {
    // 主流程：最近 10 条历史 -> SSE -> 帧级合并 token -> 更新对应助手消息。
    // baseMessages 显式传入，失败重试不会把错误占位或重复问题提交给模型。
    if (!question.trim() || isGenerating) return;
    // 用户主动发送/重试时重新跟随新答案；仅收到 token 时不能重置这个开关，
    // 否则用户刚向上翻历史，下一块文字就又会把他拖回底部。
    followLatest();
    const cleanQuestion = question.trim();
    const userMessage = { id: uid(), role: 'user', content: cleanQuestion };
    const assistantId = uid();
    const assistantMessage = {
      id: assistantId,
      role: 'assistant',
      content: '',
      sources: [],
      status: '正在连接知识库…',
      streaming: true,
      retryQuestion: cleanQuestion,
    };
    // API 只需要 role/content，不能把 error、sources、streaming 等页面字段
    // 原样发给后端；同时最多取最近 10 条，满足 ChatRequest 的契约。
    const requestHistory = baseMessages
      .filter((message) => message.role === 'user' || (message.role === 'assistant' && message.content))
      .slice(-10)
      .map(({ role, content }) => ({ role, content }));

    updateConversation(conversationId, (conversation) => ({
      ...conversation,
      title: conversation.messages.length ? conversation.title : cleanQuestion.slice(0, 24),
      updatedAt: new Date().toISOString(),
      messages: [...baseMessages, userMessage, assistantMessage],
    }));
    setInput('');
    const controller = new AbortController();
    beginGeneration(controller);

    // Markdown 解析比纯文本更费工：50ms 合并一批，兼顾实时感与主线程负担。
    // 数据更新仍和 DOM 提交在同一轮完成，原来的 useLayoutEffect 能准确跟随底部。
    const tokens = createTokenBuffer({
      onFlush: (text) => appendAssistant(conversationId, assistantId, text),
      requestFrame: (callback) => window.requestAnimationFrame(callback),
      cancelFrame: (id) => window.cancelAnimationFrame(id),
      now: () => performance.now(),
    });
    let completed = false;

    function flushQueuedTokens() {
      // 结束信号优先于刷新节奏：不能丢掉暂存盒里的最后几个字。
      tokens.flush();
    }

    function queueToken(content) {
      tokens.push(content);
    }

    try {
      // 后端现在由 LangGraph 编排，但浏览器仍只依赖稳定的 HTTP/SSE 契约。
      // 服务端 astream_events → API SSE 编码 → consumeEvent；不要让页面理解图节点名。
      // abort 会停止本地接收并触发后端清理；不代表供应商已开始的计算立即停止计费。
      const response = await fetch(API_BASE_URL + '/api/knowledge/chat/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
        signal: controller.signal,
        body: JSON.stringify({
          conversation_id: conversationId,
          question: cleanQuestion,
          history: requestHistory,
        }),
      });
      if (!response.ok) throw new Error(await responseError(response));
      if (!response.body) throw new Error('浏览器没有收到流式响应');
      // 返回一个 `ReadableStreamDefaultReader` 读取器，用来逐块读取流中的二进制字节数据。
      const reader = response.body.getReader();
      // reader 提供网络字节块，TextDecoder 把 UTF-8 字节安全拼回字符串。
      // 一个字节块不等于一个 SSE 事件，因此下方仍必须维护 buffer。
      const decoder = new TextDecoder();
      let buffer = '';

      function consumeEvent(block) {
        // 网络分块和 SSE 事件边界并不对应：一次 read 可能只有半条事件，也可能
        // 同时包含多条，所以必须先缓冲并按空行拆分，再解析 event/data。
        // 这里收到的是后端已经转换好的 SSE，不是 LangGraph 原始的 {type, ns, data}。
        // 例如 event: token + data: {"content":"日本"}，JSON.parse 后才有 data.content。
        const lines = block.split(/\r?\n/);
        // 去掉行首的 `event:` 前缀（正好 6 个字符：`e v e n t :`）。
        // 遍历所有行，找到**第一个**以 `event:` 开头的行（SSE 规范约定一个事件只有一个 event 字段）
        const eventName = lines.find((line) => line.startsWith('event:'))?.slice(6).trim();
        const dataText = lines
          .filter((line) => line.startsWith('data:'))
          .map((line) => line.slice(5).trimStart())
          .join('\n');
        if (!eventName || !dataText) return;
        const data = JSON.parse(dataText);
        if (eventName === 'status') {
          updateAssistant(conversationId, assistantId, { status: data.message });
        } else if (eventName === 'sources') {
          updateAssistant(conversationId, assistantId, { sources: data.sources || [] });
        } else if (eventName === 'token') {
          queueToken(data.content);
        } else if (eventName === 'done') {
          // 业务 done 表示后端图已走到最终结果。先把待显示文本冲出来，再用完整
          // answer 校正页面；否则下一帧的旧 token 可能又追加到已经完整的答案末尾。
          flushQueuedTokens();
          completed = true;
          const change = {
            status: '',
            streaming: false,
            rerankUsed: Boolean(data.rerank_used),
          };
          // 后端 done 携带完整答案，可校正网络分块遗漏；若未来协议不带 answer，
          // 则保留已经逐块拼接的内容，不能用 undefined 覆盖它。
          if (typeof data.answer === 'string' && data.answer) change.content = data.answer;
          updateAssistant(conversationId, assistantId, change);
        } else if (eventName === 'error') {
          flushQueuedTokens();
          throw new Error(data.message || '知识库生成失败');
        }
      }

      while (true) {
        // 这个 done 是 ReadableStream 的“网络已经读完”，与上面的 SSE done 不是一回事。
        // 网络可能因为代理断开而结束；只有收到业务 done，completed 才会变成 true。
        const { done, value } = await reader.read();
        // 中文字符可能被拆到两次 read 里。stream:true 让 TextDecoder 保留未凑齐的
        // 字节，等下一包再拼；这解决的是“字符拆开”，buffer 解决的是“事件拆开”。
        buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
        const blocks = buffer.split(/\r?\n\r?\n/);
        buffer = blocks.pop() || '';
        // 末段可能只有半条 data，先留在 buffer，不急着 JSON.parse；下次接着拼。
        // 如果收到的文本刚好以空行结束，末段为空字符串，保留下来也没有问题。
        for (const block of blocks) consumeEvent(block);
        if (done) {
          if (buffer.trim()) consumeEvent(buffer);
          break;
        }
      }
      if (!completed) throw new Error('流式连接提前结束，请重新生成');
    } catch (error) {
      flushQueuedTokens();
      if (error.name === 'AbortError') {
        updateAssistant(conversationId, assistantId, {
          status: '',
          streaming: false,
          stopped: true,
        });
      } else {
        updateAssistant(conversationId, assistantId, {
          status: '',
          streaming: false,
          error: error.message || '知识库服务暂时不可用',
        });
      }
    } finally {
      flushQueuedTokens();
      tokens.dispose();
      finishGeneration(controller);
    }
  }

  function send(question = input) {
    // 默认参数让输入框发送与建议问题按钮共用一个入口。
    if (!activeConversation) return;
    runQuestion(question, activeConversation.id, activeConversation.messages);
  }

  function retry(message) {
    // 去掉“原用户问题 + 失败助手占位”，重新加入问题，避免历史出现重复提问。
    if (!activeConversation || isGenerating) return;
    const failedIndex = activeConversation.messages.findIndex((item) => item.id === message.id);
    const baseMessages = activeConversation.messages.slice(0, Math.max(0, failedIndex - 1));
    runQuestion(message.retryQuestion, activeConversation.id, baseMessages);
  }

  function handleKeyDown(event) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      send();
    }
  }

  const healthLabel = IS_DEMO ? '离线展示 · 预置回答' : serviceStatus?.status === 'ok'
    ? '知识库在线'
    : serviceStatus?.status === 'degraded'
      ? '知识库在线 · 精排降级'
      : '正在检查服务';

  return (
    <main className="knowledge-page">
      <section className="chat-workspace">
        <header className="chat-header">
          <div>
            <h1>亚马逊跨境电商知识助手</h1>
            <p><i className={serviceStatus?.status === 'unavailable' ? 'offline' : ''} />{healthLabel}</p>
            {storageWarning && <p className="storage-warning" role="status">{storageWarning}</p>}
          </div>
          <span className="chat-mode">{IS_DEMO ? '预置问答演示' : '知识库限定回答'}</span>
        </header>

        <div className="message-scroll" ref={scrollContainerRef} tabIndex={0} role="region" aria-label="聊天消息">
          {!activeConversation?.messages.length ? (
            <section className="welcome-panel">
              <div className="welcome-symbol">跨</div>
              <p className="welcome-kicker">KNOWLEDGE, GROUNDED</p>
              <h2>从亚马逊资料中，找到可追溯的答案</h2>
              <p className="welcome-copy">
                {IS_DEMO ? '点击下方问题，体验流式文字、停止生成和资料引用。回答为人工预置内容，不进行真实检索或模型推理。'
                  : '我会先检索知识库、精排相关资料，再生成带 [资料 n] 引用的回答。政策与税务信息仍建议核对发布日期和官方最新规则。'}
              </p>
              <div className="suggestion-grid">
                {SUGGESTIONS.map((question) => (
                  <button type="button" key={question} onClick={() => send(question)}>
                    <span>↗</span>{question}
                  </button>
                ))}
              </div>
            </section>
          ) : (
            <div className="messages">
              {activeConversation.messages.map((message) => (
                <article className={'message-row ' + message.role} key={message.id}>
                  <div className="message-avatar">{message.role === 'user' ? '你' : 'K'}</div>
                  <div className="message-body">
                    <div className="message-author">
                      {message.role === 'user' ? '你' : '跨境知识助手'}
                      {message.rerankUsed && <span>Rerank</span>}
                    </div>
                    {message.content ? (
                      message.role === 'user' ? (
                        <div className="streaming-answer">{message.content}</div>
                      ) : (
                        // 只用消息 ID 定位组件；不能把内容长度放进 key，否则每批文字
                        // 都会销毁再创建整条答案。停止或断流也保留已经排好的内容。
                        <AnswerMarkdown
                          key={message.id}
                          content={message.content}
                          incomplete={Boolean(message.streaming || message.stopped || message.error)}
                        />
                      )
                    ) : !message.error && !message.stopped ? (
                      <div className="thinking-dots"><i /><i /><i /><span>{message.status}</span></div>
                    ) : null}
                    {message.stopped && <p className="stopped-note">已停止生成</p>}
                    {message.error && (
                      <div className="message-error">
                        <span>{message.error}</span>
                        <button type="button" onClick={() => retry(message)}>重新生成</button>
                      </div>
                    )}
                    {message.sources?.length > 0 && <SourceList sources={message.sources} />}
                  </div>
                </article>
              ))}
            </div>
          )}
        </div>

        <footer className="composer-wrap">
          <div className="composer">
            <textarea
              aria-label="向知识库提问"
              disabled={isGenerating}
              maxLength={2000}
              // 4. 受控组件的核心逻辑：- 监听输入框内容变化，每次用户输入时，通过 `setInput` 将最新内容同步到 React 状态 `input` 中。
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="询问亚马逊运营、物流、税务、合规、广告等知识…"
              rows={1}
              value={input}
            />
            {isGenerating ? (
              <button className="stop-button" type="button" onClick={stopGeneration} aria-label="停止生成">■</button>
            ) : (
              <button
                className="send-button"
                type="button"
                disabled={!input.trim()}
                onClick={() => send()}
                aria-label="发送问题"
              >↑</button>
            )}
          </div>
          <p>Enter 发送 · Shift + Enter 换行 · {IS_DEMO ? '预置内容仅展示交互，聊天保存在此浏览器' : '回答仅依据已入库资料'}</p>
        </footer>
      </section>
    </main>
  );
}

function SourceList({ sources }) {
  // SourceList 是无状态展示组件：接收 sources，用 JSX 描述界面，不管理请求。
  // 来源默认折叠，避免长引用打断阅读；每个 [资料 n] 与回答编号一一对应。
  return (
    <details className="source-list">
      <summary>查看 {sources.length} 条参考资料</summary>
      <div className="source-cards">
        {sources.map((source) => (
          <article className="source-card" key={source.id + '-' + source.source}>
            <div><span>[资料 {source.id}]</span><b>{source.title}</b></div>
            <p>{source.excerpt}</p>
            <footer>
              <span>{source.source}</span>
              <span>{source.category}</span>
              {source.published_at && <span>{source.published_at}</span>}
            </footer>
          </article>
        ))}
      </div>
    </details>
  );
}
