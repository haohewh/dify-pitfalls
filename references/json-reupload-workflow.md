# Dify 知识库 JSON 重新上传完整流程

## 问题背景
- Dify 知识库文档状态 `indexing_status=completed` 但 `document_segments` 为空（「伪completed」）
- API 文档上传只能创建空文档记录，worker 异步分片失败
- JSON 文件 >100KB，直接 INSERT + E'...' 转义会报 "statement too long"

## 两种插入方案

### 方案A：直接 INSERT（适合中小文件，成功率最高）

关键字段说明：
- `documents.created_by` = **account_id**（UUID），不是 tenant_id
- `document_segments.created_by` = **account_id**（UUID）
- 必须先从 accounts 表查到 account_id

**正确流程**：
```sql
-- 1. 先查 tenant_id（从 datasets 表）
SELECT tenant_id FROM datasets WHERE id = '<dataset_id>';

-- 2. 再查 account_id（从 accounts 表）
SELECT id FROM accounts WHERE email = 'admin@hdnz.net';
```

```sql
-- documents 表（created_by 用 account_id，不是 tenant_id）
INSERT INTO documents (id, tenant_id, dataset_id, position, name,
  data_source_type, data_source_info, created_from, created_by,
  created_at, processing_started_at, word_count, indexing_status,
  enabled, doc_form, batch)
VALUES ('{doc_id}', '{tenant_id}', '{DATASET_ID}', 1, '{fname}',
  'upload_file', '{}', 'api', '{account_id}',
  '{now}', '{now}', {char_count}, 'completed',
  true, 'text_model', 'batch_001');

-- document_segments 表（created_by 也用 account_id）
INSERT INTO document_segments (
  id, tenant_id, dataset_id, document_id, position, content, word_count,
  tokens, status, created_by, created_at, indexing_at,
  hit_count, enabled
) VALUES (
  '{seg_id}', '{tenant_id}', '{DATASET_ID}', '{doc_id}', 1, E'{content_escaped}',
  {char_count//4}, {char_count//8}, 'completed', '{account_id}', '{now}', '{now}',
  0, true
);
```
关键：content 里单引号转义为 `''`（双单引号），`\x00` 要去掉（`replace(content, '\x00', '')`）。

### 方案B：COPY FROM stdin（适合超大文件 >1MB）
绕过 shell 参数长度限制：
```python
# 写 seg 数据到文件（避免 shell 插值问题）
with open("/tmp/_segdata.txt", "wb") as f:
    f.write(seg_line.encode("utf-8"))

copy_cmd = "\\copy document_segments(...) FROM stdin\n"
with open("/tmp/_segdata.txt", "rb") as f:
    inp = copy_cmd.encode("utf-8") + f.read()
subprocess.run(["docker", "exec", "-i", "docker-db-1", "psql", "-U", "postgres", "-d", "dify"],
    input=inp, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
```
空 JSON 字段（keywords/index_node_id/index_node_hash）用 `\N`，content 里的 `\t\n` 替换为空格。

## 完整流程（方案A）

1. **SCP 传文件**：`scp "源文件" root@127.0.0.1:/tmp/cxm_new.json`
2. **清空旧记录**：
   ```sql
   DELETE FROM document_segments WHERE document_id IN (SELECT id FROM documents WHERE dataset_id = '{DATASET_ID}' AND name LIKE 'cxm%');
   DELETE FROM documents WHERE dataset_id = '{DATASET_ID}' AND name LIKE 'cxm%';
   ```
3. **Python 脚本 INSERT**（用 subprocess 执行上面的 SQL）
4. **验证**：
   ```sql
   SELECT d.name, d.word_count, LENGTH(ds.content), ds.status
   FROM documents d JOIN document_segments ds ON ds.document_id = d.id
   WHERE d.dataset_id = '{DATASET_ID}';
   ```

## 5人知识库 Dataset ID 映射
| 名字 | Dataset ID | 备注 |
|------|-----------|------|
| 老师甲 | 8db9605b-2a88-43b8-a2a2-51d460558940 | 用户提供的URL里的ID |
| 老师甲（旧） | 964541c0-565f-4e2e-ba3f-49519cbbb19d | 旧ID |
| 老师乙 | 433553ed-33cc-4175-8bad-bcb7009beac2 | |
| 老师戊 | 4cee457d-dca6-4c3f-86be-0ed4da862358 | |
| 老师丁 | 644f9e8d-2f5e-4329-8876-69df9877211c | |
| 老师丙 | 5e82de8c-93af-4bf7-8b5e-9840f4cbaebf | |

## tenant_id 动态获取（必须！不能用固定值）

