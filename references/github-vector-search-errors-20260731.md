# GitHub Issue 调查: 高质量建库但向量/混合检索报错

**调查日期**: 2026-07-31
**搜索工具**: GitHub REST API (匿名, 60 req/h)

## 最相关的 Issue

### [#25084 — search_method conflicts with Knowledge settings](https://github.com/langgenius/dify/issues/25084)

**场景**: 知识库用 Economy 模式建库 → API 仍返回 search_method="semantic_search" → 调向量检索时报错。

**错误信息**:
```
Cannot query field "Vector_index_06208a9f_0bf6_451b_8c7f_eccfdbda8018_Node"
on type "GetObjectsObj". Did you mean "Vector_index_82a8fad2_05b1_41de_823b_a9dcb9a54b47_Node", ...
```

**根因**: 向量不存在时调向量检索的典型报错。即使是高质量模式，如果向量没写进去（Worker 失败/Weaviate 不兼容），表现形式一样。

**结论**: Dify Bug — Economy 模式创建的 knowledge 不应允许选择 semantic_search/hybrid_search。

---

### [#27291 — Knowledge created in versions prior to 1.9.1 is not usable after upgrading to 1.9.2](https://github.com/langgenius/dify/issues/27291)

**场景**: Dify 升级后 Weaviate 版本兼容问题，现有知识库无法检索。

**错误信息**:
```
Query call with protocol GRPC search failed with message extract target vectors:
class Vector_index_b7ff402a_fea1_44f5_bed3_c26f5e25a369_Node does not have
named vector default configured. Available named vectors map[].
```

**根因**: Weaviate 版本升级后 collection schema 变化，旧知识库的向量索引名与新版本不匹配。

**结论**: Dify 升级时必须同步检查 Weaviate 版本兼容性（1.16.1 需要 Weaviate ≥1.27.0）。

---

### [#34588 — Knowledge Retrieval node returns [] after v1.13.x update](https://github.com/langgenius/dify/issues/34588)

**场景**: HQ-HYBRID + reranker + metadata filter, 召回测试正常，但 Workflow 中 Knowledge Retrieval 节点大部分时间返回空。

**根因**: 可能是 score_threshold 过高 + 混合检索的分数计算方式导致结果被过滤。与 UI 直接报错不同，属于静默失败。

---

## 诊断 SQL

```sql
-- 检查知识库所有分段的向量索引状态
SELECT ds.name AS dataset,
       COUNT(*) AS total_segs,
       SUM(CASE WHEN s.index_node_id IS NOT NULL THEN 1 ELSE 0 END) AS indexed_segs,
       SUM(CASE WHEN s.index_node_id IS NULL THEN 1 ELSE 0 END) AS missing_vector_segs
FROM datasets ds
JOIN document_segments s ON s.dataset_id = ds.id
WHERE ds.name = '<知识库名称>'
GROUP BY ds.name;

-- 检查文档索引状态
SELECT d.name, d.indexing_status, d.error,
       (SELECT COUNT(*) FROM document_segments s WHERE s.document_id = d.id) AS seg_count
FROM documents d
WHERE d.dataset_id = '<知识库ID>'
ORDER BY d.created_at DESC;
```

## 排查优先级

1. `docker inspect docker-weaviate-1 --format '{{.Config.Image}}'` — 检查版本
2. `docker logs docker-weaviate-1 --tail 20 2>&1 | grep -i 'READONLY\\|disk\\|90'` — 检查磁盘
3. `docker logs docker-worker-1 --tail 20 2>&1 | grep -i 'weaviate\\|embedding\\|error'` — 检查 Worker
4. 查 `document_segments.index_node_id` — 确认向量是否真的写进去了
