/**
 * 聊天滚动控制器：只有“正在跟随最新消息”时，才调整消息容器自己的 scrollTop。
 *
 * 这是普通 JS 函数，不是 React 组件。Hook 在 DOM 挂载后创建它，文字更新后调用
 * update，发送新问题/切换会话时调用 followLatest，离开页面时调用 dispose。
 * following 像一个开关：向上翻历史就关掉；手动回到底部或发送新问题再打开。
 * 开关存在闭包里，不属于聊天记录，不会进入 localStorage 或发给后端。
 */
export function createChatAutoScroll(container) {
  let following = true;
  let previousTop = container.scrollTop;
  let touchY = null;
  let disposed = false;

  function update() {
    if (disposed || !following) return;
    // scrollHeight 是全部内容高度，clientHeight 是可见窗口高度；相减才是底部位置。
    // 内容不够一屏时得到负数，取 0，避免无意义的来回滚动。
    const bottom = Math.max(0, container.scrollHeight - container.clientHeight);
    if (Math.abs(container.scrollTop - bottom) > 1) {
      // 流式追加已经在逐帧变化，不能每块文字再启动一段 smooth 动画。
      // 只滚这个容器，不用 scrollIntoView，避免连外层页面也被一起带动。
      container.scrollTo({ top: bottom, behavior: 'instant' });
    }
    // 程序刚滚完会触发 scroll 事件，先记住当前位置，避免误判成用户上滑。
    previousTop = container.scrollTop;
  }

  function onScroll() {
    const top = container.scrollTop;
    if (top < previousTop - 1) {
      following = false;
    } else if (container.scrollHeight - container.clientHeight - top <= 2) {
      // 2px 只用于容忍浏览器的小数/取整误差，不是“离底部还有一大段也强行拉回”。
      following = true;
    }
    previousTop = top;
  }

  function onWheel(event) {
    // wheel 先于浏览器实际滚动发生。先关开关，防止同一帧到来的 token 抢走位置。
    if (event.deltaY < 0) following = false;
  }

  function onTouchStart(event) {
    touchY = event.touches[0]?.clientY ?? null;
  }

  function onTouchMove(event) {
    const nextY = event.touches[0]?.clientY;
    // 手指向下拖，看到的是更上面的历史；与鼠标滚轮的 deltaY 方向相反。
    if (touchY !== null && nextY > touchY) following = false;
    touchY = nextY ?? null;
  }

  function onKeyDown(event) {
    // 不接管输入控件的光标移动；消息区域本身可通过 Tab 获得焦点并用键盘滚动。
    const target = event.target;
    if (target?.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target?.tagName)) return;
    if (['ArrowUp', 'PageUp', 'Home'].includes(event.key)
      || (event.key === ' ' && event.shiftKey && target === container)) following = false;
  }

  function onToggle(event) {
    // 用户展开来源是要阅读资料，不应被后续 token 自动拖到卡片最下面。
    if (event.target?.tagName === 'DETAILS' && event.target.open) following = false;
  }

  const passive = { passive: true };
  container.addEventListener('scroll', onScroll, passive);
  container.addEventListener('wheel', onWheel, passive);
  container.addEventListener('touchstart', onTouchStart, passive);
  container.addEventListener('touchmove', onTouchMove, passive);
  container.addEventListener('keydown', onKeyDown);
  // toggle 不冒泡，用捕获阶段监听子级 details；解绑必须使用相同的 capture 值。
  container.addEventListener('toggle', onToggle, true);

  return {
    update,
    followLatest() {
      if (disposed) return;
      following = true;
      update();
    },
    dispose() {
      // StrictMode 会试验性地挂载/清理再挂载；旧控制器必须停止工作且彻底解绑。
      disposed = true;
      container.removeEventListener('scroll', onScroll);
      container.removeEventListener('wheel', onWheel);
      container.removeEventListener('touchstart', onTouchStart);
      container.removeEventListener('touchmove', onTouchMove);
      container.removeEventListener('keydown', onKeyDown);
      container.removeEventListener('toggle', onToggle, true);
    },
  };
}
