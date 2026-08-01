---
name: dify-ops-reference
description: Dify 运维参考——容器路径、数据库结构、API端点、常见bug修复
---
### Bug1: docker-web-1 重启后 Next.js 路由丢失（/console 404）
- 现象：重启 docker-web-1 后，example.com/console 返回 Next.js 的 404 页面
- 排查路径：
  1. 容器内 `wget http://web:3000/` → 正常（返回 HTML）→ nginx 正常
  2. `docker inspect docker-web-1 --format "{{.NetworkSettings.Networks}}"` → docker_default 网络正常
  3. `find /app/web/.next/server/app -name "page.js"` → 发现 `/console` 路由不存在
  4. 根因：Next.js build 不完整，docker restart 挂载的 volume 里 build 产物缺失
- 解决：再次 `docker restart docker-web-1` 通常能恢复（volume 重新挂载），不行则需重 build
- **排查时从容器内测**：`docker exec docker-nginx-1 wget -q -O- http://web:3000/console` 验证

### Bug2: 服务器自身访问公网域名被防火墙拦截
- 现象：服务器上 `curl http://example.com` 返回 exit code 7（connection refused）
  - 但 `curl http://127.0.0.1` 正常，`nslookup example.com` 解析正确（127.0.0.1）
- 根因：走公网路由自己，被云服务器 iptables INPUT 链或安全组拦截
- **正确姿势**：从容器内用 docker_default 网络测：
  ```bash
  docker exec docker-nginx-1 wget -q -O- http://web:3000/
  docker exec docker-nginx-1 wget -q -O- http://172.19.0.9:5001/health
  ```
- 外网访问问题去云服务器控制台看安全组，不是 Dify 问题

### Bug3: tenant_id 不匹配导致文档在数据库存在但UI不显示
- 现象：小卡片显示"1文档·23千字符"，但点开文档列表为空；知识库关联应用显示"0关联应用"
- 根因：文档 `documents.tenant_id` ≠ App `apps.tenant_id`，跨租户的文档对App不可见
- 诊断：
  ```sql
  -- 查文档的 tenant_id
  SELECT id, name, tenant_id FROM documents WHERE dataset_id = '<dataset_id>';
  -- 查 App 的 tenant_id
  SELECT id, name, tenant_id FROM apps WHERE name LIKE '%老师甲%';
  ```
- **上传前必须确认**：用 App 所在账号登录 Dify 再上传，或确认文档 tenant_id 与 App 一致
- 解决：用 App 所属租户的账号重新上传文件

### Bug4: knowledge_config.data_source 空值导致 500
- 报错：`AttributeError: 'NoneType' object has no attribute 'info_list'`
- 原因：Dify 1.3.1 代码直接访问 `knowledge_config.data_source.info_list.data_source_type`，无空值保护
- 修复：sed 替换加 `if ... else None` 保护，见 dataset_service.py 第 897/918/1036/1093/1133/1310 行
- **修复后必须 docker cp 进容器**：`docker cp /opt/dify/... docker-api-1:/app/api/services/dataset_service.py`

### Bug5: Dify Web前端显示UTC时间而非北京时区（2026-07-28实测）
- 现象：知识库文档上传时间显示比实际早8小时（如实际06:05显示02:05）
- 根因：docker-web-1 容器内 TZ=UTC，Next.js读取浏览器本地时间时按UTC解析
- **LOG_TZ参数无效**：LOG_TZ只控制日志时区，不影响前端显示
- **无法彻底修复**：Next.js官方镜像在构建时强制嵌入UTC，容器内改/etc/timezone无权限
- 临时方案：数据库时间正确，前端显示偏差是UI bug，不影响功能
- 已知问题，不影响实际使用

### Bug6: `data_source_info` JSON 格式错误导致前端 500
- 报错：`Expecting property name enclosed in double quotes: line 1 column 2 (char 1)`
- 根因：`data_source_info` 值写成单引号 `{name:...}` 或键值无引号 `name:"..."`
- 正确格式：`{"name": "文件.json", "size": N, "type": "json", "upload_type": "file"}`（双引号包裹整个JSON）
- **Bug6 + Bug7 + Bug8 + Bug9 常四缺N同时出现**，INSERT后详情页500要把四个全补

### Bug7: 直接INSERT文档缺 `file_id` 导致500 KeyError
- 报错：`KeyError: 'upload_file_id'`
- 触发页面：知识库文档详情页 `/datasets/{id}/documents/{doc_id}`
- 根因：`documents.file_id` 为 NULL，Dify 代码读取文件上传信息时 `data_source_info['upload_file_id']` 报 KeyError
- 修复：
```python
import uuid
file_id = str(uuid.uuid4())
# UPDATE documents SET file_id = '<file_id>' WHERE id = '<doc_id>';
```
- **Bug7 + Bug8 + Bug9 经常三缺一同时出现**，INSERT后若详情页500，三个都要补

### Bug8: 直接INSERT文档缺 `dataset_process_rule_id` 导致500
- 报错：`AttributeError: 'NoneType' object has no attribute 'to_dict'`（`document.dataset_process_rule.to_dict()`）
- 触发页面：知识库文档详情页 `/datasets/{id}/documents/{doc_id}`
- 根因：直接INSERT `documents` 表时 `dataset_process_rule_id` 为NULL，Dify代码假设此字段永远有值
- 修复：先给数据集建一条 `dataset_process_rules` 记录，再UPDATE文档
```sql
-- 1. 建 process_rule（用 dataset 的 tenant_id 和任意账号ID）
INSERT INTO dataset_process_rules (id, dataset_id, mode, rules, created_by)
VALUES ('<uuid>', '<dataset_id>', 'automatic', NULL, '<account_id>');

-- 2. 关联到文档
UPDATE documents SET dataset_process_rule_id = '<rule_id>' WHERE id = '<doc_id>';
```
- **症状判断**：日志里出现 `Exception on /console/api/datasets/{id}/documents/{doc_id}` + `to_dict` 即为此bug

### Bug9: 直接INSERT文档缺 `data_source_info` 导致500
- 报错：同 Bug8，`AttributeError: 'NoneType' object has no attribute 'to_dict'`
- 根因：`data_source_info` 字段为NULL，Dify读取文件详情时代码假设非空
- 修复：
```sql
UPDATE documents
SET data_source_info = '{"name": "文件名.json", "size": N, "type": "json", "upload_type": "file"}'
WHERE id = '<doc_id>';
```
- **Bug8和Bug9经常同时出现**，INSERT后若详情页500，两个都要补

### Bug10: 容器内外路径不一致
- 主机路径改了但容器跑的是 volume 挂载的旧文件
- 每次改完必须 docker cp + docker restart

### Bug11: Dify 知识库"伪completed"状态
- 现象：`documents.indexing_status='completed'` 但 `document_segments` 表为空
- 原因：文档走 API 上传后 Dify worker 异步分片，但 worker 挂了或处理失败
- 解决：直接用 COPY FROM stdin 写 segment（见上文上传流程）

### Bug12: 自定义JSON schema上传——JSONL直写数据库（2026-07-28已验证）

**已验证可用的完整工作流**：

**Step 1：JSON → JSONL 转换脚本**
```python
#!/usr/bin/env python3
import json, os

src = '/mnt/d/AI/AI产品/25 AI经验平台经验/最终知识库上传/'
out = src
for fname in os.listdir(src):
    if not fname.endswith('.json') or fname.endswith('.jsonl'):
        continue
    d = json.load(open(os.path.join(src, fname), encoding='utf-8'))
    records = []
    for key in ['cases', 'acupoint_knowledge', 'treatment_principles',
                'golden_quotes', 'refined_principles', 'refined_quotes', 'keywords']:
        for item in d.get(key, []):
            if isinstance(item, dict):
                parts = [f"{k}：{v}" for k, v in item.items() if v and str(v).strip()]
                if parts:
                    records.append({'content': '；'.join(parts), 'source': key})
    out_path = os.path.join(out, fname.replace('.json', '.jsonl'))
    with open(out_path, 'w', encoding='utf-8') as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
    print(f'{fname} -> {len(records)}条')
```

**Step 2：服务器上用 confirmed-working 脚本上传**
```python
#!/usr/bin/env python3
# dify_upload5.py — 2026-07-28验证通过，5个老师全部成功
import json, uuid, subprocess

TENANT = 'f4194df5-5a62-4558-846c-e20f76586813'
COPY_COLS = ('id, tenant_id, dataset_id, document_id, position, content, '
             'word_count, tokens, keywords, index_node_id, index_node_hash, '
             'hit_count, enabled, disabled_at, disabled_by, status, '
             'created_by, created_at')

teachers = [
    ("老师乙", "c18d25ae-2028-4939-9baf-3e2dd71b7b72", "/tmp/老师乙经验精炼.jsonl"),
    ("老师丙", "975df16c-c5fc-4876-821b-84f585a3c832", "/tmp/老师丙经验精炼.jsonl"),
    ("老师丁",   "8a9e8241-30d9-46ab-8566-0cc52eb68219", "/tmp/老师丁经验精炼.jsonl"),
    ("老师戊", "9dd0682e-d32e-4ed2-bc32-727ecb93c490", "/tmp/老师戊经验精炼.jsonl"),
    ("老师甲", "f8e83086-4186-4511-b965-c48d85021508", "/tmp/老师甲经验精炼_合规.jsonl"),
]

def psql(sql):
    return subprocess.check_output(
        ['docker', 'exec', 'docker-db-1',
         'psql', '-U', 'postgres', '-d', 'dify', '-c', sql],
        stderr=subprocess.STDOUT, timeout=30).decode()

for name, ds_id, jsonl_path in teachers:
    records = [json.loads(l) for l in open(jsonl_path, encoding='utf-8') if l.strip()]
    total_chars = sum(len(r['content']) for r in records)
    doc_id, file_id, batch = str(uuid.uuid4()), str(uuid.uuid4()), f'batch_{file_id}'
    fname = jsonl_path.split('/')[-1]
    print(f"处理 {name}: {len(records)}条, {total_chars}字符")
    psql(f"INSERT INTO upload_files (id, tenant_id, key, name, size, extension, mime_type, created_by, created_by_role, storage_type, used) VALUES ('{file_id}', '{TENANT}', 'upload_files/{ds_id}/{file_id}', '{fname}', {total_chars}, 'jsonl', 'application/jsonl', '{TENANT}', 'account', 'local', false)")
    psql(f"INSERT INTO documents (id, tenant_id, dataset_id, name, doc_form, doc_language, indexing_status, data_source_type, file_id, word_count, position, created_by, batch, created_from, enabled) VALUES ('{doc_id}', '{TENANT}', '{ds_id}', '{fname}', 'text_model', 'Chinese', 'completed', 'upload_file', '{file_id}', {total_chars}, 1, '{TENANT}', '{batch}', 'api', true)")
    seg_lines = []
    for i, rec in enumerate(records):
        seg_id = str(uuid.uuid4())
        content = rec['content'].replace('\t', ' ').replace('\n', ' ').replace("'", "''")
        keywords = json.dumps([rec.get('source', '')], ensure_ascii=False)
        line = f'{seg_id}\t{TENANT}\t{ds_id}\t{doc_id}\t{i+1}\t{content}\t{len(rec["content"])}\t0\t{keywords}\t\\N\t\\N\t0\ttrue\t\\N\t\\N\tdataset\t{TENANT}\tnow()'
        seg_lines.append(line)
    seg_data = ('\n'.join(seg_lines) + '\n').encode('utf-8')
    proc = subprocess.Popen(
        ['docker', 'exec', '-i', 'docker-db-1',
         'psql', '-U', 'postgres', '-d', 'dify', '-c',
         f'COPY document_segments({COPY_COLS}) FROM stdin'],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out, _ = proc.communicate(seg_data)
    print(f"  COPY: {out.decode()[:50] if out else 'OK'}")
```

**Step 3：部署到服务器执行**
```bash
# 先把jsonl和脚本传到服务器
scp /tmp/*.jsonl root@127.0.0.1:/tmp/
scp /tmp/dify_upload5.py root@127.0.0.1:/tmp/
ssh root@127.0.0.1 "python3 /tmp/dify_upload5.py"
```

**关键字段**：
- `COPY_COLS` 必须包含 `created_by` 和 `created_at`（新增字段，缺少会报错 `null value in column "created_by"`）
- `COPY FROM stdin` 成功返回 `COPY N`（N=记录数）
- 空字段（index_node_id等）写 `\N`，不是 NULL
### Bug13: Dify 支持的文件格式（2026-07-28实测）

Dify 知识库**不支持 jsonl**。官方支持格式：
- ✅ PDF、DOCX、TXT、Markdown、CSV、Excel、HTML、JSON
- ❌ **jsonl 不支持**（上传后字符数为0，索引报错）

**结论**：所有自定义 schema 的 JSON 文件一律转成 `.md`（用 `##` 标题 + 正文）再上传。

### Bug14: 文档上传 API——JSON body + base64（2026-07-28核心发现）

**错误方式**：multipart/form-data 上传
```
415 unsupported_media_type: "Did not attempt to load JSON data because Content-Type was not 'application/json'"
```

**正确方式**：JSON body + base64 编码文件内容
```python
import base64, requests

payload = {
    "indexing_technique": "high_quality",
    "process_rule": {
        "mode": "custom",
        "rules": {
            "pre_processing_rules": [{"id": "remove_extra_spaces", "enabled": True}],
            "segmentation": {"separator": "\n\n", "max_tokens": 500}
        }
    },
    "file": base64.b64encode(open(file_path, "rb").read()).decode(),
    "file_name": os.path.basename(file_path),
}
headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
r = requests.post(f"{API}/console/api/datasets/{ds_id}/documents",
    headers=headers, json=payload, timeout=120)
```
**注意**：Dify Console Token 登录方式：`POST /console/api/login` + email/password，返回的 access_token 用于后续所有 API 调用。

### Bug15: Dify Dataset ID 两套体系——URL ID ≠ API ID（2026-07-28）

- **URL/浏览器里的 ID**（如 `f8e83086-4186-4511-b965-c48d85021508`）：用于浏览器访问，与 API 不通
- **API ID**（如 `bbd95d85-7d90-4f89-aa9f-3687bcd65274`）：用于 API 调用

**查询正确 API ID**：
```python
r = requests.get(f"{API}/console/api/datasets?page=1&limit=20",
    headers={"Authorization": f"Bearer {token}"})
for ds in r.json()["data"]:
    print(f"{ds['name']} -> {ds['id']}  docs:{ds['document_count']}")
```

### Bug16: Starsower_v2 `/api/chat` 知识库链路断裂——llm.py DIFY_BASE_URL 指向错误地址（2026-07-28实测）

**症状**：AI回答靠大模型训练记忆，知识库从未被调用。用户感觉"AI什么都知道但不是从我们知识库里答的"。

**根因**：`/api/chat` 主流程调用 `services/llm.py` → `call_llm()` → 优先走 Dify，但 `DIFY_BASE_URL = "http://172.19.0.9:5001"`（Docker内网地址，Starsower_v2服务器上不可达），连接失败 → fallback DeepSeek（[作者]禁止）。

**真正调用链**：`前端 /api/chat → routes/chat.py → services/llm.py → call_llm() → Dify（URL错） → fallback DeepSeek ❌`

⚠️ `dify_proxy.py` 的 `/api/chat-dify` 是废弃接口，前端从未调用，无需关注。

**修复（llm.py 第12行，已执行）**：
```python
DIFY_BASE_URL = "http://127.0.0.1:8081"  # Dify 通过 docker-proxy 映射到服务器本地 8081
```

