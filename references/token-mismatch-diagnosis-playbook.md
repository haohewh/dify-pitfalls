# Dify 知识库检索失败 - 系统性诊断 Playbook

2026-07-29 实测验证的诊断工作流。

## 症状

- Starsower_v2 `/api/chat` 返回通用大模型回答，不含知识库内容
- 直连 Dify API 用正确 Key 能正常检索
- 用户问"右手腕疼痛怎么按揉"返回"左证右调"通用理论，而不是知识库里的具体穴位

## 诊断步骤（按顺序）

### 第一步：审查调用代码

```bash
ssh root@127.0.0.1 "cat /opt/myapp/services/llm.py"
```

**关注点**：`_get_dify_token()` 从哪里读取 Token。本案例中从 SQLite `app_settings` 表读取。

### 第二步：三重源对比 Token

```bash
ssh root@127.0.0.1 "
echo '=== SQLite (llm.py 实际读取源) ==='
sqlite3 /opt/myapp/soulfire_v2.db \"SELECT key, substr(value,1,45) FROM app_settings WHERE key LIKE '%dify%';\"
echo '=== .env 文件 ==='
grep DIFY_KEY /opt/myapp/.env
echo '=== 进程环境变量 ==='
PID=\$(ps aux | grep 'uvicorn.*8001' | grep -v grep | awk '{print \$2}' | head -1)
cat /proc/\$PID/environ | tr '\0' '\n' | grep DIFY_KEY
"
```

**本案例发现**：SQLite 有旧 Key `app-LKEQexB6...`，.env 和进程环境有新 Key `app-ScaMF6vPl...`。`llm.py` 读 SQLite → 旧 Key → 401 → fallback DeepSeek。

### 第三步：直连 Dify API 验证 Key 有效性

```bash
# 旧 Key
ssh root@127.0.0.1 "curl -s --max-time 10 -X POST 'http://127.0.0.1:8081/v1/chat-messages' \
  -H 'Authorization: Bearer app-[REDACTED]' \
  -H 'Content-Type: application/json' \
  -d '{\"query\":\"测试\",\"response_mode\":\"blocking\",\"user\":\"diag\",\"inputs\":{}}'"

# 新 Key  
ssh root@127.0.0.1 "curl -s --max-time 10 -X POST 'http://127.0.0.1:8081/v1/chat-messages' \
  -H 'Authorization: Bearer app-[REDACTED]' \
  -H 'Content-Type: application/json' \
  -d '{\"query\":\"右手腕疼痛怎么按揉\",\"response_mode\":\"blocking\",\"user\":\"diag\",\"inputs\":{}}'"
```

**期望**：旧 Key 返回 `401 unauthorized`，新 Key 返回穴位知识 + `retriever_resources` 非空。

### 第四步：验证 Starsower_v2 真实调用链

```bash
ssh root@127.0.0.1 "curl -s --max-time 40 -X POST 'http://localhost:8001/api/chat' \
  -H 'Content-Type: application/json' \
  -d '{\"avatar_id\":1,\"message\":\"右手腕疼痛怎么按揉\",\"user_id\":\"diag_final\"}'"
```

**本案例结果**：返回"左证右调"通用理论（DeepSeek fallback），证实知识库未被调用。

### 第五步：检查 Dify Docker 日志

```bash
ssh root@127.0.0.1 "docker logs docker-api-1 --tail 100 2>&1 | grep -iE '401|unauthorized|Vector_index|retrieval|error' | tail -20"
```

**本案例发现**：传统经络针法底座1 有 Vector_index 不匹配错误（`Vector_index_7c1c4496_...` 不存在）。

### 第六步：检查知识库数据库状态

```sql
-- 知识库概览
SELECT ds.name, COUNT(DISTINCT s.id) as segments,
  COALESCE(SUM(s.word_count), 0) as total_chars
FROM datasets ds
LEFT JOIN document_segments s ON s.dataset_id = ds.id
GROUP BY ds.id, ds.name ORDER BY ds.name;

-- App 知识库关联
SELECT a.name, ds.name as dataset
FROM apps a
LEFT JOIN app_dataset_joins ad ON ad.app_id = a.id
LEFT JOIN datasets ds ON ds.id = ad.dataset_id
ORDER BY a.name;
```

### 第七步：检查 main.py 加载路径

```bash
ssh root@127.0.0.1 "head -10 /opt/myapp/main.py | grep load_dotenv"
```

**本案例发现**：`load_dotenv("/opt/myapp/.env")` 而非 `/opt/myapp/.env`（Bug27）。

## 根本原因

`llm.py` 的 `_get_dify_token()` 从 SQLite `app_settings` 读取 Token，Dify Studio 重新生成 Key 后：
- `.env` 已更新 → ✅
- 进程环境变量已更新 → ✅  
- **SQLite `app_settings` 未更新** → ❌ 这才是实际被读取的源

## 修复

```bash
# 1. 更新 SQLite Token
ssh root@127.0.0.1 "sqlite3 /opt/myapp/soulfire_v2.db \
  \"UPDATE app_settings SET value='app-[REDACTED]' WHERE key='dify_token_老师甲';\""

# 2. kill -9 重启（不能只 SIGHUP）
ssh root@127.0.0.1 "pkill -9 -f 'uvicorn.*8001'; sleep 2; \
  cd /opt/myapp && nohup /opt/myapp/venv/bin/python3 \
  -m uvicorn main:app --host 0.0.0.0 --port 8001 >> /tmp/starsower.log 2>&1 &"

# 3. 验证
ssh root@127.0.0.1 "sleep 3 && curl -s --max-time 40 -X POST 'http://localhost:8001/api/chat' \
  -H 'Content-Type: application/json' \
  -d '{\"avatar_id\":1,\"message\":\"右手腕疼痛怎么按揉\",\"user_id\":\"verify_fix\"}'"
```

## 关键教训

1. **Token 的"源"是 SQLite**：`llm.py` 不读 `.env` 或进程环境变量，只读 `app_settings` 表
2. **三重对比是必须的**：SQLite vs .env vs 进程环境，三者可能不同步
3. **直连测试排除变量**：绕过 Starsower_v2 直接调 Dify API，确认是 Token 问题还是路由问题
4. **kill -9 是唯一可靠的重启方式**：`pkill` 和 `SIGHUP` 不可靠
