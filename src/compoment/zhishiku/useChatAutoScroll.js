import { useCallback, useLayoutEffect, useRef } from 'react';
import { createChatAutoScroll } from './chatAutoScroll';

/** 把普通滚动控制器接入 React：组件描述消息，Hook 负责 DOM 提交后的滚动。 */
export function useChatAutoScroll(conversationId, messages) {
  const scrollContainerRef = useRef(null);
  const controllerRef = useRef(null);
  const previousConversationRef = useRef(null);

  useLayoutEffect(() => {
    const container = scrollContainerRef.current;
    if (!container) return undefined;
    const controller = createChatAutoScroll(container);
    controllerRef.current = controller;
    // 只观察可见窗口的尺寸（例如折叠侧栏/旋转手机），不盯着每个 token 创建定时器。
    // 文本高度变化由下面的消息 Effect 处理；用户展开来源不会强制跳到卡片末尾。
    const observer = typeof ResizeObserver === 'undefined'
      ? null
      : new ResizeObserver(() => controller.update());
    observer?.observe(container);
    return () => {
      observer?.disconnect();
      controller.dispose();
      controllerRef.current = null;
    };
  }, []);

  useLayoutEffect(() => {
    // useLayoutEffect 发生在 DOM 已更新、浏览器还没把这一帧画出来时。
    // 此时一次校正位置，就不会先显示旧位置、下一刻又滑走；不能在里面调用模型或做耗时计算。
    const controller = controllerRef.current;
    if (previousConversationRef.current !== conversationId) {
      previousConversationRef.current = conversationId;
      controller?.followLatest();
    } else {
      // 不因每个 token 都重开 following；用户已经向上翻时，update 内部会直接返回。
      controller?.update();
    }
  }, [conversationId, messages]);

  const followLatest = useCallback(() => controllerRef.current?.followLatest(), []);
  return { scrollContainerRef, followLatest };
}