**根因**：硬编码 tenant_id 会导致跨租户问题——文档在数据库存在但 App 看不到（小卡片显示有数据，点开列表为空）。

正确获取方式：
```sql
-- 从 datasets 表反查 tenant_id（必须用这个）
SELECT tenant_id FROM datasets WHERE id = '<dataset_id>';

-- 从 accounts 表查 account_id（admin@hdnz.net）
SELECT id FROM accounts WHERE email = 'admin@hdnz.net';
```

**2026-07-27 实测值**：
- `admin@hdnz.net` 账号的 tenant_id = `f4194df5-5a62-4558-846c-e20f76586813`（[作者]'s Workspace）
- `admin@hdnz.net` 账号的 account_id = `4a018cd0-bddf-4c36-bb30-0b6d7a2678dd`
- 之前错误地用了 `ddd9af29-94c8-4f09-8c9c-1698e66fb00d`（另一个租户），导致文档上传后 UI 不显示

**Python 动态获取模板**：
```python
def get_uuid_from_psql(psql_cmd, query):
    """从 psql 输出中提取 UUID"""
    p = subprocess.Popen(psql_cmd + ['-c', query], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out, _ = p.communicate()
    for line in out.decode().split('\n'):
        line = line.strip()
        if len(line) > 30 and '-' in line:
            return line  # UUID 行
    return None
```

## 上传脚本模板
```python
#!/usr/bin/env python3
import subprocess, json, uuid
from datetime import datetime

JSON_PATH = "/tmp/cxm_new.json"
DATASET_ID = "8db9605b-2a88-43b8-a2a2-51d460558940"
DOC_NAME = "cxm_new.json"

with open(JSON_PATH, encoding="utf-8") as f:
    content = f.read()

char_count = len(content)
doc_id = str(uuid.uuid4())
seg_id = str(uuid.uuid4())
now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
tenant_id = "ddd9af29-94c8-4f09-8c9c-1698e66fb00d"

# Escape content for SQL: single quote → ''
content_escaped = content.replace("'", "''").replace("\x00", "")

# Delete old
subprocess.run(["docker", "exec", "docker-db-1", "psql", "-U", "postgres", "-d", "dify",
    "-c", f"DELETE FROM document_segments WHERE document_id IN (SELECT id FROM documents WHERE dataset_id = '{DATASET_ID}' AND name LIKE 'cxm%');"],
    stdout=subprocess.PIPE, stderr=subprocess.PIPE, env={"PGPASSWORD": "difyai123456"})
subprocess.run(["docker", "exec", "docker-db-1", "psql", "-U", "postgres", "-d", "dify",
    "-c", f"DELETE FROM documents WHERE dataset_id = '{DATASET_ID}' AND name LIKE 'cxm%';"],
    stdout=subprocess.PIPE, stderr=subprocess.PIPE, env={"PGPASSWORD": "difyai123456"})

# Insert doc
r1 = subprocess.run(["docker", "exec", "docker-db-1", "psql", "-U", "postgres", "-d", "dify", "-c", f"""
INSERT INTO documents (id, tenant_id, dataset_id, position, name,
  data_source_type, data_source_info, created_from, created_by,
  created_at, processing_started_at, word_count, indexing_status,
  enabled, doc_form, batch)
VALUES ('{doc_id}', '{tenant_id}', '{DATASET_ID}', 1, '{DOC_NAME}',
  'upload_file', '{{}}', 'api', '{tenant_id}',
  '{now}', '{now}', {char_count}, 'completed',
  true, 'na', 'batch_001');
"""], stdout=subprocess.PIPE, stderr=subprocess.PIPE, env={"PGPASSWORD": "difyai123456"})
print("Doc:", "OK" if r1.returncode == 0 else r1.stderr.decode()[:100])

# Insert segment
r2 = subprocess.run(["docker", "exec", "docker-db-1", "psql", "-U", "postgres", "-d", "dify", "-c", f"""
INSERT INTO document_segments (
  id, tenant_id, dataset_id, document_id, position, content, word_count,
  tokens, status, created_by, created_at, indexing_at, hit_count, enabled
) VALUES (
  '{seg_id}', '{tenant_id}', '{DATASET_ID}', '{doc_id}', 1, E'{content_escaped}',
  {char_count//4}, {char_count//8}, 'completed', '{tenant_id}', '{now}', '{now}', 0, true
);
"""], stdout=subprocess.PIPE, stderr=subprocess.PIPE, env={"PGPASSWORD": "difyai123456"})
print("Seg:", "OK" if r2.returncode == 0 else r2.stderr.decode()[:100])
```
