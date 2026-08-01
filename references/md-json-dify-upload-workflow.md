# MD解析→结构化JSON→Dify数据库上传流程

## 背景
老师甲经验精炼文件有两份：
- `/mnt/d/AI/AI产品/25 AI经验平台经验/已处理过的5人经验/5人切片文档/老师甲经验精炼.md` — 原始
- 同目录 `老师甲经验精炼_清洗后.md` — 医疗红线清洗后版本

## 完整流程

### Step 1：医疗红线清洗
```python
REDLINE = [
    ('左病右治', '左证右治'), ('上病下治', '上证下治'),
    ('早修班', '读书会'), ('看医生', '看我'), ('看诊', '看我'),
    ('患者', '家人'), ('病人', '朋友'),
    ('扎针', '按揉'), ('针刺', '按揉'), ('用针', '按揉'),
    ('放血', ''),  # 直接删除
    ('症', '证'),  # 必须是全词匹配，避免破坏其他词
    # ...其他规则
]

with open(fp, 'r', encoding='utf-8') as f:
    content = f.read()
for old, new in REDLINE:
    content = content.replace(old, new)
with open(fp.replace('.md', '_清洗后.md'), 'w', encoding='utf-8') as f:
    f.write(content)
```

### Step 2：MD解析为结构化JSON
```python
import re, json

with open('/tmp/cxm_clean.md', 'r', encoding='utf-8') as f:
    md = f.read()

cases = []
current = None

for line in md.split('\n'):
    ls = line.strip()
    if not ls:
        continue
    # CASE 标题行 —— 注意分隔符是全角冒号：
    m = re.match(r'### (CASE-\d+)：(.+)', ls)
    if m:
        if current:
            cases.append(current)
        current = {'CASE_ID': m.group(1), 'title': m.group(2).strip()}
        continue
    if current:
        # 字段行 —— 注意是「- 」不是「|- 」，注意冒号是全角：
        m2 = re.match(r'^- (.+?)：(.+)', ls)
        if m2:
            current[m2.group(1).strip()] = m2.group(2).strip()

if current:
    cases.append(current)

knowledge = {
    'IDENTITY': '老师甲AI分身',
    'role': '经络理法分享师',
    'source': '老师甲读书会经验整理',
    'cases_count': len(cases),
    'cases': cases
}
```

### Step 3：保存JSON到本地（Dify不支持直接上传JSON，必须先本地转存）
```python
out = fp.replace('.md', '_清洗后.json')
with open(out, 'w', encoding='utf-8') as f:
    json.dump(knowledge, f, ensure_ascii=False, indent=2)
print(f"保存到: {out}")
```
⚠️ **必须保存JSON到本地**：Dify不支持.json格式上传，但上传前本地保存JSON可以保留结构化数据，方便后续审计和复用。

### Step 4：上传到Dify（数据库直接INSERT）

#### 4.1 上传到服务器
```bash
scp "/path/to/老师甲经验精炼_清洗后.md" root@127.0.0.1:/tmp/cxm_clean.md
```

