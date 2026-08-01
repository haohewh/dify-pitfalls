# Dify 1.16.1 链路诊断补充（2026-07-31 实战）

## 场景：前端 AI 分身回答"通用话术"而非知识库内容

完整诊断链（从"老师经验库尚未配置"到全通）：

### 1. SQLite 缺 dify_token → "老师经验库尚未配置"
`/opt/myapp/soulfire_v2.db` 的 `app_settings` 表缺 `dify_token_老师甲` 记录。
llm.py 的 `_get_dify_token()` 从该表读，无记录 → 返回"（老师经验库尚未配置，请等待管理员更新。）"

**修复**：
```sql
INSERT OR REPLACE INTO app_settings (key, value) VALUES ('dify_token_老师甲', 'app-xxx');
-- 然后 kill -9 重启 uvicorn 进程（pkill -9 -f 'uvicorn.*8001'）
```

### 2. 生成 Dify App API Key（1.16.1 端点）
- `POST /console/api/workspaces/current/.../apps/{app_id}/api-keys` 返回 201 + token
- **注意 1.16.1 的 App 可能从未生成过 API Key**：api_tokens 表无记录时，需要先生成再写入 SQLite
- 用户从 Dify 工作室界面复制官方 key 最可靠（对应正确的 App 配置）

### 3. pre_prompt 缺 {{#context#}} → 检索了但模型看不到
- 症状：检索正常（日志有 Weaviate schema 200），但回答是模型自身知识
- 修复：`UPDATE app_model_configs SET pre_prompt = '{{#context#}}\n\n' || pre_prompt WHERE app_id='...'`
- 重启 docker-api-1

### 4. score_threshold 过高 → 召回 0 条（本次关键发现）
- 症状：hit-testing 返回 `命中 0 条`，模型拿不到上下文只能凭记忆答
- 经验2 配置：score_threshold=0.45 + top_k=3
- **weighted_score（权重）模式下 0.45 阈值会过滤掉全部结果**——之前界面测到 0.84 分是另一种计分方式
- 修复：阈值降到 0.2，top_k 提到 6
```sql
UPDATE datasets
SET retrieval_model = jsonb_set(
  jsonb_set(jsonb_set(retrieval_model::jsonb, '{score_threshold}', '0.2'::jsonb),
    '{score_threshold_enabled}', 'true'::jsonb),
  '{top_k}', '6'::jsonb)
WHERE id = '<dataset_id>';
```

### 5. hit-testing 端点（1.16.1 改名）
- 旧版 `/datasets/{id}/retrieve` 在 1.16.1 是 **404**
- 正确：`POST /console/api/datasets/{id}/hit-testing`
- payload 的 retrieval_model.weights.vector_setting 必须含 `embedding_provider_name` + `embedding_model_name`（否则 pydantic validation error）

## 重启进程的坑
- `pkill -9 -f 'uvicorn.*8001'` 在同一 ssh 会话里会 **kill 掉 ssh 本身**（bash 被波及），表现为 exit 255、后续命令不执行
- 正确做法：pkill 单独一条命令执行，**下一条 ssh 重新连接**再启动+验证
- 启动：`cd /opt/myapp && nohup ./venv/bin/python3 -m uvicorn main:app --host 0.0.0.0 --port 8001 >> /tmp/starsower.log 2>&1 &`

## nginx systemd failed 但实际正常
- `systemctl status nginx` 显示 failed（7-30 一次错误 stop 的残留记录），但 nginx 进程实际在跑、443 正常监听、外网 301 正常
- 判断服务是否真挂：`ss -tlnp | grep :443` + 外网 curl，不要只看 systemd 状态
