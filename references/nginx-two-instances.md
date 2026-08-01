# Dify 部署架构：两套 Nginx 的区别

## 核心发现（2026-07-27）

example.com 有**两套独立的 Nginx**，绝对不能混淆：

| | 主机 Nginx | Docker Nginx |
|--|-----------|-------------|
| 端口 | 80（主机） | 8081（docker-proxy 映射） |
| 配置路径 | `/etc/nginx/` | `docker exec docker-nginx-1 cat /etc/nginx/conf.d/default.conf` |
| 管理命令 | `nginx -s reload`（主机） | `docker exec docker-nginx-1 nginx -s reload` |
| 进程用户 | `nginx`（主机用户） | root（容器内） |

## 路由链

```
外网访问 example.com
    ↓ 端口 80
主机 Nginx（/etc/nginx/conf.d/example.com.v2.conf）
    ↓ proxy_pass http://127.0.0.1:8081/
Docker Nginx（容器内，端口8081）
    ↓ proxy_pass http://172.19.0.6:3000（docker-web-1）
Docker Web（Next.js，前端）
    ↓
Docker API（端口5001）
```

## 关键教训

1. **主机 nginx 的配置在 `/etc/nginx/`**，不是容器里
2. **Docker nginx 的配置在容器里**，用 `docker exec ... cat ...` 查看
3. **重启主机 nginx**：`nginx -s reload`（不用 docker）
4. **重启 Docker nginx**：`docker exec docker-nginx-1 nginx -s reload`

## Bug: web:3000 主机名解析失败

**症状**：example.com 返回 404 或空白

**排查**：
```bash
# 1. 查 docker-web-1 的实际 IP（不是猜测）
docker inspect docker-web-1 --format "{{json .NetworkSettings}}" | python3 -c "import sys,json; nets=json.load(sys.stdin); [print(k) for k in nets]"

# 2. 确认监听地址
docker exec docker-web-1 ss -tlnp
# 输出：tcp  0  0  172.19.0.6:3000  0.0.0.0:*  LISTEN  7/node

# 3. 从 docker-nginx-1 内部测试能否连通
docker exec docker-nginx-1 wget -q -O- http://172.19.0.6:3000
# 如果返回 HTML 说明 web 正常，nginx 配置问题

# 4. 如果 web 正常但外网 404 → 主机 nginx 配置问题
# 检查 /etc/nginx/conf.d/example.com.v2.conf 里的 location / 路由
```

**修复**：nginx 配置里用实际容器 IP，不用 hostname：
```nginx
# 错误（hostname 解析不到）
location / { proxy_pass http://web:3000; }

# 正确（用实际 IP）
location / { proxy_pass http://172.19.0.6:3000; }
```

## 外部nginx必须单独路由 /console/api

外部nginx的 `location /` 会把所有请求代理到 `127.0.0.1:8081`（docker-nginx），但 docker-nginx 里 `/console/api` 路由正确不代表外部nginx能看到。**外部nginx必须在 `/console/api` 路由上单独配置**：

```nginx
# 外部nginx /etc/nginx/conf.d/example.com.v2.conf 里添加：
location /console/api {
    proxy_pass http://127.0.0.1:8081/console/api;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
}
```

否则 `/console/api` 请求会走 `location /` → docker-nginx → Next.js web容器 → 404。

## 外部nginx完整路由示例（2026-07-27实测）

```nginx
server {
    listen 443 ssl;
    server_name example.com;

    # Dify console API - 必须单独路由，走 API 服务
    location /console/api {
        proxy_pass http://127.0.0.1:8081/console/api;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # Dify Web - 走 docker-nginx
    location / {
        proxy_pass http://127.0.0.1:8081/;
        proxy_set_header Host $host;
    }
    location /_next/ { proxy_pass http://127.0.0.1:8081/_next/; }
    location = /apps { proxy_pass http://172.19.0.6:3000; proxy_set_header Host $host; }
    location /apps/ { proxy_pass http://172.19.0.6:3000; proxy_set_header Host $host; }
    location /console/ { proxy_pass http://127.0.0.1:8081/; proxy_set_header Host $host; }
}
```

## Dify API 内部访问

Dify API 在 Docker 内部监听 `172.19.0.9:5001`：
```bash
# 从服务器主机测（用 Docker 网络）
curl -s http://172.19.0.9:5001/health

# 从 docker-api-1 内部测
docker exec docker-api-1 wget -q -O- http://localhost:5001/health
```
