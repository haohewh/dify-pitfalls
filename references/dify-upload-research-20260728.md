# Dify 知识库上传工具调研（2026-07-28）

## Dify 支持的文件格式（官方）

✅ PDF、DOCX、TXT、Markdown、CSV、Excel、HTML、JSON
❌ **jsonl 不支持**

## GitHub 工具调研

### Samge0/dify-upload（★17，2026-07-01更新）
- **语言**：Python（要求 3.13+）
- **License**：MIT
- **功能**：批量上传、自动轮询索引、进度记录、断点续传、去重、GUI客户端
- **优点**：纯 API 模式不需要数据库，API Key（`dataset-` 开头）即可运行
- **缺点**：Python 3.13 要求，服务器是 3.12（有兼容风险）
- **状态**：⭐ 可用，但 Python 版本是障碍
- **地址**：https://github.com/Samge0/dify-upload

### miemiejiaoxl/dify-knowledgebase（★1）
- **语言**：JavaScript + React + RabbitMQ
- **缺点**：架构太重，依赖太多，无人维护
- **状态**：不推荐

## JSON → MD 转换工作流（推荐）

```python
import json, os

src = '/mnt/d/AI/AI产品/25 AI经验平台经验/最终知识库上传/'
for fname in os.listdir(src):
    if not fname.endswith('.json') or fname.endswith('.jsonl'):
        continue
    d = json.load(open(os.path.join(src, fname), encoding='utf-8'))
    lines = []
    for key in ['cases', 'acupoint_knowledge', 'treatment_principles',
                'golden_quotes', 'refined_principles', 'refined_quotes', 'keywords']:
        for item in d.get(key, []):
            if isinstance(item, dict):
                parts = [f"{k}：{v}" for k, v in item.items() if v and str(v).strip()]
                if parts:
                    if item.get('source'):
                        lines.append(f"## {item['source']}\n")
                    lines.append('；'.join(parts))
                    lines.append('\n\n')
    out_path = os.path.join(src, fname.replace('.json', '.md'))
    with open(out_path, 'w', encoding='utf-8') as f:
        f.writelines(lines)
    print(f'{fname} -> {len([l for l in lines if l.strip()])}条')
```

## API 上传脚本（已验证通过）

```python
#!/usr/bin/env python3
"""Dify API 上传文档——JSON body + base64 方式"""
import base64, requests, os, json

API = "http://172.19.0.9:5001"

def login():
    r = requests.post(f"{API}/console/api/login",
        json={"email": "admin@hdnz.net", "password": "[REDACTED]"}, timeout=10)
    return r.json()["data"]["access_token"]

def upload_file(token, dataset_id, file_path):
    filename = os.path.basename(file_path)
    with open(file_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    payload = {
        "indexing_technique": "high_quality",
        "process_rule": {
            "mode": "custom",
            "rules": {
                "pre_processing_rules": [{"id": "remove_extra_spaces", "enabled": True}],
                "segmentation": {"separator": "\n\n", "max_tokens": 500}
            }
        },
        "file": b64,
        "file_name": filename,
    }
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    r = requests.post(
        f"{API}/console/api/datasets/{dataset_id}/documents",
        headers=headers, json=payload, timeout=120
    )
    return r.status_code, r.json()

# 用法
token = login()
status, result = upload_file(token, "API_ID", "/path/to/file.md")
print(result)
```

## 5个老师 API ID 映射（2026-07-28）

| 老师 | API ID（知识库） |
|------|-----------------|
| 老师甲 | bbd95d85-7d90-4f89-aa9f-3687bcd65274 |
| 老师乙 | 7f4230d5-7ce4-4f08-a8ec-f45532372e55 |
| 老师丙 | fd267580-3738-4fbc-8a5f-67909bcb9d20 |
| 老师戊 | 20728bcf-260f-4bb5-bb39-e77342325e35 |
| 老师丁 | 5355320f-4599-4eba-a9b7-c6a1431f32ec |

（URL ID ≠ API ID，必须用 API list 接口查出来的 ID）

## RPM 超限处理

索引报错 `[models] Rate Limit Error, rate limit exceeded(RPM)` 时：
```sql
UPDATE documents SET indexing_status='waiting', error=NULL
WHERE indexing_status='error' AND name LIKE '%.md';
```
Dify 会自动重试。
