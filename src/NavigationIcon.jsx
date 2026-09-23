/**
 * 小型内联 SVG：沿用 currentColor 跟随文字颜色，不请求图片，也不依赖图标字体。
 * aria-hidden 表示图标只是装饰；可访问名称来自旁边文字或按钮的 aria-label。
 */
export default function NavigationIcon({ name }) {
  const paths = {
    recommend: <><path d="m3 3 2 2 2 11h11l3-8H6" /><circle cx="9" cy="20" r="1" /><circle cx="18" cy="20" r="1" /></>,
    knowledge: <><path d="M12 5c-3-2-6-2-9-1v15c3-1 6-1 9 1 3-2 6-2 9-1V4c-3-1-6-1-9 1Z" /><path d="M12 5v15" /></>,
    hot: <path d="M13 3c1 5-5 6-4 10-2-1-3-2-3-4-6 7-1 13 6 12 7 0 9-8 5-12 0 3-2 4-3 3 2-4 0-7-1-9Z" />,
    image: <><rect x="3" y="3" width="18" height="18" rx="3" /><circle cx="8" cy="8" r="1.5" /><path d="m3 17 5-5 4 4 4-6 5 7" /></>,
    chat: <path d="M20 15a3 3 0 0 1-3 3H9l-5 3V6a3 3 0 0 1 3-3h10a3 3 0 0 1 3 3Z" />,
    plus: <path d="M12 5v14M5 12h14" />,
    close: <path d="m6 6 12 12M18 6 6 18" />,
    panel: <><rect x="3" y="4" width="18" height="16" rx="3" /><path d="M9 4v16" /></>,
    menu: <path d="M4 6h16M4 12h16M4 18h16" />,
    down: <path d="m7 10 5 5 5-5" />,
    up: <path d="m7 14 5-5 5 5" />,
  };
  return <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor"
    strokeWidth="1.65" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
    {paths[name] || paths.chat}
  </svg>;
}
