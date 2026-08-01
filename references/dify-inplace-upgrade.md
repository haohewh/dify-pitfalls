# Dify 就地升级工作流（1.3.1 → 1.15.0）

2026-07-13 首次尝试失败 → 2026-07-29 成功。升级是可行的，但需准备 DB 重置。

## 前提条件

```bash
docker images | grep 'dify-api.*latest'
# 确认 :latest 镜像已在本地
# 如果 :latest 不存在且 Docker Hub 不通 → 放弃升级
```

## 升级步骤

### 1. 备份

```bash
cd /opt/dify/docker
cp docker-compose.yaml docker-compose.yaml.bak
docker exec docker-db-1 pg_dump -U postgres dify > /tmp/dify_backup.sql
```

### 2. 改标签

```bash
sed -i 's|image: langgenius/dify-api:1.3.1|image: langgenius/dify-api:latest|g' docker-compose.yaml
sed -i 's|image: langgenius/dify-web:1.3.1|image: langgenius/dify-web:latest|g' docker-compose.yaml
grep 'langgenius/dify' docker-compose.yaml  # 验证
```

### 3. 启动新容器

```bash
docker compose stop api web worker nginx plugin_daemon
docker compose up -d api web worker plugin_daemon
# nginx 稍后处理（可能有端口冲突）
```

### 4. 等 DB 迁移

```bash
sleep 20
docker logs docker-api-1 --tail 30 2>&1 | grep -E 'migrat|error|success'
# 预期输出 20+ 条 "Running upgrade" 和最终 "Database migration successful!"
# 1.3.1 → 1.15.0 的迁移全部自动执行，无需干预
```

### 5. 处理 nginx（端口冲突核心）

Dify Docker nginx 和 Host nginx 都想要 443 端口。正确方案：

```bash
# a) 停 Docker nginx，让 Host nginx 先拿 443
docker compose stop nginx
systemctl restart nginx
# 验证：ss -tlnp | grep ':443 ' | grep nginx ← 应显示 host nginx

# b) Docker nginx 改到 4443
sed -i 's/EXPOSE_NGINX_SSL_PORT=443/EXPOSE_NGINX_SSL_PORT=4443/' /opt/dify/docker/.env
docker compose rm -sf nginx && docker compose up -d nginx
# 验证：docker-nginx-1 端口应为 8081->80, 4443->443
```

### 6. 初始化管理员（DB 需重置）

如果登录失败，DB 迁移可能不兼容。最干净的方案：删库重建。

```bash
# a) 重置 DB
docker exec docker-db-1 psql -U postgres -c "DROP DATABASE IF EXISTS dify WITH (FORCE);"
docker exec docker-db-1 psql -U postgres -c "CREATE DATABASE dify;"
docker restart docker-api-1
sleep 20

# b) init（获取 session cookie）
curl -c /tmp/cookies.txt -X POST http://127.0.0.1:8081/console/api/init \
  -H 'Content-Type: application/json' \
  -d '{"password":"starsower2026"}'

# c) setup（创建管理员）
curl -b /tmp/cookies.txt -X POST http://127.0.0.1:8081/console/api/setup \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@hdnz.net","name":"[作者]","password":"[REDACTED]"}'
# 如返回 500 → 修复权限后重试

# d) 登录验证（密码必须 base64）
PWD=$(echo -n '[REDACTED]' | base64 -w0)
curl -X POST http://127.0.0.1:8081/console/api/login \
  -H 'Content-Type: application/json' \
  -d "{\"email\":\"admin@hdnz.net\",\"password\":\"$PWD\"}"
```

### 7. 修复 privkeys 权限

```bash
# setup 报 "PermissionDenied at write => permission denied ... privkeys/.../private.pem"
chmod -R 777 /opt/dify/docker/volumes/app/storage/
# 重新走 init → setup
```

### 8. 旧镜像回收

```bash
docker rmi langgenius/dify-api:1.3.1 langgenius/dify-web:1.3.1
# 释放 ~2.6GB
```

## 关于密码 — 1.15.0 新变化

1.15.0 登录 API 加了 `@decrypt_password_field` 装饰器，要求密码 **Base64 编码**。不是真加密，只是前端混淆（`libs/encryption.py` 里就是 `base64.b64decode`）。浏览器前端自动处理，不影响 Web 使用。但 curl/API 调用时必须先 base64。

```bash
echo -n '[REDACTED]' | base64
# → aGRuejYzMjEwMA==
```

## 故障排查

| 症状 | 根因 | 修复 |
|------|------|------|
| `"Invalid encrypted data"` | 密码未 base64 | `echo -n pwd \| base64` 再发 |
| `setup` 500 `permission denied` | privkeys 目录权限 | `chmod -R 777 storage/` |
| nginx 启动失败 | 443 被 docker 占用 | 停 docker nginx → 启 host nginx → docker nginx 改 4443 |
| `Cannot query field "Vector_index_..."` | Weaviate 索引损坏 | 删文档重传（见 dify-ops-reference Bug25/28） |
| DB 迁移后登录 401 | 密码算法不兼容 | 删库重建 → init → setup |

## 回滚

```bash
cp docker-compose.yaml.bak docker-compose.yaml
docker compose down
docker compose up -d
# 注意：DB 迁移已执行，回滚后可能不兼容
# 最干净的恢复：用备份 SQL 重建 DB
```

## 关键教训

- DB 重建是最干净的恢复方式，不要试图修迁移
- Docker Hub 不通时，只要镜像在本地就能升级
- 升级后 nginx 端口冲突是必处理项
- 1.15.0 的 Dify Studio UI 变化较大，但 API 兼容 1.3.1
