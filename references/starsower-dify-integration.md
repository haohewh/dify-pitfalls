# Starsower_v2 ↔ Dify 集成架构

## 重要结论

**Starsower_v2（example.com/xhxc）完全不走 Dify 知识库**，LLM 调用路径是：
- Starsower_v2 → `services/llm.py` → **DeepSeek API**（`api.deepseek.com`）
- Starsower_v2 → 本地 JSON 文件（`/opt/myapp/data/experiences/*.json`）

**Starsower_v2 的 avatars 表 system_prompt** 才是实际生效的提示词（不是 Dify 的 pre_prompt）。

## 改造方案：让 Starsower_v2 走 Dify API

### 步骤1：获取5个 Dify App Token
从 Dify App → "API访问" 页面获取，格式：`app-xxxxx`

| 名字 | App Token |
|------|-----------|
| 老师甲 | app-[REDACTED] |
| 老师乙 | app-[REDACTED] |
| 老师丙 | app-[REDACTED] |
| 老师戊 | app-[REDACTED] |
| 老师丁 | app-[REDACTED] |

### 步骤2：改 llm.py 支持 Dify

```python
DIFY_BASE_URL = "http://172.19.0.9:5001"

def call_llm(avatar_name, avatar_personality, user_message,
             memory_context="", conversation_id=None):
    dify_token = _get_dify_token(avatar_name)  # 从 app_settings 读
    if dify_token:
        answer, new_conv_id = _call_dify(dify_token, user_message,
                                          user_id=avatar_name,
                                          conversation_id=conversation_id)
        return json.dumps({"reply": answer, "avatar": avatar_name,
                           "conversation_id": new_conv_id})
    # fallback DeepSeek...
```

### 步骤3：存 Dify Token 到 app_settings
```python
# dify_token_老师甲 = app-[REDACTED]
conn.execute("INSERT OR REPLACE INTO app_settings (key, value) VALUES (?, ?)",
             (f"dify_token_{name}", token))
```

### 步骤4：conversation_id 持久化（Dify 会话历史）
1. `conversations` 表加 `dify_conv_id` 列
2. 发消息前查该用户上次 `dify_conv_id`，传 `conversation_id` 给 Dify
3. Dify 返回新 `conversation_id`，存回数据库

SQL：
```sql
ALTER TABLE conversations ADD COLUMN dify_conv_id TEXT;

-- 存：取最新一条的 dify_conv_id
UPDATE conversations SET dify_conv_id = ? WHERE id = (
  SELECT id FROM conversations WHERE user_id=? AND avatar_id=? ORDER BY created_at DESC LIMIT 1
);
```

### 步骤5：对话入口参数
Dify `/v1/chat-messages` 请求体：
```json
{
  "query": "用户问题",
  "inputs": {},
  "user": "avatar_name",
  "response_mode": "blocking",
  "conversation_id": "可选-上次会话ID"
}
```

### 关键坑
- Starsower_v2 端口 8001，服务器自身访问 `http://localhost:8001` 正常
- Dify API 在 `http://172.19.0.9:5001`（容器内网），不是 `http://example.com`
- 改完 `llm.py` 必须重启 Starsower_v2：`fuser -k 8001/tcp && uvicorn...`

## Starsower_v2 架构速查
- 代码：`/opt/myapp/`
- 数据库：`/opt/myapp/soulfire_v2.db`（SQLite）
- 经验JSON：`/opt/myapp/data/experiences/*.json`
- avatars 表：system_prompt（实际生效的提示词）
- LLM配置：`app_settings` 表的 `llm_api_key` / `llm_base_url` / `llm_model`
- DeepSeek Key：`sk-[REDACTED]`（已失效）
