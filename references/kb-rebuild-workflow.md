# 知识库完整重建工作流（2026-07-29 实战验证）

## 场景
Dify 知识库索引损坏导致检索静默失败：API返回200，但回答全是LLM通用内容，无知识库检索结果。

## 诊断三连

### 1. 查 API 日志（向量索引错误）
```bash
docker logs docker-api-1 --tail 50 2>&1 | grep -i 'Vector_index\|retrieval\|error' | head -10
```
典型错误：
```
Cannot query field "Vector_index_7c1c4496_..." on type "GetObjectsObj"
```
→ 向量索引名 Weaviate 里不存在，文档删重建后 class 名称变化。

### 2. 查 Weaviate 是否 READONLY
```bash
docker logs docker-weaviate-1 --tail 20 2>&1 | grep -i 'READONLY\|disk\|90'
```
典型错误：
```
Set READONLY, disk usage currently at 90.26%, threshold set to 90.00%
```
→ 磁盘满导致 Weaviate 进入只读模式，重启后自动恢复。

### 3. 查分段是否真已索引
```sql
SELECT ds.name, COUNT(*) AS total,
  SUM(CASE WHEN s.index_node_id IS NOT NULL THEN 1 ELSE 0 END) AS indexed,
  SUM(CASE WHEN s.enabled=true AND s.status='completed' THEN 1 ELSE 0 END) AS usable
FROM datasets ds
JOIN document_segments s ON s.dataset_id = ds.id
GROUP BY ds.id, ds.name;
```
如果 `indexed = total` 但 `usable = 0` → 状态修复即可。

## 修复流程

### Step 0：Weaviate READONLY 解除
```bash
# 先确认磁盘有空余（需 <80%）
df -h /
# 重启 Weaviate 即可解除 READONLY（重启后重新检测磁盘，自动恢复读写）
docker restart docker-weaviate-1
sleep 5
# 验证无 READONLY 告警
docker logs docker-weaviate-1 --tail 5 2>&1 | grep -i 'READONLY'
```

### Step 1：通过 API 删除所有旧文档
```python
import requests
BASE = "http://127.0.0.1:8081"

# 登录
r = requests.post(f"{BASE}/console/api/login",
    json={"email": "admin@hdnz.net", "password": "[REDACTED]"}, timeout=10)
token = r.json()["data"]["access_token"]
h = {"Authorization": f"Bearer {token}"}

# 获取所有文档
rd = requests.get(f"{BASE}/console/api/datasets?page=1&limit=20", headers=h, timeout=10)
for ds in rd.json()["data"]:
    r2 = requests.get(f"{BASE}/console/api/datasets/{ds['id']}/documents?page=1&limit=20",
                      headers=h, timeout=10)
    for doc in r2.json().get("data", []):
        requests.delete(f"{BASE}/console/api/datasets/{ds['id']}/documents/{doc['id']}",
                       headers=h, timeout=30)
```

### Step 2：重新上传文件（Dify 1.3.1 两步骤流程）
```python
import base64

# Step 2a：上传文件
for ds_name, fpath, fname in FILES:
    ds_id = ds_map[ds_name]
    with open(fpath, "rb") as fh:
        r1 = requests.post(
            f"{BASE}/console/api/files/upload",
            headers=h,
            files={"file": (fname, fh, "text/markdown")},
            timeout=60
        )
    uf_id = r1.json()["id"]

    # Step 2b：用 upload_file_id 创建文档
    payload = {
        "indexing_technique": "high_quality",
        "data_source": {
            "type": "upload_file",
            "info_list": {
                "data_source_type": "upload_file",
                "file_info_list": {"file_ids": [uf_id]}
            }
        },
        "process_rule": {"mode": "automatic"},
        "doc_language": "Chinese"
    }
    r2 = requests.post(
        f"{BASE}/console/api/datasets/{ds_id}/documents",
        headers={**h, "Content-Type": "application/json"},
        json=payload, timeout=120
    )
```

**⚠️ Dify 1.3.1 不接受 `data_source` + `info_list` 格式外的其他格式**。不能直接传 base64 文件内容，必须先调 `/files/upload` 拿到 upload_file_id。

### Step 3：修复 MiniMax Embedding RPM 限流（Bug21）
并发上传多个大文档时，MiniMax Embedding API 触发 RPM 限流，文档状态变为 `error`。
但**分段可能已经索引完成**。修复：

```sql
-- 情况A：分段已索引（indexed_segs = total_segs）
UPDATE documents SET indexing_status = 'completed', error = NULL, completed_at = NOW()
WHERE indexing_status = 'error';

UPDATE document_segments SET status = 'completed', enabled = true
WHERE status = 'indexing' AND enabled = false;
```

```sql
-- 情况B：分段未索引（indexed_segs < total_segs）
UPDATE documents SET indexing_status = 'waiting', error = NULL
WHERE indexing_status = 'error';
```

**预防**：每个文档上传间隔 ≥5 秒，且不要在 3 分钟内上传超过 3 个文档。

### Step 4：重启 API + Worker 刷新缓存
```bash
docker restart docker-api-1 docker-worker-1
sleep 15
```

### Step 5：验证检索
```bash
TOKEN=$(curl -s -X POST 'http://127.0.0.1:8081/console/api/login' \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@hdnz.net","password":"[REDACTED]"}' | \
  python3 -c 'import sys,json; print(json.load(sys.stdin)["data"]["access_token"])')

# 取某个 App 的 API Key
APP_ID=$(curl -s "http://127.0.0.1:8081/console/api/apps" \
  -H "Authorization: Bearer $TOKEN" | \
  python3 -c 'import sys,json; d=json.load(sys.stdin); [print(a["id"]) for a in d["data"] if "老师甲" in a["name"]]')
KEY=$(curl -s "http://127.0.0.1:8081/console/api/apps/$APP_ID/api-keys" \
  -H "Authorization: Bearer $TOKEN" | \
  python3 -c 'import sys,json; print(json.load(sys.stdin)["data"][0]["token"])')

# 测试知识库检索
curl -s --max-time 60 -X POST "http://127.0.0.1:8081/v1/chat-messages" \
  -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" \
  -d '{"query":"右手腕疼痛按揉哪些穴位？","response_mode":"blocking","user":"test","inputs":{}}' | \
  python3 -c 'import sys,json; ans=json.load(sys.stdin).get("answer",""); hits=[c for c in ["阳池","外关","养老","列缺"] if c in ans]; print(f"命中: {hits}" if hits else "未命中")'
```

## 关键教训

1. **别只改数据库** — 文档分段必须从 Dify Studio 或 API 流程走，`UPDATE indexing_status` 会绕过 Weaviate 索引同步
2. **删文档会删文件** — Dify API 删除文档会同时删除 upload_files 记录和存储文件，生产环境务必先备份
3. **Weaviate READONLY 是静默杀手** — 磁盘满后向量检索全失败，但 Dify API 仍返回 200，只能从容器日志发现
4. **MiniMax Embedding RPM 限制 300/分钟** — 批量上传必须限速，否则全 error
5. **Dify 1.3.1 文档创建需两步** — 先 upload file，再用返回的 file_id 创建 document，不支持一步 base64 提交
