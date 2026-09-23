import remend, { isWithinCodeBlock } from 'remend';

/**
 * 只处理“给眼睛看的副本”，不改变 Context/localStorage 中收到的原文。
 * 例如网络目前只送来 **重要，先按 **重要** 展示；下一包仍从原文重新计算。
 * 如果把补上的符号也存进历史，后续 token 接上来就会把 Markdown 弄乱。
 */
export function prepareMarkdown(content, incomplete = false) {
  if (!incomplete) return content;
  let preview = content;
  // 代码里的 **/# 是代码本身，不能当作装饰符号删除。围栏和行内代码都要避开。
  const inFence = isWithinCodeBlock(preview, preview.length);
  const line = preview.slice(preview.lastIndexOf('\n') + 1);
  const ticks = line.match(/(?<!\\)`+/g) || [];
  const inInlineCode = ticks.length % 2 === 1;
  if (!inFence && !inInlineCode) {
    // 还没收到标题文字/列表内容时先不画标记；有正文后再交给 Markdown 解析。
    // 仅收起末尾未成形的前缀，不是全局删除 * 或 #；反斜杠转义也不匹配。
    preview = preview.replace(/(^|\n) {0,3}(?:#{1,6}|[-+*]|\d{1,9}[.)]|>{1,3})[ \t]*$/, '$1');
    preview = preview.replace(/(^|[\s([>])([*_]{1,3}|~{1,2})$/, '$1');
  }
  return remend(preview, {
    linkMode: 'text-only', // URL 尚未收完，只显示文字，不提供会跳错地址的半截链接。
    inlineKatex: false, // 跨境业务中 $ 常表示美元，不把价格猜成数学公式。
    katex: false,
  });
}
