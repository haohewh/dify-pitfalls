# Weaviate 版本升级指南

## 什么时候需要升级

| Dify 版本 | 最低 Weaviate 版本 | 检查命令 |
|-----------|-------------------|---------|
| ≤1.14.x | 1.19.0 | `docker inspect docker-weaviate-1 --format '{{.Config.Image}}'` |
| ≥1.15.0 | 1.24.0 | 同上 |
| ≥1.16.0 | **1.27.0** | 同上 |
| ≥2.0.0 | 1.28.0+ | 同上 |

## 升级失败场景

### 场景1：文档上传后状态"错误"或"排队中"
Worker 日志报：
```
weaviate.exceptions.WeaviateStartUpError: Weaviate version 1.19.0 is not supported.
Please use Weaviate version 1.27.0 or higher.
```
**所有 embedding 操作完全不可用**，不修的话知识库等于废了。

### 场景2：已有文档可以检索但新文档索引失败
降级或跨版本升级时，Weaviate 数据格式不兼容但旧数据还能读。此时新文档 embedding 全部失败。

## 升级步骤

```bash
# 1. 查当前版本
docker inspect docker-weaviate-1 --format '{{.Config.Image}}'

# 2. 拉目标版本
docker pull semitechnologies/weaviate:1.27.0

# 3. 改 docker-compose.yaml
sed -i 's|image: semitechnologies/weaviate:1.19.0|image: semitechnologies/weaviate:1.27.0|g' /opt/dify/docker/docker-compose.yaml

# 4. 重建容器
docker compose -f /opt/dify/docker/docker-compose.yaml stop weaviate worker
docker compose -f /opt/dify/docker/docker-compose.yaml rm -f weaviate
docker compose -f /opt/dify/docker/docker-compose.yaml up -d weaviate worker

# 5. 验证
docker logs docker-weaviate-1 2>&1 | tail -3
# 应有 "prefilled vector cache" 日志（数据兼容）
docker logs docker-worker-1 2>&1 | grep -i migration
# 应有 "Database migration successful"
```

## 数据兼容性

同一主版本线（1.x → 1.x）升级：**数据自动兼容**，无需重建。

跨主版本线（1.x → 2.x）：**需要迁移**，旧数据需导出再导入。

## 预防

每次 Dify 升级后必须检查的 3 个容器版本：
1. `docker inspect docker-weaviate-1` — 向量库
2. `docker inspect docker-db-1` — PostgreSQL
3. `docker inspect docker-redis-1` — Redis
