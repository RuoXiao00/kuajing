// Actions 在构建前检查公开 API 地址，防止上线后仍访问游客自己的 localhost。
// 本脚本不读取或输出 .env，也不需要任何供应商凭据。
const raw = process.env.VITE_API_BASE_URL || '';
let api;
try { api = new URL(raw); } catch { /* 统一在下面给出填写位置。 */ }
if (!api || api.protocol !== 'https:' || api.username || api.password
  || api.pathname !== '/' || api.search || api.hash
  || ['localhost', '127.0.0.1', '[::1]'].includes(api.hostname)
  || api.hostname.endsWith('.example.com') || api.hostname === 'example.com') {
  console.error('请在仓库 Settings → Secrets and variables → Actions → Variables 设置 VITE_API_BASE_URL，例如 https://api.你的真实域名；不要带 /api、用户名或密码。');
  process.exit(1);
}
console.log('Pages 公开 API 地址配置检查通过。');
