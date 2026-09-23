import { memo } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { MessageRenderBoundary } from '../../AppErrorBoundary';
import { prepareMarkdown } from './streamingMarkdown';

// 放在组件外，让插件数组和链接组件的引用保持稳定；每包 token 不必重新创建。
const plugins = [remarkGfm];
const components = {
  a: ({ href, children }) => href
    ? <a href={href} target="_blank" rel="noreferrer noopener">{children}</a>
    : <span>{children}</span>,
};

function MarkdownContent({ content, incomplete }) {
  // 预处理也放在边界的子组件中：如果解析器遇到极端文本抛错，边界才捕获得到。
  // 直接在父组件构造 children 时先调用 prepareMarkdown，会发生在边界保护范围之外。
  return <ReactMarkdown remarkPlugins={plugins} components={components} skipHtml>
    {prepareMarkdown(content, incomplete)}
  </ReactMarkdown>;
}

/** memo 像“内容没变就沿用上次结果”：新答案增长时，历史答案不用全部重新解析。 */
const AnswerMarkdown = memo(function AnswerMarkdown({ content, incomplete }) {
  return (
    <MessageRenderBoundary fallbackText={content}>
      <MarkdownContent content={content} incomplete={incomplete} />
    </MessageRenderBoundary>
  );
});

export default AnswerMarkdown;