**验证**：
```bash
# 1. 确认 token 已写入 app_settings
ssh root@127.0.0.1 "sqlite3 /opt/myapp/soulfire_v2.db \
\"SELECT key,value FROM app_settings WHERE key LIKE 'dify_token%'\""
# 期望：dify_token_老师甲 | app-[REDACTED]

# 2. 直连 Dify API（快速验证）
curl -s -X POST http://127.0.0.1:8081/v1/chat-messages \
  -H "Authorization: Bearer app-[REDACTED]" \
  -H "Content-Type: application/json" \
  -d '{"query":"你是谁","response_mode":"blocking","user":"test","inputs":{}}'
# 期望：返回老师甲分身回答，不是"我是通用AI"

# 3. 前端功能验证
# 去 https://example.com/xhxc 选老师甲，问"右手腕疼痛怎么按揉"
# 期望：说出阳池/外关/养老/列缺穴（知识库精炼内容）
# 如果只说"经络理法通用原理" → 知识库仍未调通
```

详见：`references/bug24-llm-py-dify-url-fix.md`

### Bug17: main.py 加载 .env 路径错误导致 Dify Key 不生效（2026-07-29实测）

**现象**：更新了 `/opt/myapp/.env` 里的 DIFY_KEY，但 Starsower_v2 重启后 API 仍返回 401。

**根因**：`main.py` 第7行 `load_dotenv("/opt/myapp/.env")` 加载的是 `/opt/myapp/.env`，不是 `/opt/myapp/.env`。Starsower_v2 进程实际读的是旧目录的 .env 文件。

```python
# 错误的加载路径
load_dotenv("/opt/myapp/.env", override=True)  # 实际生效的是这个

# Starsower_v2 目录的 .env 被忽略
# /opt/myapp/.env  # ← 这个文件的更新不会生效
```

**验证方法**：
```bash
# 查进程实际加载的环境变量
ssh root@127.0.0.1 "ps aux | grep uvicorn | grep -v grep | awk '{print \$2}' | head -1 | xargs -I{} cat /proc/{}/environ | tr '\0' '\n' | grep DIFY_KEY"
# 如果输出的是旧值（如 app-[REDACTED]），说明路径错误
```

**修复**：
方案A（正确但需改代码）：修改 `main.py` 加载路径为 `"/opt/myapp/.env"`

方案B（临时应急）：直接把 DIFY_KEY 追加到 `/opt/myapp/.env`

```bash
# 立即修复（方案B）
ssh root@127.0.0.1 "cat >> /opt/myapp/.env << 'EOF'
DIFY_KEY_CJM=app-[REDACTED]
DIFY_KEY_CXM=app-[REDACTED]
DIFY_KEY_LSL=app-[REDACTED]
DIFY_KEY_WY=app-[REDACTED]
DIFY_KEY_ZMH=app-[REDACTED]
EOF"
```

**重启后验证 Key 生效**：
```bash
ssh root@127.0.0.1 "kill -9 <uvicorn_pid>; sleep 1; cd /opt/myapp && nohup ./venv/bin/python3 -m uvicorn main:app --host 0.0.0.0 --port 8001 >> /tmp/starsower.log 2>&1 &"
sleep 3
# 验证进程加载了新 Key
ssh root@127.0.0.1 "cat /proc/\$(ps aux | grep uvicorn | grep -v grep | awk '{print \$2}' | head -1)/environ | tr '\0' '\n' | grep DIFY_KEY_CXM"
# 期望：DIFY_KEY_CXM=app-[REDACTED]
```

**教训**：改 `.env` 文件后必须 kill -9 重启进程，不能只 SIGHUP。而且要看进程实际读的是哪个 .env。

### Bug18: Milvus 向量索引名不匹配导致检索失败（2026-07-29实测）

**症状**：
- Dify API `/v1/chat-messages` 调用返回成功（200），但答案内容是通用大模型回答，不是知识库检索结果
- Docker 日志报错：`Cannot query field "Vector_index_7c1c4496_11d4_49a0_851c_40f09eec984c_Node" on type "GetObjectsObj"`

**根因**：之前用 SQL 直接修改 `documents.indexing_status='completed'` 后，虽然数据库状态标记为完成，但 **Milvus 向量数据库里的索引名称与 Dify 检索配置不匹配**。文档被删除重建或重新上传后，Milvus 中对应的向量记录被清理，但 Dify 的检索配置仍引用旧的索引名。

**排查方法**：
```bash
# 查 Dify API 日志
ssh root@127.0.0.1 "docker logs docker-api-1 --tail 50 2>&1 | grep -i 'Vector_index\|retrieval\|error' | head -10"
```

**修复方案**：
1. 先查 Weaviate READONLY（见上方 Weaviate 向量库磁盘满 章节）
2. 在 Dify Studio 里删除旧文档 → 重新上传 → 等索引完成
3. 如果分段已索引但状态错误，用 SQL 修复状态（见 references/kb-rebuild-workflow.md）

**注意**：这不是知识库内容格式问题，是向量索引损坏。删文档重新上传即可，不要试图手动修复 Weaviate。

### Bug19: Dify 1.15.0 密码 Base64 编码登录（2026-07-29 发现）

**现象**：Dify 1.15.0 升级后，直接用明文密码 POST `/console/api/login` 返回 `{"code":"authentication_failed","message":"Invalid encrypted data"}`。

**根因**：1.15.0 的登录 API 加了 `@decrypt_password_field` 装饰器（`controllers/console/auth/login.py:103`），要求密码字段为 **Base64 编码**。这不是真正加密，只是 Base64 混淆——`libs/encryption.py` 里就是 `base64.b64decode()`。

**修复**：
```bash
echo -n '[REDACTED]' | base64
# → aGRuejYzMjEwMA==
curl -X POST http://127.0.0.1:8081/console/api/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@hdnz.net","password":"aGRuejYzMjEwMA=="}'
```
浏览器前端会自动处理编码，不影响 web 正常使用。

### Bug20: Starsower_v2 Dashboard API 返回 null —— 缺 return 语句（2026-07-29 发现）

**现象**：`/api/admin` 等多个管理端点在浏览器显示 `null` 或空白，数据库有数据。

**根因**：函数执行了查询逻辑但末尾**没有 `return`**，Python 默认返回 `None` → FastAPI 序列化为 `null`。

**排查方法**：逐个检查 `@app.get()` 函数体末尾，确认每个分支都有 `return`。

**修复示例（api_dashboard 缺 return）**：
```python
    db.close()
    # ← 缺了这行！
    return {"total_users": u, "total_conversations": mc, ...}

@app.get("/api/admin/orders")
```

**预防**：
- 新增 API 端点后，确认 `db.close()` 之后有 `return`
- 前端页面加载 `null` 时先检查 API 返回是否为 `null`
- 用 `curl http://localhost:8001/api/admin` 直接调 API 排查

### Bug21: Dashboard API 前端字段名不匹配（2026-07-29 发现）

**症状**：看板 API 返回 200 但卡片显示空白或"-"，浏览器 Network 面板能看到 JSON 数据。

**根因**：后端 API 返回的 JSON 字段名与前端 HTML/JS 模板中读取的字段名不匹配。常见差异：

| 后端返回 | 前端期望 | 后果 |
|---------|---------|------|
| `amount: 19.0` | `total_amount: 19.0` | 付费排行金额为空 |
| `total_amount: 19.0` | `amount: 19.0` | 订单金额为空 |
| `user_name: "..."` | `payer: "..."` | 付款人为空 |
| `conv_count: 244` | `conversation_count: 244` | 活跃用户对话数为空 |
| `avatar_id: "1"` | `teacher_name: "老师甲"` | 老师列为空 |
| `teacher_name: "..."` | `avatar_id: "1"` | 老师列为空 |
| `order_no: "SF..."` | `order_no: "SF..."` (需要 `out_no`) | 订单号为空 |

**排查流程**：
1. 浏览器打开看板 → F12 Network → 找到失败的 API 请求 → 看 Response JSON
2. 对比 HTML 模板中 `render*Table` 函数使用的字段名
3. 用 `curl http://127.0.0.1:8001/api/admin/xxx` 排除 nginx 问题
4. 修复：改后端 API 返回字段名对齐前端，或改前端模板对齐 API

**修复示例**（订单金额字段名不匹配）：
```python
# ❌ API 返回 total_amount，前端期望 amount
"total_amount": round(r["amount"]/100, 2)

# ✅ 改为 amount
"amount": round(r["amount"]/100, 2)
```

**预防**：
- 新增 API 端点后，先 `curl` 看返回字段，再写前端 `render*` 函数
- 前端用 `r.fieldA ?? r.fieldB ?? '-'` 兜底，但不如字段名一致可靠
- 每次改 dashboard.html 的 render 函数后，同步检查 API 返回

**现象**：删除 `/opt/myapp/`（旧 v1 目录）后 starsower_v2 无法启动，报 `No such file or directory: /opt/myapp/venv/bin/python3`

**根因**：starsower_v2 的 start.sh、systemd 服务、部署脚本全写死了 `/opt/myapp/venv/bin/python3`（旧 v1 的 venv），没有自己的独立 venv。

**修复步骤**：
```bash
# 1. 创建独立 venv
python3.12 -m venv /opt/myapp/venv
/opt/myapp/venv/bin/pip install fastapi uvicorn[standard] requests slowapi python-multipart qrcode pillow mem0ai cryptography httpx_oauth wechatpy lxml bs4

# 2. 更新所有调用路径
sed -i 's|/opt/myapp/venv/bin/python3|/opt/myapp/venv/bin/python3|g' /opt/myapp/start.sh
sed -i 's|/opt/myapp/venv/bin/python3|/opt/myapp/venv/bin/python3|g' /etc/systemd/system/starsower_v2.service
systemctl daemon-reload

# 3. 重启
pkill -9 -f 'uvicorn.*8001'
cd /opt/myapp && nohup ./venv/bin/python3 -m uvicorn main:app --host 0.0.0.0 --port 8001 &
```

**预防**：venv 永远放在项目自身目录下，不共享/依赖其他项目的 venv。

### Bug22: Dify 1.15.0 首次 Setup 500 — privkeys 权限（2026-07-29 发现）

**现象**：执行 `/console/api/setup` 返回 500 `Setup failed: PermissionDenied (persistent) at write => permission denied ... privkeys/.../private.pem`

**根因**：1.15.0 在 setup 时生成 JWT 签名私钥，写入 `storage/privkeys/` 目录。存量目录权限不足（root:root 755）。

**修复**：
```bash
chmod -R 777 /opt/dify/docker/volumes/app/storage/
```

### Bug23: Embedding 模型中途调换 → vector lengths don't match（2026-07-31 用户经验）

**铁律：知识库建好后，Embedding 模型不能中间调换！**

- 症状：调换 embedding 模型后检索报 `vector lengths don't match`（如千问 text-embedding-v2 是 1536 维，v3 是 1024 维，旧向量与新查询向量维度不一致）
- 原因：已向量化的分段还是旧模型的维度，新模型生成不同维度的向量，余弦相似度计算时维度不匹配
- **唯一处理方法：删掉知识库重新上传**（重新向量化全部内容）
- 预防：建库前就定好 embedding 模型（本项目固定用千问 text-embedding-v3），中途绝不更换；不同版本（v2/v3）也不能混用

### Bug24: MiniMax 大模型配置到 Dify 1.16.1 的 API URL 铁律（2026-07-31 用户确认）

**配置 Dify 1.16.1 + MiniMax 大模型（LLM）时，API Base URL 必须填：**
```
https://api.minimaxi.com/anthropic
```
- 不能留默认值 `https://api.minimax.io`（国际站，国内 Token Plan Key 不通）
- 不能只填 `https://api.minimaxi.com`（插件会强制追加 /anthropic，但显式写全最稳）
- 与 Bug30 同源：MiniMax 插件 v0.0.23 走 Anthropic 兼容 API，`_to_credential_kwargs()` 会检查 endpoint 是否以 /anthropic 结尾，不结尾则追加。填 `https://api.minimaxi.com/anthropic` 正好命中，走国内 Anthropic 兼容通道直接全通。

### Bug25: Dify 部署域名——根目录比子路径稳定（2026-07-31 用户确认）

**经验**：Dify 登录页/控制台放在**网址根目录**（如 `hdnz.net`）不容易出错；从 `example.com/dify` 子路径转到 `hdnz.net` 根目录后才稳定下来。与既有结论一致：子路径(/dify/)走不通——Next.js basePath 编译时写死，sub_filter/proxy_redirect/JS patch/Docker patch 都不可靠。部署新 Dify 直接绑定根域名，避免子路径。

### Bug26: Dify 1.16.1 知识库上传 API 三步坑（2026-07-31 实测）

**症状**：用旧版方式（JSON body + base64 直传）调 1.16.1 上传文档 API，报 401/400。

**坑1：登录改用 cookie 会话**。1.16.1 的 `/console/api/login` 返回 `{"result":"success"}`，access_token 在 **Set-Cookie** 里（`__Host-access_token`、`__Host-csrf_token`、`__Host-refresh_token`），不在响应 body。旧版"body 里拿 access_token"的脚本全废。

**坑2：`__Host-` cookie 带 Secure 标志，http 请求（127.0.0.1 内网）requests/curl 不会自动发送**。CSRF 校验要求 header `X-CSRF-Token` == cookie 里的 csrf token，cookie 不发 → 永远 `401 CSRF token is missing or invalid`。
**解决**：登录后用 session cookie jar 取 csrf，**手动构造 Cookie header** 强制发送：
```python
csrf = s.cookies.get("__Host-csrf_token")
cookie_hdr = "; ".join(f"{c.name}={c.value}" for c in s.cookies)
headers = {"Cookie": cookie_hdr, "X-CSRF-Token": csrf, "Origin": "https://example.com"}
```
参考：`/app/api/libs/token.py` 的 `_real_cookie_name()`（secure+无域 → `__Host-` 前缀）、`check_csrf_token()`（header==cookie 才通过）。

**坑3：上传 API 改成两步**。旧版 `file`+`file_name` base64 直传报 `400 Data source is required`。1.16.1 正确流程：
```python
# Step1: multipart 上传文件 → 拿 file_id
r1 = requests.post(f"{BASE}/console/api/files/upload", headers=H(),
    files={"file": ("x.md", f, "text/markdown")})
file_id = r1.json()["id"]

# Step2: data_source 结构建文档（info_list 里也要有 data_source_type！）
payload = {
    "indexing_technique": "high_quality",
    "data_source": {
        "data_source_type": "upload_file",
        "info_list": {"data_source_type": "upload_file",
                      "file_info_list": {"file_ids": [file_id]}}
    },
    "process_rule": {"mode": "custom", "rules": {"pre_processing_rules": [
        {"id": "remove_extra_spaces", "enabled": True}],
        "segmentation": {"separator": "\n\n", "max_tokens": 500}}},
    "doc_form": "text_model",
}
# info_list 缺 data_source_type 会报 pydantic validation error
```
参考：`/app/api/services/dataset_service.py:2238`（Data source is required）。

**⚠️ 分段模式决定问答是否合并**：
- 选「Q&A」分段模式 → Dify 把「问」「答」**强制拆成两个独立 chunk**（这就是之前检索只命中问句、答案丢失的根因！）
- 选「段落」模式（separator=\n\n）→ 「问\n答」相邻的问答对**合并为一个 chunk** ✅
- 文件格式：`问：xxx\n答：xxx`（对内单换行，对间空行）即可，无需改文件，只需上传时选对分段模式

**验证**：
```sql
SELECT s.position, LEFT(s.content, 120), s.word_count
FROM document_segments s WHERE s.dataset_id='<ds_id>' AND s.content LIKE '%心悸%' ORDER BY s.position;
-- 期望：content 同时含 问：xxx 和 答：xxx（合并），而非只有问句
```

