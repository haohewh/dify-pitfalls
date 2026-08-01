# mem0 2.0.14 使用经验 + 记忆评分/反思升级（2026-08-01 实测）

## mem0 2.0.14 API 变化（与旧版差异巨大，照旧文档写必踩坑）

**add** 签名：`add(messages, *, user_id=None, agent_id=None, run_id=None, metadata=None, timestamp=None, infer=True, ...)`
- messages 是 `[{"role": "user", "content": "..."}]` 列表
- `metadata` 里**所有值必须是字符串**（int/float 报 pydantic `Input should be a valid string`）：
  ```python
  metadata={"importance": str(score), "created_at": str(time.time())}
  ```

**search** 签名：`search(query, *, top_k=20, filters=None, threshold=0.1, rerank=False, ...)`
- ❌ 旧版 `search(query, user_id=..., limit=...)` → 报 `Top-level entity parameters frozenset({'user_id'}) are not supported in search(). Use filters={'user_id': '...'} instead`
- ✅ 正确：`search(query, top_k=N, filters={"user_id": uid})`（**参数名是 top_k 不是 limit**）
- `filters` 必须含 user_id/agent_id/run_id 至少一个（空 filters 报错）
- **query 不能为空**（`Invalid query: cannot be empty or whitespace-only`）——聚合/列举记忆要用宽泛词（如"用户 最近 记忆"）或 get_all

**embedding 配置**（国内环境关键）：
- mem0 默认 huggingface embedder 需要 `sentence_transformers` + 下载模型（国内超时）→ **改用百炼 API**：
  ```python
  MEM0_CONFIG["embedder"] = {
      "provider": "openai",
      "config": {"api_key": "<百炼key>", "model": "text-embedding-v3",
                 "openai_base_url": "https://ws-xxx.maas.aliyuncs.com/compatible-mode/v1",
                 "embedding_dims": 1024}}
  ```
- 对应 qdrant `embedding_model_dims` 必须改 **1024**（text-embedding-v3 维度）；**qdrant 已有旧 collection（如 384 维）必须删掉重建**（`rm -rf data/mem0/qdrant`），否则检索报 `shapes (0,384) and (1024,) not aligned`
- 百炼 embedding 验证：`curl -X POST <compatible-mode>/embeddings -d '{"model":"text-embedding-v3","input":["测试"]}'` → data[0].embedding 长度 1024

## ⚠️ mem0 检索稳定性（重要决策记录）

mem0 2.0.14 + qdrant 本地 + 百炼 embedding 组合**检索结果不稳定**（同 session add 后 search 命中，跨进程/new user 常返回 0 条，原因未完全定位——filter 匹配/LLM 提取时序都疑似）。**调试超过 3 轮后按 Reflexion 原则退**：把同样的"评分+反思"升级做在**已稳定工作的 sqlite_memory 渠道**（见下），mem0 保留"可用则用 + 失败静默降级 NoOp"。

## 经验平台 sqlite_memory 记忆升级（Generative Agents 机制落地，2026-08-01 上线）

生产路径 `/opt/myapp/services/sqlite_memory.py`，全部 SQLite 无外部依赖：

1. **importance 启发式评分**（不调 LLM，零成本）：
   - 偏好词（我喜欢/我今年/我是/我家人等）→ +3；健康词（疼/失眠/膝盖/按揉等）→ +2；长文本(>80字) → +1；基础 3 分，上限 10
2. **remember 存 importance**：`ALTER TABLE user_memories ADD COLUMN importance INTEGER DEFAULT 3`（执行一次）
3. **recall 加权召回**：query 分词（`re.findall(r"[\u4e00-\u9fa5]{2,}", query)`）构造 LIKE 子句 → `ORDER BY (importance * 2) DESC, id DESC`（相关词命中优先，无命中退回最近 N 条）
4. **reflect 反思画像**：LLM 聚合最近 15 条记忆 → 生成用户画像（"55岁，膝盖疼痛一月..."）→ 写 `users.profile.summary`；chat.py 每 20 条用户消息触发一次

**连带修复的隐藏 bug**：`_get_llm()` 返回 `(api_key, base_url)` 但 `summarize()` 硬编码 `model="deepseek-v4-flash"`——app_settings 配了百炼 base_url 后模型名不匹配 → 摘要永远失败退化为 `text[:80]`。修复：`_get_llm` 返回三元素 `(api_key, base_url, model)`，model 从 app_settings `llm_model` 读。**经验平台所有 LLM 调用（mem0 提取/摘要/反思）统一走 app_settings 的 `llm_api_key/llm_base_url/llm_model`（百炼 qwen3.7-flash），不再硬编码 deepseek。**

## 关键文件
- 经验平台 mem0 封装：`/opt/myapp/services/memory.py`（MemoryService + _NoOpMemoryService 降级）
- SQLite 记忆：`/opt/myapp/services/sqlite_memory.py`（remember/recall/reflect/update_profile）
- mem0 LLM 配置来源：SQLite `app_settings` 表 key `llm_api_key/llm_base_url/llm_model`（INSERT OR REPLACE 即生效，无需重启）
