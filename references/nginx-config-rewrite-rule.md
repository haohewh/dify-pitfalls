# Nginx 配置操作铁律

## 核心原则：永远重写，不追加

修改 nginx 配置文件（如 `/etc/nginx/conf.d/example.com.v2.conf`）时，**必须重写整个文件**，禁止用 `sed -i 'Na content' file` 追加行。

### 错误做法（会导致配置损坏）
```bash
# 危险：数字行号会漂移，追加位置不可控
sed -i '54i\    location /api/joint-chat {...}' /etc/nginx/conf.d/example.com.v2.conf

# 危险：写到 server{} 闭合括号之后
grep -n 'location /api/' file.conf  # 查到第54行
sed -i '54a ...' file.conf          # sed的54行 ≠ nginx配置的54行
```

**症状**：`nginx -t` 报错 `"location" directive is not allowed here`

**根因**：nginx 配置文件里的空行、注释行、嵌套结构导致 sed 行号与实际配置位置错位

### 正确做法
```bash
cat > /etc/nginx/conf.d/example.com.v2.conf << 'EOF'
server {
    listen 443 ssl;
    ...
    # 路由顺序：精确路径在前，通用路径在后
    location /api/joint-chat { proxy_pass http://127.0.0.1:8001/api/joint-chat; proxy_set_header Host $host; }
    location /api/admin/      { proxy_pass http://127.0.0.1:8001/api/admin/;  proxy_set_header Host $host; }
    location /api/            { proxy_pass http://127.0.0.1:5000/api/;          proxy_set_header Host $host; }
    ...
}
EOF
nginx -t && systemctl reload nginx
```

### nginx location 匹配规则
- 精确匹配优先：`location /api/joint-chat` 优先于 `location /api/`
- 前置声明的精确路由不会被后续通用路由覆盖
- 所以 `/api/joint-chat` 必须写在 `location /api/` **之前**

### 修改前备份
```bash
cp /etc/nginx/conf.d/example.com.v2.conf /etc/nginx/conf.d/example.com.v2.conf.bak_$(date +%Y%m%d%H%M)
```
