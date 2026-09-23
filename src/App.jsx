import { useEffect, useState } from 'react';
import { NavLink, useLocation, useRoutes } from 'react-router-dom';
import './App.css';
import routers from './routers';
import NavigationIcon from './NavigationIcon';
import { useKnowledgeConversations } from './compoment/zhishiku/KnowledgeConversationContext';
import { usePreferences } from './compoment/shezhi/usePreferences';

// App 是全站布局组件：路由页放在右侧，导航和知识库会话列表放在左侧。
// 页面状态改变会让函数重新执行，但 localStorage 和会话数据分别由专门模块管理。
const NAV_ITEMS = [
  { to: '/tuijian', icon: 'recommend', label: '产品推荐' },
  { to: '/remeng', icon: 'hot', label: '热门产品' },
  { to: '/tupian', icon: 'image', label: '图片生成' },
];

function KnowledgeConversationPanel({ closeMobileNavigation }) {
  const {
    conversations,
    activeId,
    createChat,
    selectChat,
    deleteChat,
    storageWarning,
  } = useKnowledgeConversations();

  function handleCreate() {
    createChat();
    closeMobileNavigation();
  }

  function handleSelect(id) {
    selectChat(id);
    closeMobileNavigation();
  }

  return (
    <section className="knowledge-conversation-panel" id="knowledge-conversation-panel">
      {/* 子列表已位于“知识库”下，不重复放一套 Logo；视觉缩进表示所属关系。 */}
      <button className="new-chat-button" type="button" onClick={handleCreate}>
        <NavigationIcon name="plus" /> 新建会话
      </button>
      <p className="conversation-label">最近会话 · 最多保存 20 个</p>
      <div className="conversation-list">
        {conversations.map((conversation) => (
          <div
            className={'conversation-item ' + (conversation.id === activeId ? 'active' : '')}
            key={conversation.id}
          >
            <button
              className="conversation-select"
              onClick={() => handleSelect(conversation.id)}
              type="button"
              aria-current={conversation.id === activeId ? 'true' : undefined}
            >
              <span className="conversation-icon"><NavigationIcon name="chat" /></span>
              <span className="conversation-title">{conversation.title}</span>
            </button>
            <button
              className="delete-conversation"
              onClick={() => deleteChat(conversation.id)}
              type="button"
              aria-label={'删除会话 ' + conversation.title}
              title={'删除会话 ' + conversation.title}
            ><NavigationIcon name="close" /></button>
          </div>
        ))}
      </div>
      {storageWarning && <p className="sidebar-storage-warning" role="status">{storageWarning}</p>}
      <div className="privacy-note">
        <strong>本地会话</strong>
        <span>聊天仅保存在此浏览器，后端不永久保存匿名历史。</span>
      </div>
    </section>
  );
}

function StandardNavigationLink({ item, onNavigate }) {
  return (
    <NavLink
      to={item.to}
      className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}
      onClick={onNavigate}
      title={item.label}
    >
      <span className="nav-icon" aria-hidden="true"><NavigationIcon name={item.icon} /></span>
      <span className="nav-label">{item.label}</span>
    </NavLink>
  );
}

