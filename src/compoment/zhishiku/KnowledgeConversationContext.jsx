/* oxlint-disable react/only-export-components -- Provider 与配套 Hook 必须共享同一 Context 实例。 */
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import {
  MAX_CONVERSATIONS,
  loadConversations,
  newConversation,
  persistConversations,
} from './knowledgeConversationStore';

const KnowledgeConversationContext = createContext(null);

// Provider 是会话状态的唯一拥有者。它包住整个应用，侧栏与聊天页通过
// 同一个 Hook 读取状态，所以切换会话会在两个位置同步体现。
export function KnowledgeConversationProvider({ children }) {
  // 会话与 activeId 放进同一状态对象，可以原子地删除当前会话并选择下一项，
  // 避免在一个 setState 回调中再次调用另一个 setState。
  const [conversationState, setConversationState] = useState(() => {
    const conversations = loadConversations();
    return { conversations, activeId: conversations[0].id };
  });
  const [isGenerating, setIsGenerating] = useState(false);
  const [storageWarning, setStorageWarning] = useState('');
  // useRef 保存 AbortController，但 ref 改变不会触发渲染，适合网络句柄；
  // 是否生成中需要更新界面，因此另用 useState 保存。
  const controllerRef = useRef(null);

  const { conversations, activeId } = conversationState;
  const activeConversation = useMemo(
    // useMemo 缓存派生结果而不复制第二份状态，依赖变化时才重新查找。
    () => conversations.find((item) => item.id === activeId) || conversations[0],
    [conversations, activeId],
  );

  // 750ms 防抖把密集 token 合并保存；但用户可能不等 750ms 就刷新，所以离开页面
  // 或切到后台时还要立即保存。这像“平时攒一批记账，离店前把最后一笔结清”。
  // 不在这里读取 window.localStorage：让存储模块在自己的 try 内取对象并兜住权限错误。
  useEffect(() => {
    let pending = true;
    function saveLatest() {
      // 同一次状态可能先遇到 visibilitychange，再遇到 pagehide；只保存一次。
      if (!pending) return;
      pending = false;
      const result = persistConversations(undefined, conversations, activeId);
      setStorageWarning((current) => current === result.warning ? current : result.warning);
    }
    function saveWhenHidden() {
      if (document.visibilityState === 'hidden') saveLatest();
    }
    const timer = window.setTimeout(saveLatest, 750);
    window.addEventListener('pagehide', saveLatest);
    document.addEventListener('visibilitychange', saveWhenHidden);
    return () => {
      // 每次状态变化会替换闭包，使监听器拿到最新 conversations，而非首次渲染的数组。
      // 清理只取消旧任务，不在这里写库：Effect 每个 token 都清理，写这里会抵消防抖。
      window.clearTimeout(timer);
      window.removeEventListener('pagehide', saveLatest);
      document.removeEventListener('visibilitychange', saveWhenHidden);
    };
  }, [conversations, activeId]);

  const stopGeneration = useCallback(() => {
    // useCallback 缓存的是函数，不会主动执行它；点击停止、切换会话等才调用。
    // ?. 表示没有正在生成的控制器就什么也不做，避免对 null 调用 abort。
    controllerRef.current?.abort();
  }, []);

  const beginGeneration = useCallback((controller) => {
    controllerRef.current?.abort();
    controllerRef.current = controller;
    setIsGenerating(true);
  }, []);

  const finishGeneration = useCallback((controller) => {
    // 用“是不是同一个控制器对象”判断请求身份，不是比较两次请求的问题文字。
    // 例：A 被停止后立刻开始 B，A 的 finally 可能晚到；若它直接清空 current，
    // B 就会被误标成未生成。只有仍负责当前请求的控制器，才有权做这次清理。
    if (controllerRef.current === controller) {
      controllerRef.current = null;
      setIsGenerating(false);
    }
  }, []);

  const updateConversation = useCallback((id, updater) => {
    // 函数式 setState 总能取得最新状态，避免流式回调捕获旧数组。
    // updater 只描述目标会话如何变化，Context 统一负责定位。
    setConversationState((current) => ({
      ...current,
      conversations: current.conversations.map((item) => (
        item.id === id ? updater(item) : item
      )),
    }));
  }, []);

  const createChat = useCallback(() => {
    stopGeneration();
    const created = newConversation();
    setConversationState((current) => ({
      activeId: created.id,
      conversations: [created, ...current.conversations].slice(0, MAX_CONVERSATIONS),
    }));
    return created.id;
  }, [stopGeneration]);

  const selectChat = useCallback((id) => {
    setConversationState((current) => {
      if (current.activeId === id) return current;
      stopGeneration();
      return current.conversations.some((item) => item.id === id)
        ? { ...current, activeId: id }
        : current;
    });
  }, [stopGeneration]);

  const deleteChat = useCallback((id) => {
    setConversationState((current) => {
      const remaining = current.conversations.filter((item) => item.id !== id);
      if (id === current.activeId) stopGeneration();
      if (remaining.length) {
        return {
          conversations: remaining,
          activeId: id === current.activeId ? remaining[0].id : current.activeId,
        };
      }
      const created = newConversation();
      return { conversations: [created], activeId: created.id };
    });
  }, [stopGeneration]);

  const value = useMemo(() => ({
    // 缓存 value 与各回调引用，防止 Provider 每次渲染都让消费者无效重渲染。
    // 不是“一用了 useMemo 就不渲染”：conversations 真变了，消费者仍需要更新。
    // 这里仅避免依赖没变时凭空创建另一个 value 对象，触发没有必要的通知。
    conversations,
    activeId,
    activeConversation,
    isGenerating,
    storageWarning,
    updateConversation,
    createChat,
    selectChat,
    deleteChat,
    beginGeneration,
    finishGeneration,
    stopGeneration,
  }), [
    conversations,
    activeId,
    activeConversation,
    isGenerating,
    storageWarning,
    updateConversation,
    createChat,
    selectChat,
    deleteChat,
    beginGeneration,
    finishGeneration,
    stopGeneration,
  ]);

  return (
    <KnowledgeConversationContext.Provider value={value}>
      {children}
    </KnowledgeConversationContext.Provider>
  );
}

export function useKnowledgeConversations() {
  // 自定义 Hook 隐藏 Context 细节，并在忘记 Provider 时给出明确错误。
  const value = useContext(KnowledgeConversationContext);
  if (!value) throw new Error('useKnowledgeConversations 必须在 Provider 内使用');
  return value;
}
