import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig(({ mode }) => ({
  // npm run dev:demo / build:demo 无需 .env 或密钥；真实开发模式不覆盖这些变量。
  define: mode === 'demo' ? {
    'import.meta.env.VITE_DEMO_MODE': JSON.stringify('true'),
    'import.meta.env.VITE_CONNECTION_MODE': JSON.stringify('demo'),
    'import.meta.env.VITE_ROUTER_MODE': JSON.stringify('hash'),
    'import.meta.env.VITE_API_BASE_URL': JSON.stringify(''),
  } : {},
  // Pages 项目站部署在 /仓库名/，自定义域名部署在 /；由 Actions 在构建时传入。
  // 开发和原来的服务器同源部署不设置此变量，继续使用根路径。
  base: process.env.VITE_BASE_PATH || '/',
  plugins: [react()],
  // 开发环境把同源 /api 请求转发到 FastAPI。浏览器因此能正常携带
  // SameSite=Strict 管理 Cookie，也不需要在组件里硬编码 127.0.0.1。
  server: {
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      // 只代理接口，不能代理整个 /tuijian 前缀：后者也是 React 页面地址，
      // 否则直接打开/刷新推荐页时，HTML 会被错误地转给 FastAPI，得到 404。
      '/tuijian/agentcall': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
}))
