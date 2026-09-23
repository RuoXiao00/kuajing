/**
 * SSE 收包很碎，先放进普通字符串“暂存盒”，约 50ms 再一次交给 React。
 * rAF 只约下一次绘制，不保证 50ms，所以还要检查时间；空盒不继续占用动画帧。
 * 依赖从参数传进来，测试就能用假时钟，不必真的等待或调用模型。
 */
export function createTokenBuffer({ onFlush, requestFrame, cancelFrame, now, interval = 50 }) {
  let pending = '';
  let frame = null;
  let lastFlush = now();
  let disposed = false;

  function flush() {
    if (frame !== null) cancelFrame(frame);
    frame = null;
    if (!pending) return;
    const text = pending;
    pending = '';
    lastFlush = now();
    onFlush(text);
  }

  function tick() {
    frame = null;
    if (disposed || !pending) return;
    if (now() - lastFlush >= interval) flush();
    else frame = requestFrame(tick);
  }

  return {
    push(text) {
      if (disposed || !text) return;
      pending += text;
      if (frame === null) frame = requestFrame(tick);
    },
    flush,
    dispose() {
      // 正常结束/停止/失败先 flush，再销毁；旧请求的帧不能继续往新会话写文字。
      disposed = true;
      if (frame !== null) cancelFrame(frame);
      frame = null;
      pending = '';
    },
  };
}
