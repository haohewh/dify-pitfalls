# Bug24 深度解析：llm.py 才是真正的 Dify 调用入口

## 症状
AI回答靠大模型训练记忆，知识库从未被调用。

## 根因：`llm.py` DIFY_BASE_URL 写错了

**文件**：`/opt/myapp/services/llm.py`

```python
DIFY_BASE_URL = "http://172.19.0.9:5001"  # ❌ 错：Docker内网地址，Starsower_v2服务器上不可达
```

Starsower_v2服务器上 Dify 通过 docker-proxy 映射到本地 `8081`，不是 `5001`。

## 真正调用链

```
前端 /api/chat (index.html 第669行)
  → routes/chat.py → call_llm()
    → services/llm.py → call_llm()
      → Dify (URL错，连不上)
        → fallback DeepSeek ❌ （[作者]禁止）
```

**注意**：`dify_proxy.py` 的 `/api/chat-dify` 是废弃接口，前端从未调用（日志里没有真实流量），无需关注。

## 已修复

```python
# llm.py 第12行
DIFY_BASE_URL = "http://127.0.0.1:8081"  # ✅ Dify docker-proxy 本地端口
```

## 验证方法

### 1. 直连 Dify API（快速验证）
```bash
ssh root@127.0.0.1
curl -s -X POST http://127.0.0.1:8081/v1/chat-messages \
  -H "Authorization: Bearer app-[REDACTED]" \
  -H "Content-Type: application/json" \
  -d '{"query":"你是谁","response_mode":"blocking","user":"test","inputs":{}}'
# 期望：返回老师甲分身回答，不是"我是通用AI"
```

### 2. 前端功能验证（最终验证）
去 https://example.com/xhxc 选老师甲，问：
- "右手腕疼痛怎么按揉" → 期望：说出阳池/外关/养老/列缺穴（知识库精炼内容）
- 如果只说"经络理法通用原理" → 知识库仍未调通

### 3. 日志验证
```bash
ssh root@127.0.0.1
grep '\[Dify\]' /opt/myapp/logs/app.log
# 看到 [Dify] 老师甲: xxx → Dify调用成功
# 如果看到 [Dify] 老师甲 调用失败，fallback → URL可能仍错
```

## 教训

"llm.py 在调 Dify" 不等于 "知识库在被用"——必须：
1. 确认 DIFY_BASE_URL 可达
2. 实际发一条有知识库特征的问题，验证检索发生
3. 看日志确认走了 Dify 而非 fallback
