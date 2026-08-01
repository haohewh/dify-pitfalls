# 分身上线链路检查清单（2026-07-31 实测：老师甲从"未配置"到全通）

**现象**：example.com/xhxc 问 AI 分身，返回"（老师经验库尚未配置，请等待管理员更新。）"或通用话术（不引知识库）。

## 三环检查法（按顺序）

### 环1：Dify Token 是否写入 SQLite
```bash
sqlite3 /opt/myapp/soulfire_v2.db "SELECT key, value FROM app_settings WHERE key LIKE 'dify_token%';"
# 空 = 未配置 → 从 Dify Studio 生成 API Key 写入：
sqlite3 /opt/myapp/soulfire_v2.db "INSERT OR REPLACE INTO app_settings (key, value) VALUES ('dify_token_老师甲', 'app-xxx');"
# ⚠️ key 名必须 = dify_token_{avatar_name}，avatar 名与 avatars 表完全一致
```
API Key 生成（无界面操作时）：`POST /console/api/apps/{app_id}/api-keys`（1.16.1，cookie+CSRF 认证）
验证 Key 直连：`curl -X POST http://127.0.0.1:8081/v1/chat-messages -H "Authorization: Bearer app-xxx" -d '{"query":"...","response_mode":"blocking","user":"test","inputs":{}}'`

### 环2：App 的 pre_prompt 必须有 {{#context#}}
```sql
SELECT (pre_prompt LIKE '%#context#%') AS has_context FROM app_model_configs WHERE app_id='<app_id>' ORDER BY created_at DESC LIMIT 1;
-- f = 缺变量 → 修复：
UPDATE app_model_configs SET pre_prompt = '{{#context#}}\n\n' || pre_prompt WHERE app_id='<app_id>';
docker restart docker-api-1
```
没有 {{#context#}} → 检索执行了（日志有 Weaviate 查询）但结果不注入模型 → 模型凭记忆答通用话术。

### 环3：知识库检索参数
```sql
SELECT retrieval_model::jsonb->>'score_threshold', retrieval_model::jsonb->>'top_k',
       retrieval_model::jsonb->>'score_threshold_enabled', retrieval_model::jsonb->>'search_method'
FROM datasets WHERE id='<ds_id>';
```
**经验值**：hybrid_search + weighted_score 模式下 score_threshold 0.45 会过滤掉全部 → 降到 **0.2**、top_k **3→6**。
验证检索是否命中：`POST /console/api/datasets/{id}/hit-testing`（1.16.1 端点，旧 /retrieve 已 404）。retrieval_model 必须含完整 weights.vector_setting（embedding_provider_name + embedding_model_name），否则 pydantic 报错。

## 快速判别
| 症状 | 大概率原因 |
|---|---|
| "老师经验库尚未配置" | 环1 Token 缺失 |
| 回答通用话术/不引知识库 | 环2 缺 context 或 环3 阈值太高 |
| 回答像老师（有案例细节）但偶发通用 | 检索命中不稳定，调 top_k |

## 验证全链路
```bash
curl -s -X POST http://localhost:8001/api/chat -H 'Content-Type: application/json' \
  -d '{"avatar_id":1,"message":"心悸伴胸闷有什么表现？","user_id":"check_xxx"}'
# 期望：回答含知识库案例细节（如"心率178、按揉内关"）+ 免责声明
```

## 已确认可用的 App 配置（2026-07-31）
- App：老师甲经验fuzhi（3f135625-33cf-4696-b983-81cc9f37c839）
- 知识库：老师甲经验3（合规版）
- 模型：qwen3.7-flash（enable_thinking: false）
- Key：app-[REDACTED]
- 其余 4 分身（老师乙/老师丙/老师戊/老师丁）同流程接入，需各自 API Key
