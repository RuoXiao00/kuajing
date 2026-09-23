import assert from 'node:assert/strict';
import test from 'node:test';
import { createChatAutoScroll } from './chatAutoScroll.js';

// Fake 只提供控制器会用到的 DOM 尺寸/事件/滚动方法，不启动浏览器或请求任何模型。
// 浏览器验收另外检查真实布局；这里用精确断言防止以后重新引入逐 token 平滑滚动。
function fakeContainer() {
  const listeners = new Map();
  return {
    scrollTop: 0, scrollHeight: 1000, clientHeight: 400, calls: [],
    addEventListener(name, callback) { listeners.set(name, callback); },
    removeEventListener(name, callback) {
      if (listeners.get(name) === callback) listeners.delete(name);
    },
    scrollTo(options) { this.calls.push(options); this.scrollTop = options.top; },
    emit(name, event = {}) { listeners.get(name)?.(event); },
    listenerCount() { return listeners.size; },
  };
}

test('连续追加只即时滚消息容器，没有 smooth 动画，尺寸未变时不重复写入', () => {
  const element = fakeContainer();
  const controller = createChatAutoScroll(element);
  controller.update();
  for (let i = 0; i < 100; i++) {
    element.scrollHeight += 10;
    controller.update();
    element.emit('scroll'); // 浏览器程序滚动后的事件不能把跟随关掉。
  }
  assert.equal(element.scrollTop, 1600);
  assert.ok(element.calls.every(call => call.behavior === 'instant'));
  const count = element.calls.length;
  controller.update();
  assert.equal(element.calls.length, count);
});

test('上滑阅读时 token 不抢位置，手动滚回底部才恢复跟随', () => {
  const element = fakeContainer();
  const controller = createChatAutoScroll(element);
  controller.followLatest();
  element.emit('wheel', { deltaY: -100 });
  element.scrollTop = 500;
  element.emit('scroll');
  element.scrollHeight += 500;
  controller.update();
  assert.equal(element.scrollTop, 500);
  element.scrollTop = 1100;
  element.emit('scroll');
  element.scrollHeight += 20;
  controller.update();
  assert.equal(element.scrollTop, 1120);
});

test('用户上滑意图先于 scroll 事件生效；发送新问题可主动恢复', () => {
  const element = fakeContainer();
  const controller = createChatAutoScroll(element);
  controller.followLatest();
  element.emit('wheel', { deltaY: -10 });
  element.scrollHeight += 100;
  controller.update();
  assert.equal(element.scrollTop, 600);
  controller.followLatest();
  assert.equal(element.scrollTop, 700);
});

test('拖动滚动条向上也暂停，靠近底部但尚未回到底部不抢滚动', () => {
  const element = fakeContainer();
  const controller = createChatAutoScroll(element);
  controller.followLatest();
  element.scrollTop = 580;
  element.emit('scroll');
  element.scrollHeight += 50;
  controller.update();
  assert.equal(element.scrollTop, 580);
});

test('触摸向下拖或 PageUp 暂停跟随，水平滚轮不影响纵向跟随', () => {
  const element = fakeContainer();
  const controller = createChatAutoScroll(element);
  controller.followLatest();
  element.emit('wheel', { deltaY: 0 });
  element.scrollHeight += 10;
  controller.update();
  assert.equal(element.scrollTop, 610);
  element.emit('touchstart', { touches: [{ clientY: 100 }] });
  element.emit('touchmove', { touches: [{ clientY: 120 }] });
  element.scrollHeight += 100;
  controller.update();
  assert.equal(element.scrollTop, 610);
  controller.followLatest();
  element.emit('keydown', { key: 'PageUp', target: element });
  element.scrollHeight += 100;
  controller.update();
  assert.equal(element.scrollTop, 710);
});

test('展开来源时暂停自动跟随，方便读资料', () => {
  const element = fakeContainer();
  const controller = createChatAutoScroll(element);
  controller.followLatest();
  element.emit('toggle', { target: { tagName: 'DETAILS', open: true } });
  element.scrollHeight += 200;
  controller.update();
  assert.equal(element.scrollTop, 600);
});

test('卸载后解绑全部事件，旧回调不再滚动新页面', () => {
  const element = fakeContainer();
  const controller = createChatAutoScroll(element);
  controller.dispose();
  controller.update();
  controller.followLatest();
  assert.equal(element.calls.length, 0);
  assert.equal(element.listenerCount(), 0);
});

test('短内容不滚负数，完成渲染收缩高度时仍正确定位到底部', () => {
  const element = fakeContainer();
  const controller = createChatAutoScroll(element);
  element.scrollHeight = 200;
  controller.update();
  assert.equal(element.calls.length, 0);
  element.scrollHeight = 1200;
  controller.update();
  element.scrollHeight = 900;
  controller.update();
  element.emit('scroll');
  element.scrollHeight = 1000;
  controller.update();
  assert.equal(element.scrollTop, 600);
});
