# Dify 模型插件凭据验证调试工作流

当用户在 Dify 配置模型凭据时遇到「渲染此组件时发生了意外错误」或 API 返回 400/500，按此流程排查。

## 第一步：确认 Key 本身有效（排除用户/Key问题）

始终先用模型原生的 OpenAI 兼容端点测试 Key，避免被 Dify 插件层误导：

```bash
# OpenAI 兼容格式（通用）
curl -s -w "\nHTTP:%{http_code}" https://api.provider.com/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $KEY" \
  -d '{"model":"MODEL_NAME","messages":[{"role":"user","content":"hi"}],"max_tokens":3}'

# ✅ 200 + choices → Key 有效，问题在 Dify 插件层
# ❌ 401 + "invalid api key" → Key 本身无效（截断/过期/格式错误）
```

**常见 Key 问题**：
- Key 被截断（`...` 字面点）：检查 `.env` 文件里 Key 完整性，正常长度 50-80 字符
- Key 类型不匹配：部分厂商有「订阅 Key」和「按量 Key」两种，不能混用
- Key 过期：Token Plan 过期后返回 401

## 第二步：查 Dify 后端日志（定位哪个环节报错）

```bash
# 查 API 容器日志
docker logs docker-api-1 2>&1 | grep -E "CredentialsValidateFailedError|PluginInvokeError|error" | tail -20

# 查 plugin_daemon 日志
docker logs docker-plugin_daemon-1 2>&1 | grep "validate_provider_credentials" | tail -10
```

典型错误链：
```
API 容器：CredentialsValidateFailedError: Error code: 401 - {error: {message: 'invalid api key'}}
Plugin daemon：status=200 latency_ms=2572  ← proxy 正常，但 MiniMax 返回401
```

## 第三步：找到插件代码（读取验证逻辑）

插件包位于 plugin_daemon 容器的 `/app/storage/` 下：

```bash
# 1. 列出所有已装插件
docker exec docker-plugin_daemon-1 ls /app/storage/plugin_packages/langgenius/

# 2. 找到插件解压后的运行目录
docker exec docker-plugin_daemon-1 find /app/storage/cwd -maxdepth 1 -type d | grep PROVIDER_NAME

# 3. 查看插件 manifest（凭据表单定义）
docker exec docker-plugin_daemon-1 cat /app/storage/cwd/.../manifest.yaml
# 关注：provider_credential_schema → variable 字段（API Key 变量名）

# 4. 查看 provider 代码（validate_provider_credentials 方法）
docker exec docker-plugin_daemon-1 grep -n "validate_provider_credentials" /app/storage/cwd/.../provider/*.py
docker exec docker-plugin_daemon-1 sed -n "START,ENDp" /app/storage/cwd/.../provider/PROVIDER.py

# 5. 查看 LLM 模型 validate_credentials 方法
docker exec docker-plugin_daemon-1 grep -n "validate_credentials" /app/storage/cwd/.../models/llm/llm.py
```

## 第四步：检查插件调用的实际 API 端点和认证方式

关键函数通常叫 `_to_credential_kwargs()` 或类似，决定实际调用的 URL 和 header：

```bash
docker exec docker-plugin_daemon-1 grep -n "_to_credential_kwargs\|_build_credential" /app/storage/cwd/.../models/llm/llm.py
docker exec docker-plugin_daemon-1 sed -n "START,ENDp" /app/storage/cwd/.../models/llm/llm.py
```

检查以下关键点：
- **Base URL**：是否是厂商当前的 API 端点（有些插件用的旧端点已废弃）
- **认证 header**：`Authorization: Bearer` vs `x-api-key` vs `X-Api-Key`
- **API 格式**：OpenAI 兼容 (`/v1/chat/completions`) vs Anthropic (`/v1/messages`) vs 厂商私有格式
- **模型名映射**：`_resolve_model_name()` 或 `_MODEL_ALIASES` 映射是否正确

## 第五步：直接模拟插件调用验证

用 curl 模拟插件实际发出的请求：

```bash
# Anthropic/MiniMax 格式
curl -sv https://api.example.com/anthropic/v1/messages \
  -H "x-api-key: $KEY" \
  -H "anthropic-version: 2023-06-01" \
  -H "Content-Type: application/json" \
  -d '{"model":"MODEL","max_tokens":8,"messages":[{"role":"user","content":"ping"}]}'

# 关注 response header 和 body 中的具体错误信息
```

## 第六步：修复方案（按优先级）

1. **更新插件**：去 Dify 后台「插件」→ 检查是否有新版（新版可能改了 API 端点或认证方式）
2. **换用其他插件**：如千问/Tongyi 插件比 MiniMax 稳定，或装 `openai_api_compatible` 通用插件
3. **绕过插件层**：用 Dify 的「OpenAI API Compatible」模型提供商类型，直接填 Base URL + API Key
4. **修改插件代码**：仅临时方案，更新插件会覆盖修改

## 常见插件问题索引

| 插件 | 版本 | 问题 | 根因 |
|------|------|------|------|
| MiniMax | 0.0.23 | Anhtropic API header 认证不识别 | 插件调 `/anthropic/v1/messages`，端点已废弃或 Bug |
| DeepSeek | — | — | 正常 |
| Tongyi | 0.1.48 | — | 正常（千问工作空间 Key） |

## 关键文件位置

| 组件 | 路径 |
|------|------|
| 插件包 | `/app/storage/plugin_packages/langgenius/`（.dgpt 格式，压缩包） |
| 插件运行代码 | `/app/storage/cwd/langgenius/PROVIDER-VERSION@HASH/` |
| 插件 manifest | 同上 `manifest.yaml` |
| Provider 代码 | 同上 `provider/PROVIDER.py` |
| LLM 模型代码 | 同上 `models/llm/llm.py` |
| API 容器日志 | `docker logs docker-api-1` |
| Plugin daemon 日志 | `docker logs docker-plugin_daemon-1` |