export default function App() {
  // useRoutes 根据当前 URL 生成页面元素，useLocation 提供路由信息。
  // 桌面折叠来自共享设置；知识列表展开和手机抽屉仍是当前页面的临时状态。
  const routeElements = useRoutes(routers);
  const location = useLocation();
  const { preferences, updatePreferences } = usePreferences();
  const navCollapsed = preferences.sidebarCollapsed;
  const setNavCollapsed = (value) => updatePreferences({
    sidebarCollapsed: typeof value === 'function' ? value(navCollapsed) : value,
  });
  const [knowledgeExpanded, setKnowledgeExpanded] = useState(
    location.pathname.startsWith('/zhishiku'),
  );
  const [mobileNavigationOpen, setMobileNavigationOpen] = useState(false);
  const isKnowledgeRoute = location.pathname.startsWith('/zhishiku');

  useEffect(() => {
    // 从其他功能重新进入知识库时总是展开会话区域；离开路由则把抽屉关闭。
    // oxlint-disable-next-line react/set-state-in-effect -- 这里同步的是浏览器路由这一外部状态。
    setKnowledgeExpanded(isKnowledgeRoute);
    setMobileNavigationOpen(false);
  }, [isKnowledgeRoute, location.pathname]);

  useEffect(() => {
    if (!mobileNavigationOpen) return undefined;
    const closeOnEscape = (event) => {
      if (event.key === 'Escape') setMobileNavigationOpen(false);
    };
    window.addEventListener('keydown', closeOnEscape);
    return () => window.removeEventListener('keydown', closeOnEscape);
  }, [mobileNavigationOpen]);

  if (location.pathname.startsWith('/admin')) {
    return <div className="admin-shell">{routeElements}</div>;
  }

  // 面板是否“展开”只由路由和按钮决定。桌面整栏折叠时由 CSS 隐藏，但仍
  // 保留 DOM，才能让使用相同状态的移动抽屉正常显示会话列表。
  const knowledgePanelOpen = isKnowledgeRoute && knowledgeExpanded;

  function handleKnowledgeClick(event) {
    // 从其他页面点击时让 NavLink 正常跳转；已在知识库时 preventDefault，
    // 把同一个按钮改成展开/收起开关，这是路由行为与界面行为的分界点。
    if (!isKnowledgeRoute) {
      setNavCollapsed(false);
      setKnowledgeExpanded(true);
      return;
    }
    event.preventDefault();
    if (navCollapsed) {
      setNavCollapsed(false);
      setKnowledgeExpanded(true);
    } else {
      setKnowledgeExpanded((current) => !current);
    }
  }

  return (
    <div className={`App ${navCollapsed ? 'nav-collapsed' : ''} ${mobileNavigationOpen ? 'mobile-nav-open' : ''}`}>
      <button
        className="mobile-nav-toggle"
        type="button"
        aria-label="打开导航"
        aria-expanded={mobileNavigationOpen}
        onClick={() => setMobileNavigationOpen(true)}
      ><NavigationIcon name="menu" /></button>
      <button
        className="navigation-backdrop"
        type="button"
        aria-label="关闭导航"
        onClick={() => setMobileNavigationOpen(false)}
      />

      <aside className="router-header" aria-label="主导航">
        <div className="router-brand">
          <img src={`${import.meta.env.BASE_URL}pt8.jpg`} alt="跨境阁" className="logo" />
          <strong className="brand-name">跨境阁</strong>
        </div>
        <button
          className="sidebar-collapse-button"
          type="button"
          onClick={() => setNavCollapsed((current) => !current)}
          aria-label={navCollapsed ? '展开左侧导航' : '收起左侧导航'}
          title={navCollapsed ? '展开左侧导航' : '收起左侧导航'}
        ><NavigationIcon name="panel" /></button>
        <button
          className="mobile-nav-close"
          type="button"
          aria-label="关闭导航"
          onClick={() => setMobileNavigationOpen(false)}
        ><NavigationIcon name="close" /></button>

        {/* 导航名称使用项目原文，避免浏览器自动翻译改写“知识库”等功能名。 */}
        <nav className="router-nav" translate="no">
          <StandardNavigationLink item={NAV_ITEMS[0]} onNavigate={() => setMobileNavigationOpen(false)} />
          <div className={`knowledge-nav-group ${knowledgePanelOpen ? 'open' : ''}`}>
            <NavLink
              to="/zhishiku"
              className={({ isActive }) => `nav-item knowledge-nav-button ${isActive ? 'active' : ''}`}
              onClick={handleKnowledgeClick}
              title="知识库"
              aria-label="知识库"
              aria-expanded={knowledgePanelOpen}
              aria-controls="knowledge-conversation-panel"
            >
              <span className="nav-icon" aria-hidden="true"><NavigationIcon name="knowledge" /></span>
              <span className="nav-label">知识库</span>
              <span className="nav-caret" aria-hidden="true"><NavigationIcon name={knowledgePanelOpen ? 'up' : 'down'} /></span>
            </NavLink>
            {knowledgePanelOpen && (
              <KnowledgeConversationPanel
                closeMobileNavigation={() => setMobileNavigationOpen(false)}
              />
            )}
          </div>
          {NAV_ITEMS.slice(1).map((item) => (
            <StandardNavigationLink
              item={item}
              key={item.to}
              onNavigate={() => setMobileNavigationOpen(false)}
            />
          ))}
        </nav>

        <NavLink
          to="/settings"
          className={({ isActive }) => `account-settings ${isActive ? 'active' : ''}`}
          onClick={() => setMobileNavigationOpen(false)}
          title="账号设置"
        >
          <img src={`${import.meta.env.BASE_URL}pt8.jpg`} alt="账号头像" className="account-avatar" />
          <span className="account-nickname" translate="no">{preferences.nickname}</span>
          <span className="account-icon">设置</span>
        </NavLink>
      </aside>
      <main className="router-content">{routeElements}</main>
    </div>
  );
}
