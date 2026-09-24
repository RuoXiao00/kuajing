# GitHub Pages 与真实后端连接

线上入口：[app.qiyuange.online](https://app.qiyuange.online/)。
后端地址：`https://api.qiyuange.online`。
管理员入口：[登录管理后台](https://app.qiyuange.online/#/admin)。

## 发布模式

GitHub Actions 的 Pages 工作流固定 `VITE_CONNECTION_MODE=live` 和 `VITE_DEMO_MODE=false`，直接请求真实后端。不会在连接失败时显示样例，不执行原来 2.5 秒的启动探测；页面按真实请求显示加载、缓存或错误状态。

推送 main 会自动发布，也可以在 Actions → Publish frontend to GitHub Pages → Run workflow 手动发布。旧的 PAGES_MODE 仓库变量不再控制线上模式。本地离线测试工具仍可独立使用，不影响线上。

## 服务器跨域配置

已配置过可以跳过。宝塔部署在 `/www/kuajing-next` 时，执行一次：

```bash
cd /www/kuajing-next &&
curl -fL https://raw.githubusercontent.com/RuoXiao00/kuajing/main/deploy/enable-pages-origin.sh -o deploy/enable-pages-origin.sh &&
bash deploy/enable-pages-origin.sh
```

脚本保留 env 备份，设置 app 与 GitHub Pages 的准确来源，重建容器读取 env；不重建镜像，不修改供应商密钥。

## 域名与 Cookie

- app：CNAME 指向 `RuoXiao00.github.io`，Pages 的 Custom domain 设置为 `app.qiyuange.online`。
- api：A 记录指向 API 服务器，由 Nginx 配置 HTTPS 和 `http://127.0.0.1:18000` 反向代理。
- GitHub Pages 的自定义域名证书可用后启用 Enforce HTTPS。首次更换自定义域名后重新发布一次以更新资源基础路径。
- 图片历史及管理员登录使用 HttpOnly + Strict Cookie，通过同一主域名下的 app / api 访问。使用 github.io 原始地址时，Cookie 功能会提示切到项目域名。

参考：[GitHub 自定义域名文档](https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site/managing-a-custom-domain-for-your-github-pages-site)、[Cookie 属性](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Set-Cookie)。

## 验收

从个人电脑执行，而非仅在服务器内部测试：

```powershell
curl.exe --fail --max-time 15 https://api.qiyuange.online/api/knowledge/health
curl.exe -i --max-time 15 -H "Origin: https://app.qiyuange.online" https://api.qiyuange.online/api/knowledge/health
```

检查返回 JSON 和 `access-control-allow-origin: https://app.qiyuange.online`，以及 `access-control-allow-credentials: true`。浏览器中的真实请求同样要验证；单次成功不能说明所有网络路径均稳定。

app 前端页面可访问，不等于内地服务器上的 api 已免除备案要求。按阿里云的说明，中国内地云资源对外提供网站服务需要完成相应备案，域名与 SSL 配置不能替代该流程。[阿里云备案说明](https://help.aliyun.com/zh/icp-filing/basic-icp-service/user-guide/icp-filing-application-overview)

## 商品更新状态

每日推荐只读取后端快照，刷新页面不会触发生成。05:00 的更新失败时保留上期结果；失败后补试一次，仍失败等待下一期。

热门商品先读已保存的首屏，再获取最新商品及下一页。来源限制访问、验证码、超时属于采集失败，页面应显示说明并保留已有商品。排查服务器可先查看：

```bash
cd /www/kuajing-next
docker compose -f compose.baota.yaml ps
docker compose -f compose.baota.yaml logs --since 2h --tail 200 api
curl -fsS http://127.0.0.1:18000/api/recommendations/latest
```

最后一条仅读取快照。不要通过不断刷新或高频重跑增加商品来源压力。

## 知识库数据

源码仓库不含知识正文或向量库。小量新增资料可在 [管理员页面](https://app.qiyuange.online/#/admin) 登录上传 DOCX/PDF/TXT；已有库可按 [迁移说明](local-development.md#已有知识库迁移) 整体搬运，避免重新调用 Embedding。
