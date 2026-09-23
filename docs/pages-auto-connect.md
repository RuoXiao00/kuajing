# 备案通过后：自动连接真实后端

前端已经设置为优先连接 `https://api.qiyuange.online`。检测失败时展示样例，检测通过时加载真实页面。**不需要等备案通过再改代码、换压缩包或重建前端。** 下面的服务器和域名配置需要做一次；前端代码无法替你修改云服务器的跨域白名单或 DNS。

## 1. 在服务器执行一次

你现有后端已经运行于 `/www/kuajing-next`，容器端口为 `127.0.0.1:18000`。在宝塔终端复制：

```bash
cd /www/kuajing-next
curl --fail --show-error --location https://raw.githubusercontent.com/RuoXiao00/kuajing/main/deploy/enable-pages-origin.sh -o deploy/enable-pages-origin.sh
bash deploy/enable-pages-origin.sh
```

脚本源码：[enable-pages-origin.sh](../deploy/enable-pages-origin.sh)。

它会备份 `deploy/backend.env`，把允许来源配置为：

```text
FRONTEND_ORIGINS=https://ruoxiao00.github.io,https://app.qiyuange.online
COOKIE_SECURE=true
```

不会打印或替换你的百炼、Coze、管理员密码和会话密钥，不删除任何数据库或图片。Compose 会重新创建容器以读取配置，短暂中断接口；不构建镜像、不重新下载依赖。`docker restart` 不会重新读取 env_file，所以不能替代这一步。

下载若因服务器无法连接 GitHub 失败，停止，不执行不完整脚本；可将仓库中该脚本上传到相同位置后运行。没有必要重新上传整个后端。

## 2. 把 Pages 绑定到自己的前端域名

展示版现在可以直接用：

**https://ruoxiao00.github.io/kuajing/**

真实图片历史和管理员登录采用 Strict Cookie。`github.io` 与 `qiyuange.online` 不是同一站点；即使 CORS 已配置，Cookie 也不能据此正常携带。为了避免创建付费图片后无法读回结果，真实模式在 github.io 地址下会提示使用项目域名。

请做以下一次性配置：

1. 仓库 **Settings → Pages → Custom domain** 填写 `app.qiyuange.online`，保存。
2. 阿里云 DNS 添加记录：

| 主机记录 | 类型 | 记录值 |
| --- | --- | --- |
| app | CNAME | RuoXiao00.github.io |

3. 保留已有的 `api` A 记录，仍指向后端服务器。不要将 app 指向服务器 IP，也不要在 CNAME 后面加 `/kuajing`。
4. Pages 显示 DNS 检查通过、证书可用后，勾选 **Enforce HTTPS**。
5. 仓库 **Actions → Publish frontend to GitHub Pages → Run workflow**，mode 保持 **auto**，执行一次，让构建获取自定义域名的根路径。此后入口为 **https://app.qiyuange.online/**。

前端仍托管在 GitHub Pages，后端仍在阿里云；这不是迁移前端服务器。GitHub 自定义域名设置和 DNS 生效可能需要等待。步骤依据 [GitHub 官方自定义域名说明](https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site/managing-a-custom-domain-for-your-github-pages-site)，Cookie 行为见 [MDN Set-Cookie](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Set-Cookie)。

## 3. 备案通过后，验证一次即可

备案状态更新与公网放行不一定同时完成。请在你自己的电脑 PowerShell 中执行，而不是使用服务器内的绕过域名测试：

```powershell
curl.exe --fail --max-time 10 https://api.qiyuange.online/api/knowledge/health
curl.exe -i --max-time 10 -H "Origin: https://app.qiyuange.online" https://api.qiyuange.online/api/knowledge/health
```

预期：

- 返回 JSON，status 为 `ok` 或 `degraded`；后者表示精排降级，仍可使用。
- 第二条响应包含 `access-control-allow-origin: https://app.qiyuange.online` 和 `access-control-allow-credentials: true`。
- 若返回备案拦截页、证书错误或无法连接，前端会继续展示样例。不要关闭 HTTPS 或改回 HTTP。

随后打开 **https://app.qiyuange.online/**：

- 自动检测成功，顶部的“交互展示”提示消失。
- 产品推荐读取真实快照；知识库显示实际文档数量。
- 如果文档数为 0，先通过管理页导入知识文件，否则无法验证有资料的真实 RAG 回答。
- 上传产品图并提交后才调用收费生图；这不是检测步骤，不会自动替你生成图片。

## 自动行为的边界

- 每次打开或刷新页面，最多等待 2.5 秒检测真实后端；较慢或暂时故障会优先保障展示。
- 展示模式在页面可见时每分钟检测，重新切回标签页也检测。
- 没有操作时检测恢复可自动刷新；已经操作的页面会提示恢复，并在下一次切换页面时连接，避免清空正在输入的提示词。也可点“立即连接”。
- 已经开始的真实请求不会转成伪造成功结果。单个模型、爬虫或 Coze 失败仍按真实错误处理；重新打开页面会再次判断连接状态。
- 样例商品、会话与真实模式缓存隔离，不把样例存进服务器。
- 自动检测只读健康状态，不生成每日推荐，不调用 Coze 或回答模型。

## 不想自动连接时如何切换

通常不用修改这些设置。需要固定展示给面试官时，在仓库 **Settings → Secrets and variables → Actions → Variables** 设置：

| 变量 | 值 |
| --- | --- |
| PAGES_MODE | demo |

再在 Actions 执行 mode=demo。要恢复自动连接，改为 auto 并执行 mode=auto。仅在手动运行中选模式只影响那一次发布；后续 push 使用仓库变量，未设置时默认 auto。

其他可选变量：

- `VITE_API_BASE_URL`：更换真实后端域名时才填，默认已是 `https://api.qiyuange.online`。不要加 /api，也不要放密钥。
- `PAGES_MODE=live`：强制真实服务，不做启动时样例回退。

## 如果服务器配置后异常

配置脚本会在 `deploy/` 下留下 `backend.env.backup-时间`。用宝塔找到本次备份，复制覆盖回 `backend.env`，权限保持 600，再执行：

```bash
cd /www/kuajing-next
docker compose -f compose.baota.yaml up -d --no-build --wait --wait-timeout 180
```

不要执行 `down -v`，不要删除 server-data。
