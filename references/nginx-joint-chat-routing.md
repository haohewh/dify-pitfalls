# 外部Nginx路由顺序陷阱：/api/joint-chat 路由覆盖（2026-07-28三重根因全修复）

## 问题现象
- 联合咨询前端 `https://example.com/xhxc/lhzx` 发送"网络错误，请重试"
- Starsower_v2 的 `/api/joint-chat` API 实际返回 405 或 404

## 三重根因，必须同时修

### 根因1：前端相对路径
```javascript
// lhzx.html 错误写法
fetch('api/joint-chat', ...)   // 相对路径 → /xhxc/api/joint-chat ❌

// 正确写法
fetch('/api/joint-chat', ...)  // 绝对路径 → /api/joint-chat ✅
```
修复：`sed -i "s|fetch('api/joint-chat')|fetch('/api/joint-chat')|g" /opt/myapp/templates/lhzx.html`

### 根因2：后端字段名不匹配
前端发 `ids`，后端读 `avatar_ids` — 字段名对不上导致400
修复：joint.py 里 `avatar_ids = data.get("avatar_ids") or data.get("ids", [])`

### 根因3：外部nginx路由顺序
`/api/` 通用路由代理到Dify，Starsower_v2的 `/api/joint-chat` 被漏掉
修复：nginx配置里 `/api/joint-chat` 必须写在 `/api/` 通用路由**之前**

## 完整修复步骤

### Step 1：修复前端相对路径
```bash
sed -i "s|fetch('api/joint-chat')|fetch('/api/joint-chat')|g" /opt/myapp/templates/lhzx.html
```

### Step 2：修复后端字段名
```bash
sed -i 's/avatar_ids = data.get("avatar_ids", \[\])/avatar_ids = data.get("avatar_ids") or data.get("ids", \[\])/' /opt/myapp/routes/joint.py
# ⚠️ 改完必须 kill -9 旧进程重启！
```

### Step 3：修复nginx配置
在 `/etc/nginx/conf.d/example.com.v2.conf` 里，`/api/joint-chat` 写在 `/api/` 之前：

```
# Starsower_v2 特定API（必须写在 /api/ 通用路由之前）
location /api/joint-chat { proxy_pass http://127.0.0.1:8001/api/joint-chat; proxy_set_header Host $host; }
location /api/admin/      { proxy_pass http://127.0.0.1:8001/api/admin/;  proxy_set_header Host $host; }

# Dify 通用API路由
location /api/           { proxy_pass http://127.0.0.1:5000/api/;          proxy_set_header Host $host; }
```

⚠️ 写到 server{} 外面会报 `location directive is not allowed here`，需要整文件重写。

## 已知工作的完整nginx配置片段
```
server {
    listen 443 ssl;
    server_name example.com www.example.com;
    ssl_certificate /etc/letsencrypt/live/example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/example.com/privkey.pem;

    location /api/joint-chat { proxy_pass http://127.0.0.1:8001/api/joint-chat; proxy_set_header Host $host; }
    location /api/admin/      { proxy_pass http://127.0.0.1:8001/api/admin/;  proxy_set_header Host $host; }
    location /api/           { proxy_pass http://127.0.0.1:5000/api/;          proxy_set_header Host $host; }
    location /xhxc/         { proxy_pass http://127.0.0.1:8001/;              proxy_set_header Host $host; }
    location / {
        proxy_pass http://127.0.0.1:8081/; proxy_set_header Host $host; proxy_read_timeout 3600s;
    }
}
```

## 验证
```bash
curl -s -X POST "https://example.com/api/joint-chat" \
  -H "Content-Type: application/json" \
  -d '{"ids":[1,2],"message":"右手腕疼痛怎么办","user_id":"test"}'
# 期望：返回JSON含reply字段，无网络错误
```
