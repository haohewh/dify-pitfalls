# 混合检索「权重设置」检索不到 vs Rerank 模式正常 — 根因调查（2026-07-31）

## 现象

Dify 1.16.1，知识库检索设置：
- 选「权重设置」(weighted_score) → 检索不到知识库内容
- 选「Rerank 模型」→ 正常检索到

且向量链路完全健康：Weaviate 1.27.0 ✅、磁盘 61% ✅、无 READONLY ✅、分段全部向量化 ✅、worker 无 embedding 错误 ✅。

## 实测根因（数据库直查）

`datasets.retrieval_model` JSON 的 `weights.vector_setting` 在部分知识库为**空值**：

```sql
-- 老师甲经验1: embedding_model_name=text-embedding-v3, embedding_provider_name=langgenius/tongyi/tongyi ✅
-- 老师甲经验2: embedding_model_name=''  ❌
-- 老师甲经验3: embedding_model_name=''  ❌
SELECT name,
       retrieval_model::json->'weights'->'vector_setting'->>'embedding_model_name' AS emb_model,
       retrieval_model::json->'weights'->'vector_setting'->>'embedding_provider_name' AS emb_provider
FROM datasets ORDER BY name;
```

**原理**：weighted_score 模式由 Dify 的 WeightRerankRunner 计算混合分数，依赖 weights 里配置的 embedding 模型信息。该字段为空 → 向量分支分数算不出 → 加权结果为空。Rerank 模式走独立 reranking_model（qwen3-rerank）重排，不依赖 weights，故正常。

## 相关 GitHub Issue

| # | 标题 | 要点 |
|---|------|------|
| [14973](https://github.com/langgenius/dify/issues/14973) | No Results When Using Weight Settings in Hybrid Search | 权重 0.7/0.3 + topK10 无阈值 → 空结果；换 reranker 正常；报错 `shapes (768,) and (384,) not aligned`（embedding 维度不匹配） |
| [31215](https://github.com/langgenius/dify/issues/31215) | IRIS hybrid search returns 0 results | WeightRerankRunner 依赖 `metadata["score"]`（weight_rerank.py:178-179），全文检索源不返回 score → 所有文档被过滤 |
| [13426](https://github.com/langgenius/dify/issues/13426) | impossible to setup KB hybrid weighted_score by API | **前端逻辑**（web/app/components/workflow/nodes/knowledge-retrieval/utils.ts）：全部数据集 high quality + 内部 + embedding 模型一致 → 默认 WeightedScore；否则回退 RerankingModel。`reranking_mode` 和 `weights` 参数未文档化 |
| [8854](https://github.com/langgenius/dify/issues/8854) | Knowledge Retrieval Node reverts to RerankModel | 前端 draft API 偶发丢失 reranking_mode/weights 字段 → 配置回退 RerankModel |
| [25084](https://github.com/langgenius/dify/issues/25084) | search_method conflicts with Knowledge settings | Economy 模式建库却用 semantic_search → `Cannot query field "Vector_index_xxx_Node"` |
| [27291](https://github.com/langgenius/dify/issues/27291) | KB not usable after upgrade | Weaviate 升级后旧知识库向量索引不可用：`does not have named vector default configured` |

## 完整诊断顺序（排除向量链路 → 查配置）

1. `docker inspect docker-weaviate-1 --format '{{.Config.Image}}'` — 1.16.1 需 ≥1.27.0
2. `df -h /` — 磁盘 <80%，否则 Weaviate READONLY
3. `docker logs docker-weaviate-1 2>&1 | grep READONLY`
4. `docker logs docker-api-1 2>&1 | grep 'Vector_index\|Cannot query'` — schema 查询 200 = 正常
5. 分段向量化检查（见 SKILL.md Bug39 诊断 SQL）
6. `docker logs docker-worker-1 2>&1 | grep -i error` — embedding 错误
7. 以上全健康 → 查 weights 配置（Bug39 SQL）

## 修复方案

```sql
-- 以老师甲经验1 为模板补齐（jsonb_set 改 JSON，然后重启 docker-api-1）
UPDATE datasets
SET retrieval_model = jsonb_set(
        retrieval_model::jsonb,
        '{weights,vector_setting,embedding_model_name}',
        '"text-embedding-v3"'
    )
WHERE name = '<知识库名>';
```

## 经验教训

- **文档状态 completed ≠ 检索配置正常**。向量写入了，但检索配置（weights）可能是坏的。
- **权重设置和 Rerank 是两条独立打分链路**：权重模式对配置敏感，Rerank 模式更鲁棒。遇到"权重不行 Rerank 行"先查 weights 配置，别一上来就重建知识库。
- 同一次建库的不同知识库，retrieval_model JSON 可能不一致（经验1 有 embedding 配置，经验2/3 没有）——多知识库环境必须逐个查。
