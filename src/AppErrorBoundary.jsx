import { Component } from 'react';
import { KNOWLEDGE_STORAGE_KEY } from './compoment/zhishiku/knowledgeConversationStore';

/** 捕获页面渲染异常，给用户一个可恢复界面，而不是让 React 根节点整页空白。 */
export class AppErrorBoundary extends Component {
  // Error Boundary 必须使用 React class 生命周期；普通 try/catch 无法捕获
  // 子组件渲染阶段的异常。它不捕获事件处理器和异步请求中的异常。
  state = { failed: false };

  static getDerivedStateFromError() {
    // static 方法在失败后产生替代 state，React 随后重新渲染 fallback 界面。
    return { failed: true };
  }

  componentDidCatch(error, info) {
    // 控制台保留开发诊断信息；页面只展示安全、可操作的恢复提示。
    console.error('页面渲染失败', error, info);
  }

  clearKnowledgeHistory = () => {
    try {
      window.localStorage.removeItem(KNOWLEDGE_STORAGE_KEY);
    } finally {
      window.location.reload();
    }
  };

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <main className="app-error-fallback" role="alert">
        <div>
          <strong>页面遇到异常，但知识库数据没有被删除</strong>
          <p>可以先重新加载；如果是浏览器中的旧会话损坏，再手动清理本地会话。</p>
          <div>
            <button type="button" onClick={() => window.location.reload()}>重新加载</button>
            <button type="button" className="secondary" onClick={this.clearKnowledgeHistory}>
              清理本地会话并重载
            </button>
          </div>
        </div>
      </main>
    );
  }
}

/** 单条 Markdown 失败时只降级该消息为纯文本，不影响输入框和其他会话。 */
export class MessageRenderBoundary extends Component {
  // 第二层边界只包围一条 Markdown；局部失败不会卸载聊天页和输入框。
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error) {
    console.error('Markdown 渲染失败，已回退纯文本', error);
  }

  render() {
    return this.state.failed
      ? <div className="streaming-answer">{this.props.fallbackText}</div>
      : this.props.children;
  }
}
