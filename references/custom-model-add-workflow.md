# Dify 1.16.1 给已装插件添加自定义模型 — 完整实操记录（2026-07-31）

## 背景

Dify 1.16.1 的 tongyi 插件（0.2.5）没有定义 qwen3.7-flash，界面选不到。目标是把它加进去（输入 0.2 / 输出 0.8 元/百万，全场最便宜）。

## 死路记录（全部实测失败，节省未来时间）

| 尝试 | 结果 |
|------|------|
| 改 cwd 目录 yaml（`/app/storage/cwd/langgenius/tongyi-0.2.5@*/models/llm/qwen3.7-flash.yaml`）| 重启后 `_position.yaml` 等被包内容还原；新加的 yaml 可能幸存但模型列表不出现 |
| 改 `_position.yaml` 加模型名 | 不生效——它不是真正的注册清单，或缓存不刷新 |
| 改 difypkg 包（`plugin/` + `plugin_packages/` 下的 zip，用 python zipfile 塞入 yaml 并更新 _position）| 包内容 hash 变化 → 插件实例 hash 从 `9aab606` 变 `ea01aaa`，cwd 目录名跟着变，但 **redis declaration_cache 仍引用旧 hash**，模型列表不刷新 |
| 清 redis 缓存（`declaration_cache` + `plugin_model_providers:generation:N`）| 清了重启后 plugin_daemon 重新生成旧值——因为包/安装记录没变 |
| 用 openai_api_compatible provider | 该插件**实际未安装**（providers 列表只有 minimax/deepseek/tongyi；provider_models 里 2 条记录是残留），报 `Provider ... does not exist` |

## 正路：自定义模型凭据 API

前提：目标插件的 `provider/<name>.yaml` 的 `configurate_methods` 含 `customizable-model`（tongyi 有）。

### 1. 查插件自定义模型 schema（必填字段）

```python
import yaml
# docker exec docker-plugin_daemon-1 sh -c 'cat /app/storage/cwd/langgenius/tongyi-0.2.5@*/provider/tongyi.yaml'
d = yaml.safe_load(content)
schema = d["model_credential_schema"]
for f in schema["credential_form_schemas"]:
    print(f.get("variable"), f.get("type"), "required=", f.get("required"))
# tongyi: dashscope_api_key(secret,必填) + context_size(text,必填,default 4096)
#        + max_tokens(text,default 4096) + function_calling_type(select,default no_call)
```

### 2. 创建自定义模型凭据

```python
import requests

BASE = "http://127.0.0.1:8081"
PROVIDER = "langgenius/tongyi/tongyi"

s = requests.Session()
r = s.post(f"{BASE}/console/api/login", json={"email": "admin@hdnz.net", "password": "<base64密码>"})
# 1.16.1 登录 = cookie 会话（Bug26 坑1/坑2）：手动构造 Cookie header
csrf = s.cookies.get("__Host-csrf_token")
cookie_hdr = "; ".join(f"{c.name}={c.value}" for c in s.cookies)
H = {"Cookie": cookie_hdr, "X-CSRF-Token": csrf, "Origin": "https://example.com",
     "Referer": "https://example.com/console/", "Content-Type": "application/json"}

payload = {
    "model": "qwen3.7-flash",
    "model_type": "llm",
    "name": "qwen3.7-flash",
    "credentials": {
        "dashscope_api_key": "<复用插件已有凭据的 key>",
        "context_size": "1000000",   # 🔴 必须字符串！数字 → "Variable context_size should be string"
        "max_tokens": "8192",        # 🔴 也是字符串
        "function_calling_type": "no_call",
    },
}
r1 = requests.post(
    f"{BASE}/console/api/workspaces/current/model-providers/{PROVIDER}/models/credentials",
    headers=H, json=payload, timeout=120)
# 成功: 201 {"result":"success"}；立即出现在模型列表，无需重启
```

### 3. 验证

```python
r2 = requests.get(
    f"{BASE}/console/api/workspaces/current/model-providers/{PROVIDER}/models?model_type=llm",
    headers=H, timeout=60)
models = r2.json()["data"]
# 列表含 qwen3.7-flash = 成功（102 → 103）
```

模型本身可用性另测（百炼 compatible-mode 直连 chat/completions）。

## 插件机制备忘

- 模型列表来源：plugin_daemon `/management/models` 接口（需鉴权）+ redis `declaration_cache:local:<plugin>@<hash>` + `plugin_model_providers:tenant_id:<id>:generation:N`
- 插件目录三处：`plugin/`（安装包）+ `plugin_packages/`（缓存包）+ `cwd/`（运行解压副本）。**删 cwd 目录无效**（重启从包恢复）；彻底卸载走 Dify 界面/API
- 改包内容 → 实例 hash 变化（9aab606→ea01aaa）→ cwd 目录名变化 → redis 缓存 key 对不上 → 模型列表混乱。**不要改包**
- `provider_models` 表只记录显式配置过的模型（自定义模型会写入），≠ 插件声明全部模型
- API 容器内 `docker exec docker-api-1 python3 -c "..."` 调 `http://plugin_daemon:5002` 需 401 鉴权（PluginDaemonUnauthorizedError），排查时优先用 Dify console API 而非直连 plugin_daemon

## 相关坑速记

- 登录/CSRF/cookie：见 SKILL.md Bug26
- SQL 写文件执行防引号转义：见 SKILL.md Bug28
- 插件版本残留：`ls /app/storage/cwd/langgenius/ | grep <plugin>`；删残留目录用完整路径不带 sh -c glob
