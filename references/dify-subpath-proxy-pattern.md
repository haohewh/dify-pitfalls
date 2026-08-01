# Dify 移至 Nginx 子路径前缀模式（ENHANCED 方案）

**场景**：把 Dify（Next.js 应用 + Docker nginx）从域名根路径迁移到 `/dify/` 子路径，主页恢复为静态门户页面。

## 三个核心冲突

Dify 的 Next.js SPA 有三层路径问题：

### 1. 服务端 3xx 重定向
未登录用户访问 `/dify/` → Dify Next.js 返回 307 `Location: /auth/refresh?...`（根级路径）
浏览器跟随 → `example.com/auth/refresh?...` → 无对应 nginx 路由 → 404

### 2. 客户端 SPA 导航
前端 JS 读取 `data-base-path` 属性（SSR HTML 中）决定所有客户端路由的基路径。默认空字符串 = `/`。
登录成功后 JS 执行 `router.push('/')` → 浏览器跳到主页 → 不是 Dify

### 3. SSR 路径暴露层级
Dify web 容器 env `CONSOLE_API_URL=https://example.com/console` 硬编码 API 地址，
必须保留 `/console/`、`/_next/`、`/v1/`、`/files/` 在根级。

## ✅ 三层同时修复

### 第1层：proxy_redirect — 重写3xx重定向Location

```nginx
location /dify/ {
    proxy_redirect ~^(https?://[^/]+)?(/.*) /dify$2;
}
```

正则匹配两种格式：
- 相对路径 `/auth/refresh?redirect_url=%2F` → `/dify/auth/refresh?redirect_url=%2F`
- 绝对路径 `https://example.com/auth/refresh?redirect_url=%2F` → `/dify/auth/refresh?redirect_url=%2F`

### 第2层：sub_filter — 改写SPA基路径

```nginx
location /dify/ {
    sub_filter_once off;
    sub_filter_types text/javascript;
            sub_filter 'data-base-path=""' 'data-base-path="/dify"';
}
```

`sub_filter_types text/javascript` 是**关键**：Dify Next.js 把配置也嵌入到 `<script>` 标签的 RSC 负载中。
没有 `text/javascript`，HTML `<body>` 的 `data-base-path` 改了但 RSC 里的没改 → JS 仍读空字符串。

### 第3层：根级SSR路径兜底（安全网）

```nginx
location /signin    { proxy_pass http://127.0.0.1:8081; }
location /auth/     { proxy_pass http://127.0.0.1:8081; }
location /install   { proxy_pass http://127.0.0.1:8081; }
location /reset-password { proxy_pass http://127.0.0.1:8081; }
```

任何未被 proxy_redirect 捕获的 SSR 重定向落到根级时仍有 Dify 页面。

## 完整 nginx 配置

```nginx
location = /dify { return 302 /dify/; }
location /dify/ {
    proxy_pass http://127.0.0.1:8081/;
    proxy_set_header Host $host;
    proxy_read_timeout 3600s;

    # 第1层：重写所有3xx重定向的 Location 头
    proxy_redirect ~^(https?://[^/]+)?(/.*) /dify$2;

    # 第2层：改写 SPA 基路径（含 RSC 负载）
    sub_filter_once off;
    sub_filter_types text/javascript;
            sub_filter 'data-base-path=""' 'data-base-path="/dify"';
}

# 第3层：Dify SSR 内部路由根级兜底
location /signin    { proxy_pass http://127.0.0.1:8081; proxy_set_header Host $host; }
location /auth/     { proxy_pass http://127.0.0.1:8081; proxy_set_header Host $host; }
location /install   { proxy_pass http://127.0.0.1:8081; proxy_set_header Host $host; }
location /reset-password { proxy_pass http://127.0.0.1:8081; proxy_set_header Host $host; }

# Dify API 路由（web 容器 SSR 调用，保留根级）
location /console/ { proxy_pass http://127.0.0.1:8081/; proxy_set_header Host $host; proxy_read_timeout 3600s; }
location /_next/ { proxy_pass http://127.0.0.1:8081/_next/; proxy_set_header Host $host; }
location /files/ { proxy_pass http://127.0.0.1:8081/files/; proxy_set_header Host $host; }
location /v1/ { proxy_pass http://127.0.0.1:8081/v1/; proxy_set_header Host $host; proxy_read_timeout 3600s; }

# 主页（精确匹配，优先级最高）
location = / { root /opt/example; index index.html; }

# 兜底
location / { root /opt/example; index index.html; }
```

## 验证命令

```bash
# 1. 重定向链是否锁在 /dify/ 下
curl -skL -o /dev/null -w '%{url_effective}\n' https://example.com/dify/
# 期望: https://example.com/dify/signin?redirect_url=%2F

# 2. data-base-path 改写
curl -skL https://example.com/dify/ | grep -o 'data-base-path="[^"]*"'
# 期望: data-base-path="/dify"  （且只出现一次）

# 3. RSC 负载中的 base-path 也改写了
curl -skL https://example.com/dify/ | sort -u | grep 'data-base-path'
# 期望: 只有 data-base-path="/dify"，没有 data-base-path=""

# 4. 全量路由验证
for u in / /dify/ /signin /console/api/system-features /xhxc/ /xsyq/; do
  curl -skL -o /dev/null -w "$u → %{http_code}\n" "https://example.com$u"
done
# / → 200, /dify/ → 200, /signin → 200, /console/... → 200, etc.
```

## Pitfalls

| 坑 | 表现 | 解决 |
|----|------|------|
| 漏了 `text/javascript` | RSC 负载仍有 `data-base-path=""`，JS 跳到根 | 加 `sub_filter_types text/javascript;` |
| `proxy_redirect` 使用简单字符串 `/` | 只匹配绝对路径首 `/`，URL 含 host 时乱序 | 用正则 `~^(https?://[^/]+)?(/.*) /dify$2` |
| 浏览器缓存旧 Service Worker | 旧的 Dify 根级 SW 拦截导航，跳到 `/signin` | 开无痕窗口测试 |
| `location = /` 在 `location /` 后 | 精确匹配被 prefix 匹配抢了，主页还是 Dify | `location = /` 必须在前 |
| `add_header Content-Type text/plain` 与 `types` 冲突 | nginx 警告 `duplicate MIME type text/html` | 不用管（只是 warning，不影响功能）|