### Bug27: 召回测试能搜到知识库，但 Studio 对话读不到——缺 `{{#context#}}` 变量（2026-07-30 实测）

**现象**：Dify Studio 知识库「召回测试」能正确命中内容，但聊天对话时模型回答不引用知识库（模型自己编），回复"暂无相关知识"。

**根因**（两重可能，依次排查）：

**第一重：App 的 pre_prompt 里没有 `{{#context#}}` 变量。** Dify 通过这个变量把知识库检索结果注入到提示词中。没有它，模型收到"参考知识库回答"的指令但知识根本没传进去。

**第二重：score_threshold（召回阈值）过高。** 即使有 `{{#context#}}`，如果检索结果的相似度分数低于 `score_threshold`，仍然会被过滤掉，模型收到的上下文为空。

**排查**：
```sql
-- 检查 {{#context#}}
SELECT pre_prompt LIKE '%#context#%' AS has_context_var
FROM app_model_configs WHERE app_id = '<app_id>'
ORDER BY created_at DESC LIMIT 1;
-- f → 缺变量

-- 检查 score_threshold
SELECT retrieval_model::json->>'score_threshold' AS threshold,
       retrieval_model::json->>'score_threshold_enabled' AS enabled
FROM datasets WHERE id = '<dataset_id>';
-- 如果 > 0.3 且检索结果偏少，考虑降低
```

**修复**：
1. 在 Dify Studio → 编辑 App → pre_prompt 最前面加上 `{{#context#}}`
2. 知识库 → 检索设置 → 把 **召回阈值（Score Threshold）** 适当降低（如 0.2~0.3），或直接关掉

或用 SQL：
```sql
UPDATE app_model_configs
SET pre_prompt = '{{#context#}}\n\n' || pre_prompt,
    updated_at = NOW()
WHERE id = '<config_id>';

UPDATE datasets
SET retrieval_model = jsonb_set(retrieval_model::jsonb, '{score_threshold}', '0.2'::jsonb)
WHERE id = '<dataset_id>';

-- 然后重启 docker-api-1
```

### Dify 版本稳定性参考（2026-07-30 更新）

**前置检查**：
```bash
docker inspect docker-weaviate-1 --format '{{.Config.Image}}'  # 检查 Weaviate 版本兼容性
docker images | grep dify  # 检查本地是否有目标版本镜像
```

**通用流程**：
```bash
cd /opt/dify/docker
cp docker-compose.yaml docker-compose.yaml.bak
docker exec docker-db-1 pg_dump -U postgres dify > /opt/dify_backup.sql
sed -i 's|image: langgenius/dify-api:.*|image: langgenius/dify-api:TARGET_VERSION|g' docker-compose.yaml
sed -i 's|image: langgenius/dify-web:.*|image: langgenius/dify-web:TARGET_VERSION|g' docker-compose.yaml
docker compose stop api web worker nginx plugin_daemon
docker compose up -d api web worker nginx plugin_daemon
sleep 20
```

**版本切换后修复清单**（视目标版本而定）：
1. Docker nginx 443端口冲突 → `.env` 中 `EXPOSE_NGINX_SSL_PORT=4443`
2. 宿主机nginx配SSL接管443
3. `chmod -R 777 storage/`（1.15+ 需要）
4. 登录密码 Base64 编码（1.15+ 需要）
5. **Weaviate 版本检查** — 见 `references/weaviate-version-upgrade.md`

**回滚方案**：
```bash
docker compose stop api web worker
docker exec docker-db-1 psql -U postgres -c "DROP DATABASE IF EXISTS dify WITH (FORCE);"
docker exec docker-db-1 psql -U postgres -c "CREATE DATABASE dify;"
cd /opt/dify/docker && git checkout docker-compose.yaml
docker compose up -d
```

### 高质量建库但向量/混合检索在 UI 中报错，仅全文检索可用（2026-07-31 新增）

**症状**：知识库建库选了「高质量」，Embedding 模型在模型供应商里显示已连接，但检索设置里选向量检索或混合检索就报错，只有全文检索可选或可用。

**根因链**：高质量 → Worker 调用 Embedding → 向量写入 Weaviate → 这一步失败 → 文档标记为 `completed` 但向量不存在 → 切换向量/混合检索时报错。

**三种可能性（从高到低）**：

