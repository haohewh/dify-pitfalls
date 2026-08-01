# Dify 自定义 basePath 镜像构建

## 背景

Dify 的 Next.js 前端 `NEXT_PUBLIC_BASE_PATH` 在构建时编译进 JS 和中间件，运行时改 env 无效。直接 patch 容器内文件也不完整（中间件配置硬编码）。唯一可靠的方案是重新构建 Docker 镜像，编译时写入 `/dify` 前缀。

## 标准操作流程

### 第1步：创建 Dockerfile

```dockerfile
FROM langgenius/dify-web:latest

# Patch 服务端和中间件的 basePath
RUN find /app/targets/next/web/.next -name "*.js" -path "*/server/*" \
    -exec sed -i 's/NEXT_PUBLIC_BASE_PATH:"",/NEXT_PUBLIC_BASE_PATH:"\\/dify",/g' {} + \
    -exec sed -i 's/basePath:"",/basePath:"\\/dify",/g' {} +

# Patch 静态 JS（客户端读取 data-base-path 属性，但构建时也写了备用值）
RUN find /app/targets/next/web/.next/static -name "*.js" \
    -exec sed -i 's|NEXT_PUBLIC_BASE_PATH:""|NEXT_PUBLIC_BASE_PATH:"/dify"|g' {} +

# Patch JSON 配置文件
RUN find /app/targets/next/web/.next -name "*.json" \
    -exec sed -i 's|"basePath":""|"basePath":"/dify"|g' {} +

CMD ["node", "targets/next/web/server.js"]
```

### 第2步：构建镜像

```bash
docker build -f Dockerfile.dify -t dify-web-basepath:latest .
```

### 第3步：更新 docker-compose

```yaml
# 备份原 compose
cp /opt/dify/docker/docker-compose.yaml /opt/dify/docker/docker-compose.yaml.bak

# 改镜像名
sed -i 's|image: langgenius/dify-web:latest|image: dify-web-basepath:latest|' /opt/dify/docker/docker-compose.yaml
```

### 第4步：替换线上容器

```bash
docker compose -f /opt/dify/docker/docker-compose.yaml up -d web
```

### 第5步：验证

```bash
# 1. 容器正常启动
docker logs docker-web-1 --tail 5
# 期望：▲ Next.js 16.2.9 / ✓ Ready in 0ms

# 2. nginx 代理正常
curl -skL -o /dev/null -w '%{http_code} %{url_effective}\n' https://example.com/dify/
# 期望：200 https://example.com/dify/signin?...

# 3. data-base-path 正确（编译进镜像，不需 sub_filter）
curl -skL https://example.com/dify/ 2>&1 | grep -o 'data-base-path="[^"]*"'
# 期望：data-base-path="/dify"
```

## 关键原理

Dify 的 `@t3-oss/env-nextjs` 在服务端读取 `NEXT_PUBLIC_BASE_PATH` 源码为 `""`（硬编码在 `experimental__runtimeEnv` 中），客户端从 `document.body.dataset.basePath` 读取。但中间件配置中的 `basePath` 也是编译时写入的。因此：

- ❌ 运行时 env 变量无效（`NEXT_PUBLIC_*` 编译进 JS 包）
- ❌ docker exec sed 改容器不够（容器重启后丢失）  
- ❌ nginx sub_filter 不够（服务端跳转控制不住）
- ✅ 从原镜像再构建、sed patch 后存为新镜像（编译时覆盖）

## 与 nginx sub_filter 的比较

| 方式 | 服务端跳转 | 客户端路由 | 持久性 | 复杂度 |
|------|-----------|-----------|--------|--------|
| nginx sub_filter + proxy_redirect | ❌ 漏掉服务端跳转 | ✅ 可改 data-base-path | ✅ 持久 | 高（反复调试） |
| **Docker rebuild + sed patch** | ✅ 全路径认 /dify/ | ✅ 原生 basePath | ✅ 持久 | 低（一次构建） |

## 注意事项

- 新镜像约 693MB（比原 571MB 大，因为多了 RUN 层）
- Dockerfile patching 只在服务器上执行，不需要克隆 Dify 源码
- 如果以后 Dify 官方更新了 `:latest` 镜像，需要用新版本重新构建
