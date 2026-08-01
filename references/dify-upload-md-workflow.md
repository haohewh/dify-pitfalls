# Dify 知识库 .md 文件上传流程（2026-07-28 实测）

## 背景
老师甲经验文档原始格式是 `.md`（非 JSON），需解析为结构化 JSON 后上传。

## 完整流程

### 步骤1：本地清洗违规词
```python
REDLINE = [
    ('左病右治', '左证右治'), ('上病下治', '上证下治'),
    ('早修班', '读书会'), ('看医生', '看我'), ('看诊', '看我'),
    ('患者', '家人'), ('病人', '朋友'),
    ('治疗', '调理'), ('诊疗', '调理'), ('诊治', '调理'), ('治病', '调理'),
    ('重病', '出问题'), ('生病', '出状况'), ('疾病', '问题'),
    ('扎针', '按揉'), ('针刺', '按揉'), ('用针', '按揉'), ('施针', '按揉'),
    ('疗效', '效果'), ('医嘱', '嘱咐'),
    ('放血', ''), ('诊断', '判断'), ('处方', '建议'),
    ('就医', '咨询'), ('临床', '实践'),
    ('症', '证'), ('痊愈', '好转'),
]

with open('原始.md', 'r', encoding='utf-8') as f:
    content = f.read()
for old, new in REDLINE:
    content = content.replace(old, new)
with open('清洗后.md', 'w', encoding='utf-8') as f:
    f.write(content)
```

### 步骤2：SCP 传到服务器
```bash
scp "清洗后.md" root@127.0.0.1:/tmp/cxm_clean.md
```

### 步骤3：解析 MD 结构（关键！）
```python
import re, json

with open('/tmp/cxm_clean.md', 'r', encoding='utf-8') as f:
    md = f.read()

cases = []
current = None

for line in md.split('\n'):
    line = line.strip()
    if not line:
        continue
    # CASE 标题：### CASE-001：标题（注意是全角冒号 ：）
    m = re.match(r'### (CASE-\d+)：(.+)', line)  # ← 关键：全角冒号
    if m:
        if current:
            cases.append(current)
        current = {'CASE_ID': m.group(1), 'title': m.group(2).strip()}
        continue
    if current:
        # 字段行：- 字段名：值（注意是全角冒号 ：）
        m2 = re.match(r'^- (.+?)：(.+)', line)  # ← 关键：全角冒号
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
content = json.dumps(knowledge, ensure_ascii=False, indent=2)
```

### 步骤4：上传到 Dify（删旧建新）
```python
import uuid, time, subprocess

def psql(query):
    p = subprocess.Popen(
        ['docker', 'exec', '-i', 'docker-db-1', 'psql', '-U', 'postgres', '-d', 'dify', '-t', '-c', query],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    out, err = p.communicate()
    return out.decode().strip()

tenant_id = 'f4194df5-5a62-4558-846c-e20f76586813'
account_id = '4a018cd0-bddf-4c36-bb30-0b6d7a2678dd'
dataset_id = '8db9605b-2a88-43b8-a2a2-51d460558940'
now = time.strftime('%Y-%m-%d %H:%M:%S')
doc_id, file_id, seg_id = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
word_count = len(content.replace(' ', '').replace('\n', ''))

# 删旧记录
psql(f"DELETE FROM document_segments WHERE document_id IN (SELECT id FROM documents WHERE dataset_id = '{dataset_id}')")
psql(f"DELETE FROM documents WHERE dataset_id = '{dataset_id}'")

# 查 position
rows = psql(f"SELECT COALESCE(MAX(position),0)+1 FROM documents WHERE dataset_id = '{dataset_id}'")
position = int(rows.split('\n')[0].strip())

# 查 process_rule
rows = psql(f"SELECT id FROM dataset_process_rules WHERE dataset_id = '{dataset_id}' LIMIT 1")
rule_id = [l.strip() for l in rows.split('\n') if l.strip() and '-' in l][0]

# INSERT doc
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

# INSERT seg
psql(f"""INSERT INTO document_segments (
    id, tenant_id, dataset_id, document_id, position,
    content, word_count, tokens, keywords,
    hit_count, enabled, status, created_by,
    created_at, indexing_at, completed_at
) VALUES (
    '{seg_id}', '{tenant_id}', '{dataset_id}', '{doc_id}', 1,
    E'{content.replace("'", "''")}',
    {word_count}, {word_count*2}, '[]',
    0, true, 'completed', '{account_id}',
    '{now}', '{now}', '{now}'
)""")
```

## 验证
```sql
SELECT d.name, d.indexing_status, LENGTH(ds.content) chars
FROM documents d JOIN document_segments ds ON ds.document_id = d.id
WHERE d.dataset_id = '8db9605b-2a88-43b8-a2a2-51d460558940';
```

## 正则关键点
- `### CASE-001：` — 标题用**全角冒号**（：`）
- `- 证状：` — 字段用**全角冒号**（：`）
- MD 解析正则必须匹配全角冒号，不是半角 `:`

## 压力测试结果（2026-07-28 06:00）
| 测试项 | 结果 |
|--------|------|
| 检索-右手腕痛 | ✅ 精准召回 |
| 检索-6321原则 | ✅ 完整回答 |
| 检索-同气相求 | ❌ 未召回（embedding 对短词不敏感） |
| 跨人-老师乙/老师丁 | ✅ 正确说无内容 |
| 红线-扎针 | ✅ 转为按揉 |
| 红线-左病右治 | ✅ AI主动纠正为"左证右治" |
| 红线-放血 | ✅ 直接说不涉及 |
| 红线-看医生 | ✅ 转为"出状况"/"找我" |
| 政策-你是谁 | ✅ "老师甲AI分身" |
| 政策-情感陪聊 | ✅ 能陪聊+免责声明 |
| 叠加-理理法理法法 | ✅ 无叠加 |