#### 4.2 完整INSERT脚本（服务器上执行）
```python
import uuid, time, subprocess

def psql(query):
    p = subprocess.Popen(
        ['docker', 'exec', '-i', 'docker-db-1', 'psql', '-U', 'postgres', '-d', 'dify', '-t', '-c', query],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    out, err = p.communicate()
    return out.decode().strip()

# 已知常量
tenant_id = 'f4194df5-5a62-4558-846c-e20f76586813'
account_id = '4a018cd0-bddf-4c36-bb30-0b6d7a2678dd'
dataset_id = '8db9605b-2a88-43b8-a2a2-51d460558940'
now = time.strftime('%Y-%m-%d %H:%M:%S')

# 生成ID
doc_id = str(uuid.uuid4())
file_id = str(uuid.uuid4())
seg_id = str(uuid.uuid4())

# 删除旧记录（同一dataset_id下的）
psql(f"DELETE FROM document_segments WHERE document_id IN (SELECT id FROM documents WHERE dataset_id = '{dataset_id}')")
psql(f"DELETE FROM documents WHERE dataset_id = '{dataset_id}'")

# 获取position
rows = psql(f"SELECT COALESCE(MAX(position),0)+1 FROM documents WHERE dataset_id = '{dataset_id}'")
position = int(rows.split('\n')[0].strip())

# 获取process_rule_id
rows = psql(f"SELECT id FROM dataset_process_rules WHERE dataset_id = '{dataset_id}' LIMIT 1")
rule_id = [l.strip() for l in rows.split('\n') if l.strip() and '-' in l][0]

# INSERT documents
psql(f"""INSERT INTO documents (
    id, tenant_id, dataset_id, position,
    data_source_type, data_source_info, dataset_process_rule_id,
    batch, file_id, name, created_from, created_by,
    created_at, processing_started_at, cleaning_completed_at,
    splitting_completed_at, completed_at,
    indexing_status, enabled, doc_form, doc_type, doc_language
) VALUES (
    '{doc_id}', '{tenant_id}', '{dataset_id}', {position},
    'upload_file', NULL, '{rule_id}',
    'batch_{file_id}', '{file_id}',
    '老师甲经验精炼.json',
    'datasets', '{tenant_id}',
    '{now}', '{now}', '{now}', '{now}', '{now}',
    'completed', true, 'text_model', NULL, 'Chinese'
)""")

# INSERT document_segments
content = json.dumps(knowledge, ensure_ascii=False, indent=2)
word_count = len(content.replace(' ', '').replace('\n', ''))
tokens = word_count * 2

psql(f"""INSERT INTO document_segments (
    id, tenant_id, dataset_id, document_id, position,
    content, word_count, tokens, keywords,
    hit_count, enabled, status, created_by,
    created_at, indexing_at, completed_at
) VALUES (
    '{seg_id}', '{tenant_id}', '{dataset_id}', '{doc_id}', 1,
    E'{content.replace("'", "''")}',
    {word_count}, {tokens}, '[]',
    0, true, 'completed', '{account_id}',
    '{now}', '{now}', '{now}'
)""")
```

### Step 5：验证
```bash
# 数据库验证
docker exec docker-db-1 psql -U postgres -d dify -t -c \
  "SELECT name, char_length(content), indexing_status FROM documents d JOIN document_segments s ON s.document_id=d.id WHERE d.dataset_id='8db9605b'"

# API验证
curl -s --max-time 20 -H "Authorization: Bearer app-[REDACTED]" \
  "http://172.19.0.9:5001/v1/chat-messages" -X POST \
  -H "Content-Type: application/json" \
  -d '{"query":"右手腕疼痛怎么办","inputs":{},"user":"verify","response_mode":"blocking"}'
```

## 已踩的坑

### 坑1：正则匹配不到CASE标题
- 原因：MD里分隔符是全角冒号 `：`不是半角 `:`
- 解决：`r'### (CASE-\d+)：(.+)'` 用全角冒号

### 坑2：字段行用 `|-` 前缀
- 原因：实际MD用的是 `- `（短横线+空格），不是 `|-`（竖线+短横线+空格）
- 解决：`r'^- (.+?)：(.+)'`

### 坑3：MD解析后word_count异常少（如只有111字符）
- 原因：正则匹配失败导致cases数组为空，只有顶层的IDENTITY等字段被写入JSON
- 解决：先单独调试正则，打印匹配数确认：`grep -c 'CASE-' /tmp/cxm_clean.md` 确认CASE标题存在，再用python逐步验证匹配

### 坑3：psql输出含header/footer行
- 原因：不用 `-t` 参数时输出含列名和分隔线
- 解决：python脚本里用 `['docker', 'exec', '-i', ..., '-t', '-c', query]` 自动过滤

### 坑4：文件路径含中文
- 本地Windows路径含中文，直接scp到服务器再python3读没问题（UTF-8）
- 直接在WSL里读 `/mnt/d/` 路径也能正常处理中文

### 坑5：JSON内容含单引号
- 解决：psycopg2的 `E'...'` 转义写法，`replace("'", "''")` 双重转义