1. **Weaviate 版本过旧** — Dify 1.16.1 要求 Weaviate ≥1.27.0, docker-compose 锁的是 1.19.0, Worker 无法写入向量 (Bug31)。GitHub [#27291](https://github.com/langgenius/dify/issues/27291): 升级后报 `does not have named vector default configured`
2. **Weaviate 磁盘满→READONLY** — 向量写不进去，全文 BM25 不受影响
3. **Worker 调用 Embedding API 失败**（RPM 限流等）— 文档标记了 `completed` 但 `segment.index_node_id` 为空。GitHub [#25084](https://github.com/langgenius/dify/issues/25084): `Cannot query field "Vector_index_xxx_Node"`——向量不存在时调向量检索的典型报错

**诊断**：
```sql
-- 查出向量索引是否真的写入了
SELECT ds.name, COUNT(*) AS total_segs,
       SUM(CASE WHEN s.index_node_id IS NOT NULL THEN 1 ELSE 0 END) AS indexed_segs
FROM datasets ds
JOIN document_segments s ON s.dataset_id = ds.id
WHERE ds.name = '<知识库名>'
GROUP BY ds.name;
```
- `indexed_segs = total_segs` → 向量已写入, 问题在检索链路（查 Weaviate 日志）
- `indexed_segs = 0` → 向量根本没写入, 检查 Weaviate 版本和磁盘

**修复**：删文档→升级 Weaviate→重上传（见 Bug31 修复流程）

### 知识库检索静默失败诊断流程（2026-07-30 更新）

当用户反馈"AI回答不是知识库内容"或上传文档状态为"错误/排队中"时，按此顺序排查：

1. **Weaviate 版本兼容性** — `docker inspect docker-weaviate-1 --format '{{.Config.Image}}'`，Dify 1.16.1 需要 ≥1.27.0（见 Bug31）
2. **Weaviate READONLY** — `docker logs docker-weaviate-1 2>&1 | grep READONLY`
3. **向量索引名不匹配** — `docker logs docker-api-1 2>&1 | grep 'Cannot query field'`
4. **分段未索引** — 查 `document_segments` 表 `index_node_id` 是否为空
5. **文档状态错误** — `indexing_status` 是否为 `completed`
6. **内容格式** — chunk 是否字段堆砌（应转 Q&A）
7. **weights 配置缺失（Bug27）** — 若向量链路全健康但「权重设置」模式检索不到、Rerank 模式正常，查 `datasets.retrieval_model` JSON 的 `weights.vector_setting` 是否缺 embedding 模型名/提供方

80% 的情况是 (1)+(2) 叠加。先清磁盘 → 重启Weaviate → 重上传文档。

### Bug28: 混合检索「权重设置」检索不到，Rerank 模式正常（2026-07-31 实测）

**现象**：知识库检索设置里选「权重设置」(weighted_score) → 检索不到内容；选「Rerank 模型」→ 正常。向量链路本身健康（Weaviate 版本对、磁盘正常、分段全部已向量化 324+324+455、worker 无错）。

**根因**：`datasets.retrieval_model` JSON 中 `weights.vector_setting.embedding_model_name` / `embedding_provider_name` 为空。weighted_score 模式计算混合分数依赖这段配置；为空 → 向量分支分数算不出 → 加权结果为空。Rerank 模式走独立的 `reranking_model`（如 qwen3-rerank/gte-rerank-v2）重排，**不依赖 weights 配置**，所以正常。

**诊断 SQL**：
```sql
SELECT name,
       retrieval_model::json->'weights'->'vector_setting'->>'embedding_model_name' AS emb_model,
       retrieval_model::json->'weights'->'vector_setting'->>'embedding_provider_name' AS emb_provider
FROM datasets ORDER BY name;
-- 正常: text-embedding-v3 / langgenius/tongyi/tongyi；异常: 空值
```

**修复**：UPDATE `datasets.retrieval_model` 补齐与正常知识库一致的 embedding 模型名和提供方（jsonb_set 改 JSON，改完重启 docker-api-1）。

**⚠️ 实操坑（2026-07-31 实测）**：`ssh "docker exec psql -c \"...jsonb_set...'\"\"text-embedding-v3\"\"'...\""` 三层引号嵌套必炸（报 `invalid input syntax for type json`，Token "text" is invalid）。**正确做法：本地写 SQL 文件 → scp 到服务器 → docker cp 进 db 容器 → psql -f 执行**：
```bash
# 本地 /tmp/fix.sql 内容：
# UPDATE datasets SET retrieval_model = jsonb_set(
#   jsonb_set(retrieval_model::jsonb, '{weights,vector_setting,embedding_model_name}', '"text-embedding-v3"'::jsonb),
#   '{weights,vector_setting,embedding_provider_name}', '"langgenius/tongyi/tongyi"'::jsonb)
# WHERE name IN ('老师甲经验2', '老师甲经验3');
scp /tmp/fix.sql root@SERVER:/tmp/fix.sql
ssh root@SERVER "docker cp /tmp/fix.sql docker-db-1:/tmp/fix.sql && docker exec docker-db-1 psql -U postgres -d dify -f /tmp/fix.sql"
docker restart docker-api-1  # 刷新缓存
```
改库前先备份：`CREATE TABLE datasets_bak_YYYYMMDD AS SELECT * FROM datasets;`（2026-07-31 已备份 datasets_bak_0731）。

**GitHub 佐证**：#14973（权重设置无结果）、#31215（权重模式 0 结果，score 缺失被过滤）、#13426（weighted_score 配置难设；前端逻辑：全部数据集 high quality+同 embedding 才允许 WeightedScore，否则回退 RerankingModel）、#25084（economy 模式配 semantic_search 报 Vector_index 错）、#27291（Dify 升级后旧知识库向量不可用）。

详见 `references/hybrid-search-weights-issue.md`

### Bug29: MiniMax embo-01 embedding 模型在 1.16.1 不被识别（2026-07-31 诊断中）

**症状**：Dify 1.16.1 界面里 MiniMax 的 embedding 模型选不到/不被识别。

**🔴 命名陷阱**：模型名是 **`embo-01`（字母 o）**，不是 `emb0-01`（数字 0）！插件代码硬校验 `if model != "embo-01": raise ValueError("Invalid model name")`（`models/text_embedding/text_embedding.py`）。数字0/字母o打错直接不认。

**诊断结果**：
- 插件 v0.0.23 本身支持 embedding：`/app/storage/cwd/langgenius/minimax-0.0.23@913a242.../models/text_embedding/embo-01.yaml`（context_size 4096, max_chunks 1）
- `providers` 表：provider `langgenius/minimax/minimax` is_valid=t 且 credential_id 非空（凭据已配）
- 但 `provider_models` 表里 MiniMax 模型 **0 行记录** → embedding 模型没注册进 Dify 模型注册表 → UI 下拉看不到
- 调用端点：`{endpoint_url}/v1/embeddings?GroupId={group_id}`，body `{"model":"embo-01","texts":[...],"type":"db|query"}`（type：文档入库用 `db`，查询用 `query`）
- 默认 endpoint_url：`https://api.minimax.chat/`（配置里可改，国内走 `api.minimaxi.com`）

**诊断 SQL**：
```sql
SELECT model_name, model_type, is_valid, credential_id IS NOT NULL AS has_cred
FROM provider_models WHERE provider_name LIKE '%minimax%';
-- 0 行 = embedding 模型未注册
```

**表结构（1.16.1，猜列名会报 column does not exist，先查 information_schema）**：
- `provider_models`：id, tenant_id, provider_name, model_name, model_type, is_valid, created_at, updated_at, credential_id
- `providers`：id, tenant_id, provider_name, provider_type, is_valid, last_used, quota_type, quota_limit, quota_used, created_at, updated_at, credential_id
- ⚠️ 两表都**没有** encrypted_config 列；查凭据是否配置看 `credential_id IS NOT NULL`

**修复方向**：
1. Dify 界面「设置→模型供应商→MiniMax」里手动添加 embedding 模型（若列表有 embo-01）
2. 界面没有则 INSERT `provider_models` 一条 embo-01 记录（需正确的 tenant_id + credential_id）

### Bug30: plugin_daemon 容器消失 → docker-nginx 启动失败 → 所有 API 调用 502

**现象**：Dify 页面显示「渲染此组件时发生了意外错误」。后端 API 全部返回 502 Bad Gateway。

**诊断链**：
```bash
# 1. 查 docker-nginx 日志，看 upstream 错误
docker logs docker-nginx-1 2>&1 | grep -E 'connect\\(\\) failed|host not found'
# 典型输出（两步）：
#   ❌ 第一步：connect() failed (113: No route to host) → upstream: "http://172.23.0.9:5001/api/..."
#   ❌ 第二步（如重启过 nginx）：host not found in upstream "plugin_daemon"
#         → nginx 根本起不来，所有请求打 502

# 2. 确认 plugin_daemon 是否存活
docker ps | grep plugin
# 空输出 = plugin_daemon 容器不存在/已停止

# 3. 查 API 容器实际 IP
docker inspect docker-api-1 --format "{{.NetworkSettings.Networks.docker_default.IPAddress}}"
# 与 nginx 日志里的旧 IP 对比（如上例 172.23.0.7 ≠ 172.23.0.9）
```

**根因**（两个问题叠加，缺一不可）：
1. **plugin_daemon 容器意外停止**（OOM/磁盘满/未知原因退出），未被 `restart: always` 自动拉起
2. **API 容器重启后 IP 改变**，但 docker-nginx 的 DNS 缓存仍是旧 IP（nginx 默认只在启动时解析一次 `api` hostname）
3. 有人重启 docker-nginx 试图修复 API 502 → 因 plugin_daemon 不存在，nginx 启动时报 `host not found in upstream "plugin_daemon"`，**完全拒绝启动** → 所有请求 502

**修复步骤**：
```bash
# 步骤1：清理旧 plugin_daemon 容器
docker rm docker-plugin_daemon-1

# 步骤2：重新创建并启动 plugin_daemon
cd /opt/dify/docker && docker compose up -d plugin_daemon

# 步骤3：重启 docker-nginx（刷新 DNS 缓存）
docker restart docker-nginx-1

# 验证
curl -s -o /dev/null -w "%{http_code}" https://hdnz.net/console/api/system-features
# 期望：401（未登录）非 502
curl -s -o /dev/null -w "%{http_code}" https://hdnz.net/signin
# 期望：200
```

**关键区别**：
- 和 Bug8（nginx 路由到旧 web IP）不同：Bug8 是 nginx 运行中路由到旧容器 IP；本 bug 是 plugin_daemon 不存在导致 nginx **完全无法启动**
- 本 bug 的 502 来自 **host nginx** 而非 docker-nginx（因为 docker-nginx 根本没起来）

### Bug31: MiniMax 凭据验证失败 "invalid api key"——Dify 插件 v0.0.23 使用 Anthropic 兼容 API 存在认证 Bug

**现象**：Dify 配置 MiniMax 模型凭据时，UI 报「渲染此组件时发生了意外错误」，后端日志：
```
CredentialsValidateFailedError: Error code: 401 - {'type': 'error', 'error': {'type': 'authentication_error', 'message': 'invalid api key'}}
```
用户确认 Key 从 MiniMax 控制台新生成、粘贴完整。但仍报错。

**诊断链路（2026-07-30 实测）**：

1. 确认 Key 本身有效：用 OpenAI 兼容端点测试
   ```bash
   curl -s -w "\nHTTP:%{http_code}" https://api.minimaxi.com/v1/chat/completions \
     -H "Content-Type: application/json" \
     -H "Authorization: Bearer $KEY" \
     -d '{"model":"MiniMax-M3","messages":[{"role":"user","content":"hi"}],"max_tokens":3}'
   ```
   ✅ 200 + choices → Key 有效
   ❌ 401 + "invalid api key (2049)" → 截断/过期

2. 检查 Dify MiniMax 插件代码（`/app/storage/cwd/langgenius/minimax-0.0.23@.../`）：

   **`provider/minimax.py`** 调用链：
   ```python
   def validate_provider_credentials(self, credentials):
       model_instance = self.get_model_instance(ModelType.LLM)
       model_instance.validate_credentials(model="minimax-m2.5", credentials=credentials)
   ```

   **`models/llm/llm.py`** `validate_credentials` 方法：
   ```python
   def validate_credentials(self, model, credentials):
       request_model = self._resolve_model_name(model)
       credentials_kwargs = self._to_credential_kwargs(credentials)
       client = Anthropic(**credentials_kwargs)  # 使用 Anthropic SDK！
       client.messages.create(model=request_model, max_tokens=8, ...)
   ```

   **`_to_credential_kwargs()`** 构造认证参数：
   ```python
   endpoint_url = str(credentials.get("endpoint_url") or "https://api.minimax.io").strip()
   if not endpoint_url.endswith("/anthropic"):
       endpoint_url = f"{endpoint_url}/anthropic"  # 强制追加 /anthropic
   return {
       "api_key": api_key,
       "base_url": endpoint_url,          # → https://api.minimax.io/anthropic
       "default_headers": {
           "Authorization": f"Bearer {api_key}",
       },
   }
   ```

3. **根因**：MiniMax Anthropic 兼容 API 端点 `https://api.minimax.io/anthropic/v1/messages` 存在认证 header 识别 Bug。

   - Anthropic SDK 发送 `x-api-key`（小写 x）header
   - MiniMax 要求 `X-Api-Key`（大写 X+大写 A），但即使 curl 发大写 X-Api-Key，仍返回：
     ```
     "login fail: Please carry the API secret key in the 'X-Api-Key' field"
     ```
   - `https://api.minimax.io/anthropic` → 301 跳转 `/anthropic/` → 404
   - `https://api.minimaxi.com/anthropic/v1/messages` 同样问题
   - **OpenAI 兼容端点** `https://api.minimaxi.com/v1/chat/completions` 用 `Authorization: Bearer` 完全正常

4. **结论**：Dify MiniMax 插件 v0.0.23 的 Anthropic 兼容 API 实现与 MiniMax 生产接口不兼容，认证 header 无法识别。**不是用户 Key 的问题**。

**修复方案**（按优先级，2026-07-30 实测有效）：

1. **手动改 API Base URL（已验证可行）**：在 Dify MiniMax 插件配置里，把 **API Base URL** 从默认的 `https://api.minimax.io` 改为 **`https://api.minimaxi.com/anthropic`**（国内 Token Plan Key 专用），直接全通。

   原理：插件 `_to_credential_kwargs()` 会判断 endpoint 是否以 `/anthropic` 结尾，没有则追加。填 `https://api.minimaxi.com/anthropic` 正好命中不再拼接，走国内 `minimaxi.com` 的 Anthropic 兼容 API。

2. **更新 MiniMax 插件** — 去 Dify 后台「插件」→「市场」检查 MiniMax 插件是否有新版（改用 OpenAI 兼容 API）

3. **换用千问（Tongyi）插件** — Dify 已装的 `tongyi:0.1.48` 使用千问工作空间 Key，更稳定

4. **OpenAI API Compatible 绕过**：如果必须用 MiniMax，Dify → 模型提供商 → 使用「OpenAI API Compatible」类型（而非 MiniMax 专属插件），填：
   - API Key: MiniMax API Key
   - Base URL: `https://api.minimaxi.com/v1`
   - 模型名: `MiniMax-M3`

**验证（区分 Key 有效 vs 插件 Bug）**：
```bash
# 始终先用这个测 Key 本身是否有效
curl -s -w "\nHTTP:%{http_code}" https://api.minimaxi.com/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $KEY" \
  -d '{"model":"MiniMax-M3","messages":[{"role":"user","content":"hi"}],"max_tokens":3}'
# ✅ 200 = Key 有效
# ❌ 401 + "invalid api key (2049)" = Key 本身无效（截断/过期）

# ⚠️ 如果 Key 有效但 Dify MiniMax 插件仍报错 → 是插件 Anthropic API 的问题
```

**文件位置**：
- 插件代码：`/app/storage/cwd/langgenius/minimax-0.0.23@913a242.../`
- 插件 manifest：同目录下 `manifest.yaml`（`provider_credential_schema` 定义了凭据表单）
- LLM 模型实现：`models/llm/llm.py`（validate_credentials 第149行 + _to_credential_kwargs 第918行）
- 插件默认 endpoint：`https://api.minimax.io`（国际），`https://api.minimaxi.com`（中国需手动填）

### Bug32: Dify 1.16.1 文档上传后状态"错误"或"排队中"——Weaviate 版本过旧（2026-07-30 实测）

**现象**：知识库上传文档后，状态一直是"排队中"或变成"错误"。Worker 日志报：
```
Weaviate version 1.19.0 is not supported. Please use Weaviate version 1.27.0 or higher.
```

**根因**：Dify 升级到 1.16.1 后要求 Weaviate ≥1.27.0，但 `docker-compose.yaml` 里写死的 `weaviate:1.19.0` 未更新。Worker 根本无法执行 embedding 操作，所有文档索引失败。

**诊断**：
```bash
docker inspect docker-weaviate-1 --format '{{.Config.Image}}'
docker logs docker-worker-1 2>&1 | grep -i "weaviate version"
```

**修复**：
```bash
docker pull semitechnologies/weaviate:1.27.0
sed -i 's|image: semitechnologies/weaviate:1.19.0|image: semitechnologies/weaviate:1.27.0|g' /opt/dify/docker/docker-compose.yaml
docker compose -f /opt/dify/docker/docker-compose.yaml stop weaviate worker
docker compose -f /opt/dify/docker/docker-compose.yaml rm -f weaviate
docker compose -f /opt/dify/docker/docker-compose.yaml up -d weaviate worker
```
**数据兼容性**：Weaviate 1.19.0 → 1.27.0 在同一主版本线内，数据卷兼容，无需重建向量索引。升级后原有文档即可正常处理。

**预防**：升级 Dify 版本后，务必同步检查 Weaviate/Qdrant 向量数据库版本是否满足新版本要求。：Host nginx vs Docker nginx（2026-07-29）

**问题**：Dify Docker nginx 和 Host nginx 同时需要 443 端口用于 HTTPS，产生冲突。

**架构选择**：让 Host nginx 接管 443，Docker nginx 映射到 4443。

```bash
# 1. 停止 Docker nginx
docker compose -f /opt/dify/docker/docker-compose.yaml stop nginx

# 2. 启动 Host nginx 绑定 443（需 ssl_certificate 配置）
systemctl restart nginx
# 验证：ss -tlnp | grep ':443 ' | grep nginx

# 3. 修改 Docker nginx 端口映射（去掉 443 冲突）
sed -i 's/EXPOSE_NGINX_SSL_PORT=443/EXPOSE_NGINX_SSL_PORT=4443/' /opt/dify/docker/.env
cd /opt/dify/docker && docker compose rm -sf nginx && docker compose up -d nginx
# 验证：docker-nginx-1 端口为 8081->80, 4443->443
```

**注意**：Host nginx SSL 需要 ssl_certificate（Let's Encrypt）和 ssl_certificate_key 指向证书文件。Docker nginx 内部只做路由分发。

### Dify 1.15.0 全新初始化流程

DB 重置后必须按顺序走 init → setup：
```bash
# 1. 删库重建
docker exec docker-db-1 psql -U postgres -c "DROP DATABASE IF EXISTS dify WITH (FORCE);"
docker exec docker-db-1 psql -U postgres -c "CREATE DATABASE dify;"
docker restart docker-api-1
sleep 20

# 2. init（拿 session cookie）
curl -c /tmp/cookies.txt -X POST http://127.0.0.1:8081/console/api/init \\
  -H 'Content-Type: application/json' \\
  -d '{"password":"starsower2026"}'

# 3. setup（用 cookie 创建管理员）
curl -b /tmp/cookies.txt -X POST http://127.0.0.1:8081/console/api/setup \\
  -H 'Content-Type: application/json' \\
  -d '{"email":"admin@hdnz.net","name":"[作者]","password":"[REDACTED]"}'
# 如果返回 500 → chmod -R 777 存储目录，重试

# 4. 登录验证（密码必须 base64）
PWD=$(echo -n '[REDACTED]' | base64 -w0)
curl -X POST http://127.0.0.1:8081/console/api/login \\
  -H 'Content-Type: application/json' \\
  -d "{\"email\":\"admin@hdnz.net\",\"password\":\"$PWD\"}"
```

### Bug47: 直接改 Dify App 系统提示词（pre_prompt）——禁止自我介绍实战（2026-07-31 实测）

**场景**：AI 分身回复出现"哈喽呀！我是老师甲AI分身"开场白，需改 Dify 应用的系统提示词（模型层）+ 后端输出层兜底（代码层）双管齐下。

**表结构与定位当前生效配置**：
- 应用：`apps` 表（`id, name, mode, app_model_config_id`）
- 提示词：`app_model_configs.pre_prompt`——**同一 app 有 N 条历史配置**（本实例 8 条），只有 `apps.app_model_config_id` 指向的那条生效
```sql
-- 1. 找 app
SELECT id, name FROM apps WHERE name LIKE '%老师甲%';
-- 2. 找当前生效的配置
SELECT app_model_config_id FROM apps WHERE id='<app_id>';
-- 3. 看提示词
SELECT pre_prompt FROM app_model_configs WHERE id='<config_id>';
```

**⚠️ SSH 嵌套 $() 陷阱（血泪教训）**：`ssh root@host "docker exec ... $(...)"` ——双引号内的 `$(...)` 会被**本地 shell 先展开**，本地没有 docker 就报 `command not found`。绝不在 ssh 双引号里嵌套 $()。

**✅ 干净做法：本地写 SQL 文件 → stdin 管道喂 psql**（无引号地狱）：
```bash
# 本地 /tmp/fix.sql：
# UPDATE app_model_configs SET pre_prompt = replace(
#   pre_prompt, '<旧文本>', '<新文本>') WHERE id='<config_id>';
# SELECT substr(pre_prompt, position('11.' in pre_prompt), 200) FROM app_model_configs WHERE id='<config_id>';
ssh root@example.com "docker exec -i docker-db-1 psql -U postgres -d dify -v ON_ERROR_STOP=1" < /tmp/fix.sql
```
- replace 的旧文本必须与 DB 完全一致（含全角引号）；拿不准时用**短唯一子串**做 replace 目标
- 改库前先备份：psql `\o /tmp/prompt_backup.txt` + SELECT 导出
- 提示词改完下次对话请求即生效；若 Dify 有缓存（界面看不到变化）再 `docker restart docker-api-1`

**用户偏好：提示词+代码双层保障**。模型不听话时（提示词已写"没问你是谁不自我介绍"仍输出），必须加代码级强制过滤：chat.py 回复后处理链 `_apply_redline → _apply_policy_guard → _strip_self_intro`，用户没问"你是谁/你叫什么/你是哪位/哪个老师"时用正则删"哈喽呀"和"我是XXAI分身"句（详见 starsower-platform-ops 的内容过滤节）。



**现象**：Starsower_v2 `/api/chat` 返回通用回答（非知识库内容），但直连 Dify API 用正确 Key 能正常检索。

**根因（修正）**：`llm.py` 的 `_get_dify_token()` 从 **SQLite `app_settings` 表**读取 Token，不是从 `.env` 文件或进程环境变量。Dify Studio 重新生成 Key 后，`.env` 已更新，但 SQLite 里的旧 Key 未同步，导致 `call_llm()` → 旧 Key → 401 → fallback DeepSeek（无知识库检索）。

**Token 三处存储（优先级 = 实际代码读取顺序）**：

| 位置 | 读取代价 | `llm.py` 是否读取 |
|------|---------|------------------|
| **SQLite `app_settings`** | `_get_dify_token()` | ✅ **唯一读取源** |
| `.env` 文件 | `os.getenv("DIFY_KEY_XXX")` | ❌ `llm.py` 不读，仅 `dify_proxy.py` 读 |
| 进程环境变量 | `/proc/PID/environ` | ❌ `llm.py` 不读 |

**三重验证诊断命令**（定位 Token 不同步问题）：
```bash
# 从服务器一次性对比三处
ssh root@127.0.0.1 "
echo '=== SQLite ==='
sqlite3 /opt/myapp/soulfire_v2.db \"SELECT key, substr(value,1,45) FROM app_settings WHERE key LIKE '%dify%';\"
echo '=== .env ==='
grep DIFY_KEY /opt/myapp/.env
echo '=== 进程环境 ==='
cat /proc/\$(ps aux | grep 'uvicorn.*8001' | grep -v grep | awk '{print \$2}' | head -1)/environ | tr '\0' '\n' | grep DIFY_KEY
echo '=== 直连验证（旧Key） ==='
curl -s --max-time 5 -X POST 'http://127.0.0.1:8081/v1/chat-messages' -H 'Authorization: Bearer app-[REDACTED]' -H 'Content-Type: application/json' -d '{\"query\":\"t\",\"response_mode\":\"blocking\",\"user\":\"x\",\"inputs\":{}}' | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d.get(\"code\",\"OK\"), d.get(\"message\",\"\")[:40])'
echo '=== 直连验证（新Key） ==='
curl -s --max-time 5 -X POST 'http://127.0.0.1:8081/v1/chat-messages' -H 'Authorization: Bearer app-[REDACTED]' -H 'Content-Type: application/json' -d '{\"query\":\"t\",\"response_mode\":\"blocking\",\"user\":\"x\",\"inputs\":{}}' | python3 -c 'import sys,json; d=json.load(sys.stdin); print(\"OK:\", d.get(\"answer\",\"\")[:30])'
"
```

**正确 Key（2026-07-29 实测）**：
| 分身 | 正确 API Key |
|------|------------|
| 老师甲 | `app-[REDACTED]` |
| 老师乙 | `app-[REDACTED]` |
| 老师丁 | `app-[REDACTED]` |
| 老师戊 | `app-[REDACTED]` |
| 老师丙 | `app-[REDACTED]` |

**⚠️ 每次在 Dify Studio 重新生成 API Key 后，必须同步更新 SQLite `app_settings` 表！改 `.env` 不够，`llm.py` 不读 `.env`！**

**一键修复**：
```bash
ssh root@127.0.0.1 "sqlite3 /opt/myapp/soulfire_v2.db \"UPDATE app_settings SET value='<new_token>' WHERE key='dify_token_<avatar>'\""
# 然后 kill -9 重启进程



### Bug34: 知识库检索失败——两重根因（Weaviate索引损坏 + chunk格式不对，2026-07-29确认）

**现象**：Dify 知识库文档状态 `completed`，chunks 已向量化（227条），但问"左脚红肿疼痛91岁女"返回通用回答，检索未命中具体案例。

**根因1（直接根因）**：Milvus 向量索引名不匹配。
- Docker 日志报错：`Cannot query field "Vector_index_7c1c4496_11d4_49a0_851c_40f09eec984c_Node"`
- 之前用 SQL 直接修改 `indexing_status='completed'` 后，Milvus 里的向量记录/索引名与 Dify 检索配置不一致
- **这不是 chunk 内容问题，是向量库层面损坏**

**根因2（加重因素）**：chunk 是「字段堆砌格式」，不是 Q&A 格式。
- 上传的 chunk 内容：`【案例】id：CASE-009；condition：...；symptoms：[...]；acupoints：[...]...`
- 用户问自然语言，和整段包含几十个字段的 chunk 做向量相似度，匹配率低

**两重修复都要做**：

1. **先修 Milvus**（在 Dify Studio 操作）：
   - 删除旧文档（彻底删除，不是只改状态）
   - 重新上传 Q&A 格式文件
   - 等索引完成

2. **再转 Q&A 格式**（已生成）：
   - `D:\AI\AI产品\25 AI经验平台经验\最终知识库上传\老师甲经验精炼_QA.md`（162条）
   - 其他4个老师的 `_QA.md` 也已生成

**⚠️ 2026-07-31 修正：上传分段格式用「段落」，不要用「Q&A」模式！**
- 实测：Dify 的 Q&A 分段模式会强制把每个「问」「答」拆成独立 segment（324 段 = 162问+162答），检索时用户问题与"问"文本重合度高，答案 chunk 全被截掉 → 模型说"经验里没有"（详见 Bug40）
- **正确做法**：分段格式选「段落」，本地文件保持「问：xxx\n答：xxx\n\n问：yyy」格式，问答对自动合并为一个 chunk

**⚠️ 教训**：
- 用 SQL 直接改 `indexing_status` 只能骗过 UI，Milvus 向量库状态不会同步
- 以后删文档必须从 Dify Studio 彻底删，不能只改数据库
```bash
ssh root@127.0.0.1 "docker logs docker-api-1 --tail 30 2>&1 | grep -i 'Vector_index\|retrieval' | head -5"
```

**正确上传步骤**：
1. Dify Studio 打开知识库 → 删除旧文档
2. 上传 `_QA.md` 文件
3. **分段格式选「段落」**（不要选「Q&A」，见上）
4. 等索引完成（状态变 `completed`）再测

**⚠️ 之前上传的文档是「段落」模式，内容也是字段堆砌格式，必须重新上传 Q&A 格式才能解决检索问题**

详见：`references/qa-conversion-workflow.md`
### Bug35: MiniMax Embedding RPM 超限导致索引失败（2026-07-28，2026-07-28二次实测）

- 现象：上传成功但索引状态=`error`，错误信息 `[models] Rate Limit Error, rate limit exceeded(RPM)`
- worker 日志：`InvokeRateLimitError: [models] Rate Limit Error, rate limit exceeded(RPM)` at `cached_embedding.py:98` → `indexing_runner.py:96`

**⚠️ 核心判断：先查分段是否已索引，再决定修复策略**

```sql
-- 第一步：检查分段是否已完成向量索引
SELECT ds.name AS dataset,
       COUNT(*) AS total_segs,
       SUM(CASE WHEN s.index_node_id IS NOT NULL THEN 1 ELSE 0 END) AS indexed_segs
FROM datasets ds
JOIN document_segments s ON s.dataset_id = ds.id
WHERE ds.id IN (
  SELECT dataset_id FROM documents WHERE indexing_status = 'error'
)
GROUP BY ds.id, ds.name;
```

**情况A：分段已全部索引（indexed_segs = total_segs）→ 直接改 completed**
Dify worker 遇到 RPM 限流后自动重试成功，分段嵌入完成但文档状态未更新。不需重新处理：
```sql
UPDATE documents 
SET indexing_status = 'completed', error = NULL, completed_at = NOW()
WHERE indexing_status = 'error'
  AND id IN (
    SELECT d.id FROM documents d
    JOIN document_segments s ON s.document_id = d.id
    WHERE s.index_node_id IS NOT NULL
    GROUP BY d.id HAVING COUNT(*) > 0
  );
```

**情况B：分段未索引（indexed_segs < total_segs）→ 重置为 waiting**
embedding 确实未完成，重置后 Dify worker 会重新排队处理：
```sql
UPDATE documents SET indexing_status = 'waiting', error = NULL
WHERE indexing_status = 'error';
```

**根本预防：不要并发上传多个大文档！**
6 个文档在 5 分钟内同时上传（12:36-12:41），worker 并发调用 MiniMax Embedding API 全部触发 RPM 限流。正确做法：
- 逐个上传，每个文档上传后等 embedding 完成（状态变 `completed`），再传下一个
- 或者上传间隔 ≥2 分钟，给 MiniMax RPM 窗口留足余量
- **Dify API 访问地址**：从 Starsower_v2 服务器内部用 `http://127.0.0.1:8081`，不是 `172.19.0.9:5001`

### Bug36: 文档全部 `waiting` + 向量索引ID不匹配（2026-07-28实测）

**症状**：
- `documents.indexing_status = 'waiting'`（全部6个文档）
- GraphQL报错：`Cannot query field "Vector_index_fd267580_..." on type "GetObjectsObj"`
- RAG检索完全不工作，用户问底座内容AI瞎编

**排查**：
```sql
-- 查文档索引状态
SELECT d.name, d.indexing_status, ds.name as dataset
FROM documents d JOIN datasets ds ON d.dataset_id = ds.id;

-- 检查 segments 是否有效 index_node_id
SELECT COUNT(*) as total,
       SUM(CASE WHEN index_node_id IS NOT NULL THEN 1 ELSE 0 END) as indexed
FROM document_segments WHERE dataset_id = '<dataset_id>';
```

**根因**：Dify embedding worker 未完成处理，`index_node_id`/`index_node_hash` 为空，向量查询失败。

**修复**：确认 `indexing_status='completed'` 且 `index_node_id` 非空后，RAG 才能正常工作。

### Bug37: 文档在知识库可见但App关联时找不到（2026-07-28）

**现象**：上传后在知识库「文档」标签页可见，字符数正确，但App的「添加知识库」里搜索不到。

**排查**：
```sql
-- 确认 tenant_id 一致
SELECT id, name, tenant_id FROM documents WHERE name LIKE '%.md%';
SELECT id, name, tenant_id FROM apps;  -- 应与 documents.tenant_id 相同
-- 确认 app_dataset_joins 关联
SELECT * FROM app_dataset_joins LIMIT 5;  -- 通常为空（未关联）
```

**可能原因**：
1. 文档 tenant_id ≠ App tenant_id（Bug3）
2. Dify 控制台 API 缓存问题（刷新页面/重登）
3. 知识库和 App 不在同一租户

**验证**：知识库列表页能看到的文档 → 说明文档存在且 tenant_id 匹配 → 问题是 App 关联时的下拉搜索。尝试在 App 的「检索设置」页面直接刷新。

### Bug38: COPY FROM stdin 失败（关键字问题）
- COPY 行格式：字段用 `\t` 分隔，换行符结束一行
- 空 JSON 字段（keywords/index_node_id/index_node_hash）：必须写 `\N`，不能留空
- content 内容里的 `\t` `\n` 必须替换为空格，否则破坏 COPY 行边界
- psql 的 `\copy`（反斜线命令）和 `COPY`（大写 SQL 命令）语法相同，都能用

## Embedding / LLM 模型（2026-07-31 更新）
- LLM 主力: **qwen3.7-flash**（思考模式 False，0.2/0.8 元/百万，1.42s 全场最快；选型定稿见 Bug40）
- LLM 备用: Hy3（腾讯，免费→1/4 元/百万）、qwen3.7-plus（1.6/6.4）
- Embedding: **千问 text-embedding-v3**（tongyi 插件，Dashscope API）
- **关键分工**：对话 LLM 用 qwen3.7-flash（Dify 自定义模型加入），Embedding 用千问（勿混用）
- 已淘汰: minimax-m3（编造+最贵）、m2.7/deepseek-flash（think 泄露关不掉，插件不透传 thinking 参数）
- 老师甲配置: `temperature=0.1, top_p=0.3`（低温度，更精准）
- **经验平台记忆系统（mem0 2.0.14 + sqlite_memory）使用经验见 `references/mem0-2-usage.md`**（API 变化：search 用 top_k+filters、metadata 全字符串、embedding 用百炼 API 替代 HF；评分+反思升级模式）

### Bug39: 知识库 Q&A 分段把问/答拆成独立 chunk → 检索只命中"问"（2026-07-31 实测）

**症状**：召回测试命中多个 12-13 字符的「问：xxx」chunk（score 0.82-0.84），答案 chunk 一个都没召回 → 模型回答"经验里没有相关内容"（Hy3 实测）。

**根因**：上传时选了「Q&A」分段模式——**Dify 的 Q&A 模式强制把每个「问」「答」拆成独立 segment**。用户问题与库内"问"文本重合度高（0.84），答案文本与问题相似度低 + top_k=3 → 答案全被截掉。数据库证据：问/答各占一个 position（324 段 = 162 问 + 162 答）。

**修复**：删文档（SQL 备份→DELETE，见 Bug7-9 备份习惯）→ 用**段落模式**（`separator="\n\n"`）重传。本地 QA.md 格式「问：xxx\n答：xxx\n\n问：yyy」恰好让问答对合并为一个 chunk（162 对 = 162 段，word_count 含问答）。已验证：合并后 chunk 为「问：... 答：内关（右手）、腋前大筋...」，检索一次命中。

**教训**：本地文件格式没错，错在分段模式选择。QA 内容一律用**段落模式**上传，别用 Q&A 模式（同时修正了 Bug33 的过时建议）。

### Bug40: 模型选型终稿——qwen3.7-flash（思考关）主力 + Hy3 备用（2026-07-31 实测定稿 v2）

**经验平台项目 LLM 最终选型：qwen3.7-flash（思考模式 False）主力，Hy3 备用，qwen3.7-plus 兜底。**

**6 模型实测对比**（同一问题"心悸伴胸闷"，知识库修复后，内容全部贴库）：

| 排名 | 模型 | 耗时 | 单价(元/百万) | think | 单次成本 |
|---|---|---|---|---|---|
| 🥇 | **qwen3.7-flash（思考关）** | **1.42s** | 0.2/0.8 | 无 ✅ | ~0.004元 |
| 🥈 | qwen3.7-plus | 2.35s | 1.6/6.4 | 无 | ~0.011元 |
| 🥉 | Hy3 | 3.81s | 免费→1/4 | 无 | 0→~0.004元 |
| 4 | minimax-m2.7 | 5.20s | 2.1/8.4 | 泄露关不掉 | ~0.011元 |
| 5 | deepseek-v4-flash | 8.22s | 1/2 | 泄露关不掉 | ~0.002元 |
| 6 | minimax-m3 | 5.44s | 4.2/16.8 | 无 | ~0.077元 |

**🔴 关键参数：qwen3.7-flash 必须把「思考模式」设为 False！**
- 默认开思考：**16.51s + think 全泄露**（用户看到推理过程，灾难）
- 关掉思考：**1.42s + 无泄露**——快 11 倍，全场最快
- 思考模式是 qwen3.7-flash 的固有属性（官方标"深度思考"），Dify 配置里选 False 即可

**qwen3.7-flash 配置要点**（自定义模型方式添加，见 Bug43）：
- 官方价：输入 0.2 / 输出 0.8 元/百万（全场最低，比 deepseek-flash 便宜 2.5 倍）
- 上下文 1M（991K 输入 / 64K 输出），不是 256k
- qwen3.7-plus 有 256k 和 1M 两档价（256k: 1.6/6.4；1M: 4.8/19.2，8折后），但 API 层不区分档位，Dify 配置即 1M

**淘汰理由**：m2.7/deepseek-flash（think 泄露无解，Dify 插件不透传 thinking 参数）、minimax-m3（编造+最贵）。

### Bug41: Dify 1.16.1 添加自定义模型流程（customizable-model 通道，2026-07-31 实测）

**场景**：插件预定义模型列表里没有想要的模型（如 qwen3.7-flash），且改插件包不可行（包 hash 校验+缓存难刷）。

**正确姿势：用 provider 的 customizable-model 通道添加**，不要改插件包（difypkg 是 zip，plugin/ + plugin_packages/ 两处包 + redis declaration_cache 缓存，改包后 hash 不匹配/缓存不刷新，死路）。

**API 流程**（1.16.1，cookie+CSRF 认证，见 Bug40）：
```python
# POST /console/api/workspaces/current/model-providers/langgenius/tongyi/tongyi/models/credentials
payload = {
    "model": "qwen3.7-flash",
    "model_type": "llm",
    "name": "qwen3.7-flash",
    "credentials": {
        "dashscope_api_key": "<key>",   # 复用 tongyi 已有凭据
        "context_size": "1000000",      # ⚠️ 必须字符串！数字报 "should be string"
        "max_tokens": "8192",           # 也是字符串
        "function_calling_type": "no_call",
    },
}
# 返回 201 {"result":"success"} → 模型即出现在列表
```

**⚠️ 三个坑**：
1. `context_size`/`max_tokens` 必须是**字符串**（int 报 `Variable context_size should be string`）
2. schema 必填字段看 `provider/tongyi.yaml` 的 `model_credential_schema`（dashscope_api_key + context_size 必填）
3. 失败时查 API 日志：`docker logs docker-api-1 | grep -B5 TypeError` 定位具体字段

**⚠️ 另坑：openai_api_compatible 插件其实没装**——providers 列表里没有它（provider_models 里的 2 条 MiniMax 记录是残留）。要用 OpenAI 兼容模型必须先装该插件，或直接用 tongyi 的 customizable-model。

**插件机制备忘（1.16.1）**：
- 模型列表来源：plugin_daemon `/management/models` 接口 + redis `declaration_cache`（key 含插件 hash）
- 插件安装状态三处目录：plugin/（安装包）+ plugin_packages/（缓存包）+ cwd/（运行副本）。删 cwd 目录无效（重启从包恢复）
- **彻底卸载插件要走 Dify 界面/API**（`/workspaces/current/plugin/uninstall`），别手删目录
- provider_models 表只记录显式配置的模型（含自定义模型），≠ 插件声明的全部模型

**验证**：`GET /workspaces/current/model-providers/<provider>/models?model_type=llm` 列表出现模型名即成功。

### Bug42: 模型选型结论 v1（历史存档——已被 Bug40 v2 取代，保留踩坑记录）

**历史结论**：Hy3 主力 + qwen3.7-plus 备用（2026-07-31 早期实测，后被 qwen3.7-flash 思考关取代）。

**保留下来的有价值的坑**：
1. **Dify 插件不透传 thinking 参数**：m2.7/deepseek 的 think 输出关不掉——yaml 定义了 thinking 参数（default: false）、数据库 completion_params 加 `"thinking": false` 都无效，因为插件构造请求时**根本不读这个参数**（chat_completion_v2.py 只传 max_tokens/temperature/top_p/top_k/presence_penalty/frequency_penalty/stop）。验证：`grep -n "thinking" chat_completion_v2.py` 只有解析 reasoning 的代码（403-435 行），无透传逻辑。**参数定义≠代码透传**。
2. **删除插件旧版本目录必须给完整路径**：`sh -c 'rm -rf .../tongyi-0.1.48@*'` 的 glob 会被外层 bash 先展开导致删不掉。必须：`docker exec docker-plugin_daemon-1 rm -rf '/app/storage/cwd/langgenius/tongyi-0.1.48@<完整hash>'`，且要删 **cwd/ + plugin/ + plugin_packages/ 三处**（否则重启恢复）。
3. **改插件包是死路**：difypkg 是 zip（plugin/ + plugin_packages/ 两处），包内容 hash 与文件名 hash 分离（改内容后实例 hash 变 ea01aaa 但文件名还是 9aab606），redis declaration_cache 不刷新 → 模型列表不变。要加模型**用 customizable-model API**（见 Bug43），别改包。
4. **qwen3.7-plus 256k/1M 档位**：百炼模型 ID 唯一，Dify 插件 context_size 标 1000000（官方定义），价格表 256k/1M 差价是套餐档位差异，Dify 侧改标注不影响计费。
5. **common 插件坑**：openai_api_compatible 插件实际未安装（providers 列表没有，provider_models 残留 2 条 MiniMax 记录），要用 OpenAI 兼容模型须先装插件。

### Bug43: 分段模式设置藏在 API 请求体，网页界面不可见（2026-07-31 用户确认）

**经验**：Dify 知识库的分段规则（Q&A 分段 vs 段落模式）是**上传文档时通过 API 请求体的 `process_rule.segmentation.separator` 指定的**，Dify 网页界面**没有这个开关**，用户后台看不到、改不了。

**同一文件两种切法**（文件格式「问：xxx\n答：xxx\n\n问：yyy」不变）：
- Q&A 分段模式：Dify 按「问：」「答：」标记强制拆开 → 162 问 + 162 答 = **324 段**（问答分离，检索只命中"问"——Bug39 根因）
- 段落模式（`separator="\n\n"`）：只按空行切 → 问+答合并 = **162 段**（问答一体，检索一次命中）

**操作事实**：文件内容零修改，只改了上传请求里的 `process_rule` 参数。用户界面只能通过「分段数量 + 每段内容」间接验证。

**给用户汇报时的表达**：不要说"改了分段设置"（用户看不到），要说"删旧文档→用段落模式重传→162 段问答合并"，让用户在界面能验证。

### Bug46: 知识库格式选型——合规版（案例式）优于 QA 版（2026-07-31 实测结论）

**结论：老师甲经验知识库用「合规版」（案例式原文）比「QA 版」更适合。**

**为什么合规版更好**：
- 合规版 chunk = **完整案例**（症状+穴位+方法+效果一体），检索命中一条就有全部细节 → 回答丰富连贯
- QA 版 chunk = **单条问答**（一问一答），细节分散，回答要靠多条拼接，信息密度低
- 实测：经验3（合规版）回答完整引用两个案例细节（心率178→85、穴位、原则全有）——全场最佳；经验2（QA版）回答单薄

**格式要求**（合规版 md）：
```markdown
### CASE-001：右手腕桡侧疼痛
- 症状：...
- 辩证：...
- 经络辨证：...
- 穴位：...
- 调理方法：...
- 效果：...
- 关键原则：...
- 来源：日期
```
- 每个案例一个 chunk（段落模式上传，separator=\n\n）
- 案例间用空行分隔

**与 QA 版共存**：合规版作主力；QA 版可作检索补充（问答对命中率略高），但内容以合规版为准。**新增/修正知识时优先更新合规版**。

**同步铁律**：改完本地文件（精炼json/md）后，3 个知识库（经验1/2/3）全部重传更新（见案例合并教训：本地改一处，Dify 3 库都要同步）。

### Bug45: skill 更新后必须同步 D 盘副本（2026-07-31 用户要求）

**铁律：dify-ops-reference 每次内容更新后，必须把 SKILL.md 同步到 D 盘备份目录：**

```bash
cp /home/[作者]/.hermes/skills/dify-ops-reference/SKILL.md "/mnt/d/AI/AI工具/scgithub/difycaikeng/SKILL.md"
```

- 位置：`D:\AI\AI工具\scgithub\difycaikeng\`（含 SKILL.md + references/ + scripts/）
- 触发：任何 skill_manage patch/edit 之后
- 原因：D 盘是给 GitHub 开源用的工作副本，本地 skill 更新后不同步会过期（本次教训：上午复制后下午已落后 10+ 条 Bug）
- references/scripts 有新文件时也要一并同步（cp -r）

### Bug44: docker-nginx-1 路由到错误IP导致 Dify 界面 502/404
- 现象：example.com/ 和 example.com/apps 返回 404 或空白页
- 排查：
  1. `docker inspect docker-web-1 --format "{{json .NetworkSettings}}" | python3 -c "import sys,json; ..."` 查容器IP
  2. nginx 配置里 `proxy_pass http://web:3000` 但 hostname `web` 在 docker-nginx-1 里无法解析
  3. 正确做法：代理到 **容器IP**（如 `172.19.0.6`），不是 hostname
- 根因：nginx 容器的 `/etc/hosts` 没有 `web` 域名解析
- 正确配置：`proxy_pass http://172.19.0.6:3000;`（用容器实际IP）
- 注：主机 nginx（端口80）和 docker-nginx-1（端口8081）是**两套独立的nginx**，不能混淆
  - 主机 nginx：`/etc/nginx/nginx.conf` + `/etc/nginx/conf.d/example.com.v2.conf`
  - docker nginx：`docker exec docker-nginx-1 cat /etc/nginx/conf.d/default.conf`
  - docker-web-1 实际监听 `172.19.0.6:3000`，不是 `172.19.0.5:3000`

### 知识库文档上传（绕过 API 分片限制）

当 JSON 文件较大（>100KB）且 API 文档上传只能创建空记录时，用以下流程直接写数据库：

**推荐上传格式**：`.md`（Markdown），用 `##` 标题 + 正文结构，Dify 检索语义更清晰。

### 完整上传脚本逻辑
```python
# 1. 读 JSON
content = json.dumps(jdata, ensure_ascii=False)
char_count = len(content)
file_id, doc_id, seg_id = [uuidgen()]

# 2. upload_files 表（key 字段格式必须）
storage_key = f"upload_files/{TENANT}/{file_id}.json"
INSERT INTO upload_files (id, tenant_id, key, name, size, extension, mime_type, created_by, created_by_role, storage_type, used)
VALUES ('{file_id}', '{TENANT}', '{storage_key}', '{fname}', {char_count}, 'json', 'application/json', '{TENANT}', 'account', 'local', false)

# 3. documents 表（batch 和 created_from 是必填非空字段）
batch = "batch_" + file_id
INSERT INTO documents (id, tenant_id, dataset_id, name, doc_form, doc_language, indexing_status, data_source_type, file_id, word_count, position, created_by, created_at, batch, created_from, enabled, archived)
VALUES ('{doc_id}', '{TENANT}', '{ds_id}', '{fname}', 'text_model', 'Chinese', 'completed', 'upload_file', '{file_id}', {char_count}, 1, '{TENANT}', NOW(), '{batch}', 'api', true, false)

# 4. document_segments 表 — 用 COPY FROM stdin（不走 shell 参数）
# 关键：空 JSON 字段用 \N，content 里换行/tab 替换为空格避免破坏 COPY 行格式
COPY document_segments(id, tenant_id, dataset_id, document_id, position, content, word_count, tokens, keywords, index_node_id, index_node_hash, hit_count, enabled, status, created_by) FROM stdin
```
- keywords/index_node_id/index_node_hash 是 JSON 类型，空值必须写 `\N`
- content 内容里的 `\t` `\n` 必须替换为空格，否则破坏 COPY 行格式
- COPY 成功的返回码是 0，失败时整个行都被拒绝
- 直接 INSERT（带 E'...' 转义）会因内容太大失败，只有 COPY 行得通

### 上传文件 API（文件上传到存储）
```bash
# 先登录获取 token
TOKEN=$(curl -s -X POST "http://172.19.0.9:5001/console/api/login" \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@hdnz.net","password":"[REDACTED]"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['\''data'\'']['\''access_token'\''])")

# 上传文件（multipart/form-data）
curl -s -X POST "http://172.19.0.9:5001/console/api/files/upload" \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@/path/to/file.json;filename=file.json;type=application/json"
# 返回 {"id": "...", "size": N, ...}
```

## 相关文件
- Dify 代码：`/opt/dify/dify-1.3.1/`
- Volume 存储：`/opt/dify/docker/volumes/app/storage/upload_files/`
- Docker compose：`/opt/dify/docker/.env`

## ⚠️ DeepSeek fallback 已完全移除（2026-07-29 执行，不可恢复）

**铁律：`services/llm.py` 的 `call_llm()` 仅走 Dify API，无任何兜底。** DeepSeek 的 `_call_deepseek()`、`_get_llm_config()` 以及相关 fallback 代码已全部删除。

- Dify 无 token → 返回 `"（老师经验库尚未配置，请等待管理员更新。）"`
- Dify 调用失败 → 返回 `"（知识库服务异常，请稍后再试。）"`
- **绝不调用任何通用 LLM**，即使 Dify 宕机也不降级

**动机**：[作者] 明确"一兜底这个项目就没有任何意义了。我们本来就是用各位老师的经验的，你一兜底和豆包有什么区别？"

**健康检查**：看板 🩺 系统健康卡片 + 巡检脚本 15 项覆盖，含后端模型("仅Dify API") + 5个AI分身Dify API连通性检测。

## Starsower_v2 × Dify 集成方案（2026-07-27）

### 架构
```
Starsower_v2 (端口8001) → Dify API (本地8081 docker-proxy) → Dify知识库(语义检索) + MiniMax-M3
```

**⚠️ DIFY_BASE_URL = "http://127.0.0.1:8081"（本地docker-proxy），不是 172.19.0.9:5001**
- Starsower_v2 的 `llm.py` 仅走 Dify API，无任何 fallback
- Dify Token 存在 Starsower_v2 的 `app_settings` 表：`dify_token_{avatar_name}`
- 5个分身共用同一套 Dify MiniMax-M3 模型，各自独立知识库

### 5个分身 Dify API Token（2026-08-01 更新——4人已换新 Key 并写入生产 app_settings）
| 分身 | API Token | 备注 |
|------|-----------|------|
| 老师甲 | `app-[REDACTED]` | App=老师甲经验fuzhi，关联合规版知识库，模型 qwen3.7-flash 思考关 |
| 老师乙 | `app-[REDACTED]` | **2026-08-01 生效** |
| 老师丙 | `app-[REDACTED]` | **2026-08-01 生效** |
| 老师丁 | `app-[REDACTED]` | **2026-08-01 生效**（⚠️ 应用有故障，见 Bug48） |
| 老师戊 | `app-[REDACTED]` | **2026-08-01 生效** |

⚠️ 旧 Key（app-kVHQ... / app-9oYQ... / app-cLc5... / app-pfoI...）已全部失效。改 Key 后写入位置：SQLite `app_settings` 表 `dify_token_{人名}`（INSERT OR REPLACE，llm.py 只读这里），写入后无需重启（每次查询）。

### Bug48: Dify 应用"空转"故障——answer 回显问题原文 + completion_tokens 极小（2026-08-01 实测）

**现象**：直调某分身 Dify API（`/v1/chat-messages` blocking）返回 200，但 `answer` 是**问题原文的 echo**（如问"你好，简单介绍一下你自己"返回同一句），`metadata.usage.completion_tokens` 只有 5 个左右，`retriever_resources` 为空。对照正常分身（同配置结构）0.8s 正常回答。

**根因判断**：该 Dify 应用（如"老师丁经验"）**应用内没选好模型/配置未发布**——应用是空转状态。⚠️ 不要被数据库误导：`app_model_configs` 的 `provider/model_id/configs` 列查出来是空（null），**正常应用也是空**（Dify 1.16 模型配置在别处），空列不等于故障；老师甲同列为空但完全正常。

**排查**：对比法最有效——用另一个正常分身的 token 直调同样问题，正常 vs 异常对比 completion_tokens（正常几十到几百，异常 ~5）。

**修复**：让用户在 Dify 后台打开该应用（如"老师丁经验"）检查：① 模型是否选定（qwen3.7-flash/tongyi）② 提示词是否保存 ③ 是否点了**发布**（未发布 → API 空转）。改完 Hermes 重测直调。

⚠️ 老师甲当前生产配置：Dify App「老师甲经验fuzhi」(id 3f135625) + 知识库经验3（合规版 26案例） + qwen3.7-flash（思考模式 False）——四维测试全过可上线。旧 Key（app-ScaMF6...）已失效。

### Bug51: 身份类问题空回复——_strip_self_intro 豁免词太窄（2026-08-01 实测）

**现象**：问"你是真人还是AI？""你到底是老师甲还是老师乙？"→ 5 分身全部回复空字符串。但直调 Dify API 正常（回"我是老师甲AI分身"）。

**根因**：chat.py `_strip_self_intro`（禁止主动自我介绍过滤）豁免词只有"你是谁/你叫什么/你是哪位/哪个老师/介绍一下你/介绍下你"。"你是真人还是AI？""你到底…"**不含这些豁免词** → 触发删除逻辑 → 正则删掉"我是XXAI分身"整句 → 回复变空。Dify 回答正常，是经验平台输出层把回答删光了。

**修复**：扩展豁免词：
```python
if any(k in user_message for k in ("你是谁", "你叫什么", "你是哪位", "哪个老师", "介绍一下你", "介绍下你",
                                   "你是真人", "你到底", "你是哪个", "你是什么", "你谁", "是AI吗", "是真人吗", "AI分身吗")):
    return reply
```

**排查套路**：经验平台链路空回复 vs Dify 直调正常 → 一定是输出层过滤误删，不是模型问题。先看 `_strip_self_intro`/`_apply_redline` 的删除逻辑能否误伤该回复。

**教训**：字符串豁免类过滤，判定条件漏一种问法就整段误删。加豁免词后必须实测 4 类：①"你是真人还是AI" ②身份混淆"你到底是谁" ③标准"你是谁" ④正常问题不受影响。

### Bug52: 免责声明概率性缺失——代码层兜底 _ensure_disclaimer（2026-08-01 实测）

**现象**：四维测试中某分身 1/10 场景回复缺免责声明（Dify 提示词第5条"每答末尾强制显示"是模型层约束，qwen 偶发漏加）。

**修复**：chat.py 回复链最后加 `_ensure_disclaimer`（代码层兜底，与 _apply_redline/_apply_policy_guard 一脉）：
```python
def _ensure_disclaimer(reply: str) -> str:
    if "本内容不构成医疗建议" in reply:
        return reply
    disclaimer = "※以上为AI采集真人经验生成，身体不适请及时去医院就诊。本内容不构成医疗建议。"
    return reply.rstrip() + "\n\n" + disclaimer
# 调用点：_strip_self_intro 之后
reply_text = _ensure_disclaimer(reply_text)
```
实测：缺免责自动追加 ✓、已有不重复 ✓、线上全链路生效 ✓。

**模式**：模型层约束（提示词）不可靠，**关键合规输出必须代码层兜底**——免责、热线、红线替换同理（chat.py 三件套：_apply_redline + _apply_policy_guard + _ensure_disclaimer）。

### Bug53: 管理看板运维 API 挂载——nginx /api/ 前缀铁律（2026-08-01 实测）

**现象**：新增 FastAPI 运维路由 `/api/ops/status` 公网 404（本地 127.0.0.1:8001 却通）。

**根因**：主机 nginx 只代理 `/api/admin/` → 8001（经验平台），**`/api/` 通用前缀 → 5000（haohe-health 系统）**。`/api/ops/status` 被转到 5000 → 404。

**修复**：
1. 路由路径必须用已有代理前缀：`@router.get("/api/admin/ops/status")`（FastAPI router 无前缀挂载时，路径要写全 `/api/...`，不是 `/admin/...`——`/admin/ops/status` 也会 404）
2. 看板 fetch 同步改 `/api/admin/ops/status`

**nginx 路由清单**（example.com.v2.conf）：`/xhxc/`→8001（剥前缀转发）、`/api/admin/`→8001、`/api/`→5000、`/v1/`→8081(Dify)、`/console/`→8081。**经验平台新增 API 一律挂 `/api/admin/` 下，别碰 `/api/` 裸前缀**（被 5000 劫持）。

### Bug54: Dify 知识库统计查询——表名不是猜的那样（2026-08-01 实测）

**现象**：想统计每个知识库的文档/分段数，`dataset_documents`/`dataset_segments`/`dataset_collections` 表名全部 `relation does not exist`。

**实际表名**（1.16.1）：`documents`、`document_segments`、`document_segment_summaries`。正确查询：
```sql
SELECT ds.name, count(distinct doc.id) AS docs, count(distinct seg.id) AS segs
FROM datasets ds
JOIN app_dataset_joins j ON ds.id=j.dataset_id
LEFT JOIN documents doc ON doc.dataset_id=ds.id
LEFT JOIN document_segments seg ON seg.dataset_id=ds.id
WHERE j.app_id IN (SELECT app_id FROM api_tokens WHERE token IN (...))
GROUP BY ds.name;
```
**教训**：猜表名前先 `SELECT table_name FROM information_schema.tables WHERE table_name LIKE '%xxx%'`。documents 表（dataset_id, name, indexing_status）；app_dataset_joins（app_id, dataset_id）是应用↔知识库关联表。

### Bug55: codex 生成前端 JS 调用未定义渲染函数（2026-08-01 实测）

**现象**：看板（dashboard.html）运维区块报 `renderServer is not defined`，随后又报 `container is not defined`。

**根因**：codex 生成的 ops_section.html 里 `.then(data => { renderServer(...); renderServices(...); ... })` 调用了 **6 个根本没生成的函数**（codex 只实现了 rebuildFromData 一个完整渲染函数）；且 rebuildFromData 内部用了 `container` 变量但函数内没定义（在别的 IIFE 局部作用域里）。

**修复**：删掉未定义函数调用，只调已实现的 `rebuildFromData(data)`；rebuildFromData 开头补 `var container = document.getElementById('ops-section');`。

**教训**：codex 交付前端 JS 必须验收——`grep "function <name>"` 对调用点逐一核对；IIFE 内局部变量不能跨函数引用；占位注释（`[PASTE THIS FILE HERE]`）要检查是否残留。

### Bug56: nginx sed 修改时 `$host` 被本地 shell 展开（2026-08-01 实测）

**现象**：`sed -i 's|...|proxy_set_header Host $host;|'` 插入 nginx 配置后 `nginx -t` 报 `invalid number of arguments in "proxy_set_header"`。

**根因**：ssh 双引号内 `$host` 被**本地 bash 先展开为空** → 配置行变成 `proxy_set_header Host ;`。

**修复**：ssh 命令用**单引号**包裹（或 `\$host` 转义）让 `$host` 原样传到服务器。改 nginx 前 `cp` 备份，改后 `nginx -t` 验证再 reload。

### Bug57: /api/admin 无尾斜杠 301 → https 页面 fetch 挂（2026-08-01 实测）

**现象**：看板主 JS `fetch('/api/admin')` 报 `Failed to fetch`，但 curl 却通（301+跟随）。

**根因**：`/api/admin`（无尾斜杠）不匹配 `location /api/admin/` → 落到 `location /api/` → 转发给 5000 系统 → 5000 返回 **http:// 协议的 301** → https 页面 fetch 跨协议重定向被浏览器直接拦截（Failed to fetch）。

**修复**：nginx 加精确匹配放前面（精确匹配优先）：
```
location = /api/admin { proxy_pass http://127.0.0.1:8001/api/admin; proxy_set_header Host $host; }
```
**教训**：https 页面的 fetch 遇到 http 重定向必挂；管理 API 无斜杠请求要精确匹配直通，别经过 /api/ 通用前缀（同 Bug53 家族）。

### 运维体系五件套（2026-08-01 建成，全部在生产运行）

| 组件 | 位置 | 说明 |
|------|------|------|
| 运维 API | `/opt/myapp/routes/ops_routes.py` | `GET /api/admin/ops/status`：服务器资源/服务状态/Dify应用token/知识库统计/备份/daemon 状态（全部 subprocess+timeout，绝不崩） |
| 运维 daemon | `/opt/myapp/ops_daemon.py`（systemd `starsower-ops`） | 每 30 分钟健康检查（真实调 Dify 发一条消息，token 从 app_settings 读）+ 磁盘>85%/内存>90% 告警 + 每日 02:00 备份（backup.sh + Dify pg_dump 保留7份）；状态落盘 `data/ops_status.json` |
| 告警推送 | `/opt/myapp/data/alert_config.json` | `{"serverchan_key": "SCT..."}` Server酱微信推送（sctapi.ftqq.com/{key}.send）；支持钉钉 webhook；30 分钟去重；**无 key 自动跳过只写日志** |
| 异地备份 | 本地 `/home/[作者]/scripts/backup_sync_daemon.py` | 每 72h rsync 服务器 backups → `D:\AI\AI产品\25 AI经验平台经验\服务器备份`，本地保留 10 份；rsync 未装时 scp -r 兜底 |
| **Weaviate 向量备份** | `/opt/myapp/weaviate_backup.sh` | 每日 02:00（daemon 调用）：停容器→tar（~107MB）→重启→保留7份。**Dify 恢复三件套**：经验平台 DB + Dify pg_dump + Weaviate 向量——缺向量库则恢复后要重传全部知识库 |

**⚠️ 带宽告警教训（2026-08-01）**：大文件 rsync（如 217MB Dify SQL）会打满外网出带宽，触发腾讯云监控告警（>95% 持续5分钟）——**异地同步必须加 `--bwlimit=20000`**（20MB/s）。腾讯云告警短信不一定是攻击/故障，先对照时间线查自己有没有大传输。
| 看板鉴权 | nginx Basic Auth（`/etc/nginx/.htpasswd_gl`） | `location = /xhxc/gl` + `location /api/admin/` 加 auth_basic；分身页面（/xhxc/）不受影响 |

- 日志轮转：`/etc/logrotate.d/starsower-ops`（daily/rotate 7/compress/**copytruncate**——daemon 持续写文件必须 copytruncate）
- 看板运维区块：dashboard.html 的 ops-section（fetch `/api/admin/ops/status`，60s 自刷新）——nginx 只代理 `/api/admin/` 前缀（Bug53），新 API 一律挂这里
- 告警触发验证：`PYTHONPATH=/opt/myapp venv/bin/python3 -c "import importlib.util; s=importlib.util.spec_from_file_location('ops','/opt/myapp/ops_daemon.py'); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); m.write_alert('测试告警')"`
- Server酱免费版每天 5 条对低频告警足够，**不用订阅付费版**（用户已确认）

### Bug58: Dify 1.16 对话应用没有模型故障转移（fallback）功能（2026-08-01 实测）

**现象**：用户想给主模型 qwen3.7-flash 配备用模型 Hy3（自动故障切换），Dify 界面找不到"故障转移/Fallback"区域。

**查证**：搜 Dify 前后端代码——`docker exec docker-web-1 grep -rl -i "fallback" /app/web/.next/...`（空）、`docker exec docker-api-1 grep -rli fallback /app/api/...`（只有日志/suggested-questions 字样）——**1.16.1 对话应用（mode=chat）没有模型级故障转移功能实现**。界面模型设置只有一个主模型选择。

**⚠️ 不要被误导**：`app_model_configs.configs` 列是 null（1.16 模型配置存别处），改库配 fallback 不可行——界面没有就是没有。

**解法**（模型 API 单点依赖的破法）：
1. **自研网关 failover**（推荐，用户偏好自研）：同气路由（/opt/example/tqly/server.js）加 upstreams 多上游 + 主失败(HTTP>=400/超时)切下一个 + config.json 持久化 + OpenAI 兼容出口；Dify 装 openai_api_compatible 插件指向它。见 tongqi-router 技能。
2. litellm 网关（第三方，功能全但多一层依赖；Bug42 记录过 MiniMax 工具调用差是弃用 litellm 方案的原因之一）。

**腾讯 Hy3 凭据位置**：`D:\AI\AI 信息记录\千问百炼和腾讯 dify.txt`（千问 OpenAI 兼容地址 `https://ws-....maas.aliyuncs.com/compatible-mode/v1`；腾讯 tokenhub URL `https://tokenhub.tencentmaas.com/v1`）。注意：文件里腾讯 API KEY 常是占位符，**真实 Key 在 Dify 插件密文里，可解密提取（见 Bug59）**。

### Bug59: Dify 插件模型凭据解密——RSA 混合加密（2026-08-01 实测）

**场景**：需要提取 Dify 已配置插件模型（Hy3/tencent-tokenhub）的 API Key 用于外部网关（同气路由 failover）。用户 key 文件是占位符时走此流程。

**凭据存储**：`provider_model_credentials` 表（不是 `providers`！）。`encrypted_config` 是**字段级加密 JSON**——api_key 加密，api_base/context_size/max_tokens_limit/support_* 全是明文：
```sql
SELECT tenant_id, provider_name, model_name, encrypted_config
FROM provider_model_credentials WHERE model_name='Hy3';
-- api_base 明文: https://tokenhub.tencentmaas.com/v1  |  api_key 密文 464字符
```
社区插件（tokenhub）在 `provider_models` 有记录但 `providers` 表无行——属正常，别以为没配置。

**加密格式**（libs/rsa.py encrypt）：RSA 混合加密 = `HYBRID:` 前缀 + RSA-OAEP(gmpy2_pkcs10aep_cipher) 加密 16 字节 AES key + AES-EAX(nonce+tag) 加密正文。

**解密流程**（容器内跑，绕过 Redis/框架初始化）：
```bash
# 1. 私钥位置（容器内实际是 /app/api/storage/ 不是 /app/storage/）
docker exec -u root docker-api-1 sh -c 'find / -name "private.pem" -path "*privkeys*" 2>/dev/null'
# → /app/api/storage/privkeys/{tenant_id}/private.pem

# 2. 脚本必须 docker cp 到 /app/ 下（容器 /tmp cp 会 Permission denied）；
#    docker exec 默认非 root 读不了 cp 文件 → 必须 -u root
# 3. 脚本核心：
#    sys.path.insert(0, "/app/api")
#    from Crypto.PublicKey import RSA
#    from Crypto.Cipher import AES
#    from libs import gmpy2_pkcs10aep_cipher
#    rsa_key = RSA.import_key(open(f"/app/api/storage/privkeys/{tenant}/private.pem").read())
#    cipher_rsa = gmpy2_pkcs10aep_cipher.new(rsa_key)
#    enc = base64.b64decode(密文)
#    if enc.startswith(b"HYBRID:"): enc = enc[7:]
#    sz = rsa_key.size_in_bytes()
#    aes_key = cipher_rsa.decrypt(enc[:sz])
#    nonce/tag/ct = enc[sz:sz+16], enc[sz+16:sz+32], enc[sz+32:]
#    out = AES.new(aes_key, AES.MODE_EAX, nonce=nonce).decrypt_and_verify(ct, tag)
```
**坑**：
- shell 传密文会被截断/转义 → `psql -t -A -c "SELECT encrypted_config ..." > file` 输出到文件再管道喂脚本，**别手抄密文**（base64 "Incorrect padding"=密文丢字符）
- 直接调 `core.helper.encrypter.decrypt_token()` 报 `Redis client is not initialized`——必须绕过框架手动解
- 宿主 `pip install pycryptodome` 常装错 Python 环境（pip3/python3 版本不一致），直接用容器内已有依赖
- 完整 key 写服务器本地文件（如 /tmp/hy3_key_full.txt），打印只用掩码（安全铁律）

### Bug49: avatars 表 name 带空格 → _get_dify_token 查不到（2026-08-01 实测）

**现象**：老师丁直调 Dify API 正常，但线上页面（/api/chat）回答异常/走不到知识库。查 app_settings 明明有 `dify_token_老师丁`。

**根因**：`_get_dify_token(avatar_name)` 用 `f"dify_token_{avatar_name}"` 拼 key，而 `avatar_name` 来自 `chat.py` 的 `avatar_name = avatar["name"]`——**DB `avatars` 表里老师丁的 name 是 `'老师丁'`（中间两个空格）**！拼出来的 key 是 `dify_token_老师丁`（带空格），与无空格的 `dify_token_老师丁` 对不上 → 返回 None → 走"（老师经验库尚未配置）"。

**验证**：
```bash
cd /opt/myapp && PYTHONPATH=/opt/myapp venv/bin/python3 -c "
from services.llm import _get_dify_token
print(_get_dify_token('老师丁'))  # None ← 查不到
print(_get_dify_token('老师丁'))    # app-ODUv... ← 有值
"
```

**修复**：按 DB 里 name 的**原样**（含空格）补一条 key：
```sql
INSERT OR REPLACE INTO app_settings (key, value) VALUES ('dify_token_老师丁', '<token>');
```
两条都留（无空格 key 供测试脚本用，带空格 key 供线上链路用）。

**预防**：给新分身配 token 前，先 `SELECT id, name FROM avatars` 看 name 是否有空格/特殊字符，key 必须与 name 完全一致。测试脚本（four_dim_test_5avatars.py）里 AVATARS 也要写带空格的名字。

### Bug50: 多轮对话上下文丢失——conversation_id 查询取到空记录（2026-08-01 实测）

**现象**：用户"我膝关节痛"→ 分身问"哪里痛？"→ 用户答"后方"→ 分身又问"哪里后方？"（完全不记得上一轮）。所有分身多轮对话断片。

**根因**：chat.py 取 Dify conversation_id 的 SQL 是 `SELECT dify_conv_id FROM conversations WHERE user_id=? AND avatar_id=? ORDER BY created_at DESC LIMIT 1`。**用户消息先 INSERT（`dify_conv_id` 为空）再查询** → 取到刚插入的空记录 → `prev_dify_conv_id=None` → Dify 每次开新会话，上下文全丢。

**修复**（查询加过滤，只取有会话ID的历史记录）：
```python
prev_conv = conn.execute(
    "SELECT dify_conv_id FROM conversations WHERE user_id=? AND avatar_id=? AND dify_conv_id IS NOT NULL AND dify_conv_id != '' ORDER BY created_at DESC LIMIT 1",
    (user_id, avatar_id)
).fetchone()
```

**验证**（两轮对话）：
- 第1轮"我膝关节痛" → 分身问位置
- 第2轮"后方" → 应答"收到，是膝盖后方（腘窝处）出问题"（理解上下文）而非再问"哪里后方"

**教训**：INSERT 后再查"最近一条"做关联查询，天然会取到自己刚插的记录。关联查询要过滤目标字段非空，或先查询再 INSERT。

### Bug60: 应用模型配置真实存储位置 + 界面"发布"陷阱（2026-08-01 实测）

**模型配置存 `app_model_configs.model` 列**（JSON：`{"provider": "langgenius/tongyi/tongyi", "name": "qwen3.7-flash", "mode": "chat", "completion_params": {"enable_thinking": false, "max_tokens": 8192, "temperature": 0.1, "top_p": 0.3}}`）——不是 provider/model_id/configs 列（1.16 这三列对**正常应用也是 null**，别被误导，Bug48 已警告过）。

**⚠️ 用户每次在 Dify 界面编辑并"发布"应用 = 生成新的 app_model_configs 记录 + 更新 `apps.app_model_config_id`**。直接改历史配置 ID 完全不生效。改配置前必须：
```sql
SELECT app_model_config_id FROM apps WHERE id='<app_id>';  -- 当前生效配置
```

**⚠️ 界面发布还可能丢失 `dataset_configs` 的 datasets 数组**（知识库关联）——`{{#context#}}` 在 pre_prompt 会保留（界面保存不丢），但检索不执行（无数据集）。症状：回答泛泛引导、`docker logs docker-api-1 | grep rerank` 无检索调用。修复：从旧配置复制 dataset_configs（含 `datasets.datasets[].dataset.id` 列表）。

**改完必重启** `docker restart docker-api-1`；改前备份 `CREATE TABLE app_model_configs_bak_YYYYMMDD AS SELECT * FROM app_model_configs;`

### Bug61: Dify 接入自建模型网关（openai_api_compatible 完整流程，2026-08-01 实测）

**场景**：Dify 模型调用指向自建代理/网关（如同气路由做 qwen3.7-flash→Hy3 failover，见 tongqi-router 技能）。链路：Dify → openai_api_compatible 插件 → 网关 → 主/备模型。

1. **装插件**：Dify 界面插件市场装（API 端点 install/marketplace 流程坑多，脚本装易 404/400 "not a valid difypkg"，界面最稳）
2. **加自定义模型**（customizable-model 通道，Bug41 同款流程）：
```python
POST /console/api/workspaces/current/model-providers/langgenius/openai_api_compatible/openai_api_compatible/models/credentials
{"model": "qwen3.7-flash", "model_type": "llm", "name": "qwen3.7-flash",
 "credentials": {"api_key": "占位", "endpoint_url": "http://172.17.0.1:4002/v1",
                 "mode": "chat", "context_size": "1000000", "max_tokens": "8192", "function_calling_type": "no_call"}}
```
3. **容器访问宿主机**：endpoint_url 用 docker 网关 IP（`docker network inspect docker_default` 的 Gateway，如 172.23.0.1/172.17.0.1），**不是 127.0.0.1**（容器内指向容器自身）
4. **max_tokens 上限 4096**：completion_params 设 8192 报 `Model Parameter max_tokens should be less than or equal to 4096.0`——oac 模型 schema 限制 4096
5. **应用切换**：SQL 直改 model 列（见 Bug60），改完重启 docker-api-1
6. **验证**：① 网关日志有转发记录（如 tongqi.log FAILOVER #1 SUCCESS）② Dify 日志 `grep rerank` 有 HTTP 200（检索执行）③ 回答引用案例思路。⚠️ `metadata.retriever_resources` 空 ≠ 没检索（oac 模型下不返回引用详情，以回答质量为准）

### Bug62: 微信内置浏览器移动端适配（2026-08-01 检查）

**所有用户可见模板必须有** `<meta name="viewport" content="width=device-width, initial-scale=1.0">`（login/select/chat×5/lhzx 已全部确认有）。

- 容器用 max-width 自适应（login 400/460px、select 360px、chat 气泡 80%、lhzx 600px），无写死桌面宽度 = 手机正常
- 聊天输入栏用文档流（非 fixed 底部）可免 iOS 安全区（safe-area-inset-bottom）坑
- ⚠️ **不要给页面加 `user-scalable=no`**——用户明确要求手机端可双指放大（login.html 已去掉 maximum-scale=1 + user-scalable=no，2026-08-01）
- 检查方法：`ssh root@host "grep -n 'viewport' /opt/myapp/templates/*.html"` 批量看；固定宽度用 `grep -oE 'width:[0-9]{3,}px'`

### Bug63: 红线替换表修正 + ratchet 审计（2026-08-01 实测）

**chat.py REDLINE_REPLACE 与用户批准版本不一致的 3 处修正**（做审计时发现）：
1. `左病右治→左证右治` 应为 **左证右调**（用户批准版）
2. `上病下治→上证下治` 应为 **上证下调**（用户批准版）
3. **补上缺失的 `下针→按揉`**（原表只有扎针/针刺/用针/施针）

**教训**：合规替换表必须以用户批准版本为准，代码实现可能过时——改替换表前 grep 对照 memory 里的批准记录（memory 红线铁律是权威）。

**ratchet 式红线审计**（借鉴 0xwilliamortiz/ratchet 思路）：
- `_log_redline_audit()`：每次替换写 redline_audit 表（words JSON：`[{"word","replaced_to","count"}]` + user_id/avatar_id/created_at），`CREATE TABLE IF NOT EXISTS` 内联建表
- `_apply_redline(text, user_id, avatar_id)` 签名带审计参数；**星号过滤 `text.replace("*","")` 必须保留**（放循环前，新版曾漏掉导致星号回显复发）
- API：GET `/api/admin/redline-audit?limit=N`（records + word_stats 按词统计），加在 ops_routes.py

### Bug55: mem0 在本服务器环境不可用——经验平台记忆最终架构（2026-08-01 实测）

**结论：经验平台跨会话记忆由 `services/sqlite_memory`（SQLite 渠道）独扛，mem0 不启用。**

**mem0 环境测试结果**：
- mem0 2.0.14（最新）与 1.0.11（降级）都：add 写入正常（qdrant 有数据）但 search 恒返回 0 条
- 诊断确认：query embedding 正常（百炼 text-embedding-v3 200/1024维）、qdrant collection 正常（4点/1024维）——**qdrant 本地模式检索异常**（本地+on_disk 组合，mem0 内部无报错但返回空）
- 替代方案 chroma：需要 sqlite3>=3.35（TencentOS 系统 sqlite 过老）——也不行
- 曾有一次 search 成功（memgen_test_07），其余全 0——不稳定

**🔬 根因深挖（2026-08-01 GitHub issue 佐证）**：
- 最终定位：qdrant 里存储的**向量是 None**（payload 有数据、vector 空 → 相似度检索必空）；embedder 独立测试正常（`EmbedderFactory.create(provider, config, vector_config)` 输出 1024 维）
- 调试要点：qdrant 数据用 `QdrantClient(path=...).scroll()` 直接查 payload 与 vector——`p.vector` 为 None 即 embedding 没写进，别再看 mem0 search 的结果
- mem0 版本 API 差异：1.0.11 search 用 `user_id=` 顶层参数 + `limit`；2.0.14 用 `filters={"user_id":...}` + `top_k`；metadata 的 created_at/importance 必须是字符串（pydantic 校验）
- GitHub 佐证这是 mem0 已知问题区（官方在修，未合入稳定版）：mem0ai/mem0 **#6462**（本地 self-hosted Qdrant search 链路 4 个 bug，closed PR）、**#6319**（复用 collection 不校验维度→search 静默失败，open）、**#4473**（本地 Qdrant on_disk 默认值导致重启丢数据，closed）
- **结论：换任何 mem0 版本都一样，等官方修复合入或升级系统 sqlite 用 chroma 再试；经验平台用 sqlite_memory 渠道即可**

**经验平台记忆升级（2026-08-01 已上线，sqlite_memory）**：
- `_calc_importance()`：重要性评分（偏好词+3/健康词+2/长文本+1，上限10）
- `remember()`：LLM 摘要（**model 必须读 app_settings llm_model=qwen3.7-flash，曾硬编码 deepseek-v4-flash 与百炼 base_url 不匹配导致摘要永远失败退化为截断**）+ 存 importance
- `recall()`：加权召回（query 中文关键词 LIKE 匹配 + importance*2 DESC + id DESC；无命中退最近）
- `reflect(user_id)`：每 20 条消息触发，LLM 聚合记忆生成画像存 users.profile.summary（chat.py 触发）
- mem0 渠道调用点已改为按 user_id（学员级隔离）；mem0 本身 NoOp 降级（get_memory_service 直接返回 _NoOpMemoryService）

**app_settings 新增**：llm_api_key / llm_base_url / llm_model（百炼 qwen3.7-flash）——mem0 与 sqlite_memory 的 LLM 都从这里读。

### 设置/更新 Dify Token（数据库直接写）
```python
import sqlite3
conn = sqlite3.connect("/opt/myapp/soulfire_v2.db")
conn.execute("INSERT OR REPLACE INTO app_settings (key, value) VALUES ('dify_token_老师甲', 'app-xxx')")
conn.commit()
conn.close()
```

### INSERT documents 表必填字段清单

直接INSERT `documents` 表时，以下字段**必须非NULL**，否则详情页500：

| 字段 | 常见错误 | 正确值 |
|------|---------|--------|
| `data_source_info` | NULL → Bug9 | `'{"name":"文件.json","size":N,"type":"json","upload_type":"file"}'` |
| `dataset_process_rule_id` | NULL → Bug8 | 需先INSERT `dataset_process_rules` 再UPDATE |
| `file_id` | NULL → Bug7 | `uuid.uuid4()` 生成 |
| `doc_form` | NULL | `'text_model'` |
| `batch` | NULL | `'batch_' + uuid` |
| `created_from` | NULL | `'api'` |
| `position` | NULL | `1` |

**INSERT后立即查 `dataset_process_rules`**，如无该dataset记录先建一条。Bug10+Bug11经常同时出现。

### joint.py mem0 并行接入（2026-07-28）

```python
# joint.py 核心逻辑
from concurrent.futures import ThreadPoolExecutor, as_completed

def _get_memories(identity_key, avatar_id, message):
    from services.memory import get_memory_service
    svc = get_memory_service()
    results = svc.search_memories(str(avatar_id), message, limit=3)
    parts = [r.get("memory","") for r in results if r.get("memory")]
    return "\n".join([f"- {m}" for m in parts]) if parts else ""

def _save_memory(identity_key, avatar_id, query, reply):
    from services.memory import get_memory_service
    svc = get_memory_service()
    svc.add_memory(str(avatar_id), identity_key, f"用户问：{query}\n老师答：{reply}")

def _call_one(a):
    name, token, query, uid = a["name"], a["token"], a["query"], a["uid"]
    if token:
        try:
            reply = _call_dify(token, query, uid)
            _save_memory(a["identity_key"], a["avatar_id"], query, reply)
            return {"name": name, "reply": reply}
        except:
            return {"name": name, "reply": "（暂时无法回答）"}
    return {"name": name, "reply": "（未配置AI助手）"}
```

**并行执行**：每老师独立线程，identity_key 隔离用户记忆，总时间=最慢的老师。

---

## 关键教训：原书不清洗原则（2026-07-28）

| 类型 | 处理方式 | 上传Dify |
|------|----------|----------|
| AI分身个人经验 | REDLINE清洗（替换违规词） | 结构化JSON |
| 原书/参考文献 | **原封不动**（不清洗一个字） | TXT原文 |

**为什么原书不清洗？**
- 原书是杨真海/刘力红的正经教材，是权威参考文献
- "传统经络针法""上病下治"是书的本来面目
- AI输出时 REDLINE 规则在**输出层**拦截，不是知识库层
- 知识库检索召回的是书中原文，那不是AI说的，是书上写的

**违规词统计（原书《传统经络针法》LightRAG 191块）**：
- 传统经络针法：104处（书名，保留）
- 左/右/上/下病治：各2处（保留）
- 用针：18处（保留）
- 患者：5处（保留）

→ 全部不清洗，因为是原书原文，不是AI输出

**两层知识库架构**：
```
AI分身个人知识库（清洗后）→ 各自分身独立调用
共享底座知识库（原书）   → 所有分身共享检索
```

---

## Starsower_v2 LLM 调用逻辑（2026-07-29 更新：无兜底）

```python
# llm.py 核心逻辑（2026-07-29 删除所有 DeepSeek 相关代码）
def call_llm(avatar_name, avatar_personality, user_message, memory_context="", conversation_id=None):
    """仅走 Dify API（老师知识库），无兜底。"""
    dify_token = _get_dify_token(avatar_name)
    if not dify_token:
        return {"reply": "（老师经验库尚未配置，请等待管理员更新。）"}
    try:
        answer, new_conv_id = _call_dify(dify_token, user_message, user_id=avatar_name, conversation_id=conversation_id)
        return {"reply": answer, "conversation_id": new_conv_id}
    except:
        return {"reply": "（知识库服务异常，请稍后再试。）"}
```

### Dify conversation_id 会话持久化
- Starsower_v2 `conversations` 表新增 `dify_conv_id` 列
- 每次对话后存 `conversation_id`，下次请求时传入，实现跨请求记忆

### 验证 Starsower_v2 → Dify 连通性
```bash
# Starsower_v2 API 测试
curl -s --max-time 40 -X POST "http://localhost:8001/api/chat" \
  -H "Content-Type: application/json" \
  -d '{"avatar_id":1,"message":"你是谁","user_id":"test"}'
# 期望：{"reply":"我是老师甲AI分身",...}

# 直连 Dify 测试（blocking，新 user_id）
curl -s --max-time 40 -X POST "http://127.0.0.1:8081/v1/chat-messages" \
  -H "Authorization: Bearer app-[REDACTED]" \
  -H "Content-Type: application/json" \
  -d '{"query":"传统经络针法是什么","inputs":{},"user":"test","response_mode":"blocking"}'
```

## 相关文件
- 模型插件凭据验证调试工作流：`references/plugin-credential-debug-workflow.md`
- Starsower_v2 ↔ Dify 集成方案：`references/starsower-dify-integration.md`
- 知识库 JSON 重新上传：`references/json-reupload-workflow.md`
- Dify .md 文件清洗+上传流程：`references/dify-upload-md-workflow.md`
- Dify 输入预处理级联Bug：`references/preprocessing-cascade-bug.md`
- Nginx路由顺序+joint-chat联合咨询：`references/nginx-joint-chat-routing.md`
- MD→JSON→Dify数据库上传流程：`references/md-json-dify-upload-workflow.md`
- Dify JSONL直写上传脚本：`references/dify-upload-jsonl.py`
- Dify运维Bug参考：`dify-ops-reference`（Bug7-9 上传INSERT三缺一、nginx rewrite铁律）
- Q&A格式转换工作流：`references/qa-conversion-workflow.md`
- Nginx配置重写铁律：`dify-ops-reference/references/nginx-config-rewrite-rule.md`
- 传统经络针法书籍底座知识库方案：`references/book-base-knowledge-library.md`
- 知识库完整重建工作流（API删+传+修+验）：`references/kb-rebuild-workflow.md`\n- Dify就地升级工作流（1.3.1→1.15.0，本地已有`:latest`镜像时）：`references/dify-inplace-upgrade.md`
- Dify子路径nginx代理模式（旧方案，已被 basePath 镜像替代）：`references/dify-subpath-proxy-pattern.md`
- **自定义 basePath 镜像构建（2026-07-29 实战——唯一可靠的 Dify 子路径方案）**：`references/dify-custom-basepath-build.md`
- **Awesome-Dify-Workflow FAQ（⭐10,720 模板市场）**：`references/awesome-dify-workflow-faq.md`
- **Dify 版本稳定性参考（2026-07-30）**：`references/dify-version-stability.md`
- **给已装插件添加自定义模型（1.16.1 完整流程+死路记录）**：`references/custom-model-add-workflow.md`
- **分身上线链路检查清单（三环法：Token→{{#context#}}→检索参数）**：`references/avatar-live-link-check.md`
- **链路诊断补充（2026-07-31）**：`references/chain-diagnosis-116.md` — 前端答通用话术完整诊断链：SQLite token 缺失→API Key 生成→{{#context#}}→score_threshold 召回0条（weighted_score 下 0.45 阈值过滤全部）→hit-testing 端点（1.16.1 改名）→pkill 重启坑（同一 ssh 会话 kill uvicorn 会波及 ssh，需分开两条命令）
- **AI 分身四维合规测试（压力/医疗红线/跨人/政策，暂行办法）**：见 `ai-anthropomorphic-service-compliance` 技能（含条款映射表 + 已落地整改模式：极端情绪热线兜底/情感边界引导/2小时提醒）
