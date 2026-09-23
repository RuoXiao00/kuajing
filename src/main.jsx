import ReactDOM from 'react-dom/client'
import './index.css'
import App from './App.jsx'
import { BrowserRouter, HashRouter } from 'react-router-dom'
import { AppErrorBoundary } from './AppErrorBoundary.jsx'
import { KnowledgeConversationProvider } from './compoment/zhishiku/KnowledgeConversationContext.jsx'
import { PreferencesProvider } from './compoment/shezhi/PreferencesContext.jsx'
// main.jsx 是浏览器启动入口，只在页面首次加载时执行一次。
// 包裹顺序很重要：Router 提供路由，ErrorBoundary 兜底，Provider 提供共享会话。
const root = ReactDOM.createRoot(document.getElementById('root'))
// GitHub Pages 只提供静态文件，不能把 /tupian 回退到 index.html。
// Pages 构建用 #/tupian：刷新仍请求站点首页；本地和同源 Docker 保持原地址。
const Router = import.meta.env.VITE_ROUTER_MODE === 'hash' ? HashRouter : BrowserRouter
root.render(
  <Router>
    <AppErrorBoundary>
      <PreferencesProvider>
        <KnowledgeConversationProvider>
          <App />
        </KnowledgeConversationProvider>
      </PreferencesProvider>
    </AppErrorBoundary>
  </Router>
)
