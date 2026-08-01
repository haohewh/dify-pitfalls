# 传统经络针法底座知识库 — 建设全流程（2026-07-28版）

## 最终结论：原书不清洗

| 类型 | 处理方式 | 上传Dify |
|------|----------|---------|
| AI分身个人经验 | REDLINE清洗（替换违规词） | 结构化JSON → 转JSONL |
| **原书/参考文献** | **原封不动**（不清洗一个字） | TXT/Markdown原文 |

**为什么原书不清洗？**
- 原书是杨真海/刘力红的正经教材，是权威参考文献
- "传统经络针法""上病下治"是书的本来面目
- AI输出时 REDLINE 规则在**输出层**拦截，不是知识库层
- 知识库检索召回的是书中原文，不是AI说的

## 源文件路径
- 原版：`D:\AI\AI产品\25 AI经验平台经验\三大内针书籍\传统经络针法-和平的使者 杨真海\ocr\传统经络针法-和平的使者 杨真海.md`（MinerU OCR，77KB，1157行）
- **已废弃**：`传统经络针法-和平的使者 杨真海-LightRAG/`（LightRAG只处理了原文15%，顺序乱，来源不明）

## 处理后文件
`D:\AI\AI产品\25 AI经验平台经验\三大内针书籍\传统经络针法-和平的使者 杨真海-合规输出-4\经络理法-和平的使者-原文.md`（约199KB）

### 处理步骤
1. **MinerU OCR**：PDF → HTML表格+Markdown混合，17张经络图转成了HTML `<table rowspan>` 标签
2. **HTML表格转Markdown**：BeautifulSoup解析rowspan/colspan，16个经络穴位表全部转成干净Markdown表格
3. **删除图片引用**：9个 `![](...)` 整行删除
4. **结果**：图片引用0个，HTML表格0个，Markdown表格88行，内容完整

### 处理命令（参考）
```python
from bs4 import BeautifulSoup
import re

with open('传统经络针法-和平的使者 杨真海.md', encoding='utf-8') as f:
    content = f.read()

def html_table_to_md(table_html):
    soup = BeautifulSoup(f'<table>{table_html}</table>', 'html.parser')
    table = soup.find('table')
    rows = table.find_all('tr')
    max_cols = 0
    for tr in rows:
        cols = tr.find_all(['td', 'th'])
        ci = 0
        for cell in cols:
            ci += int(cell.get('colspan', 1))
        max_cols = max(max_cols, ci)
    grid = [[''] * max_cols for _ in range(len(rows))]
    for ri, tr in enumerate(rows):
        cols = tr.find_all(['td', 'th'])
        ci = 0
        for cell in cols:
            while grid[ri][ci] != '': ci += 1
            rs = int(cell.get('rowspan', 1))
            cs = int(cell.get('colspan', 1))
            val = cell.get_text(strip=True)
            for r in range(rs):
                for c in range(cs):
                    grid[ri+r][ci+c] = val
            ci += cs
    lines = []
    for ri, row in enumerate(grid):
        clean = [v for v in row if v != '']
        if not clean: continue
        lines.append('| ' + ' | '.join(clean) + ' |')
        if ri == 0:
            lines.append('| ' + ' | '.join(['---'] * len(clean)) + ' |')
    return '\n'.join(lines)

new_content = re.sub(r'<table>.*?</table>', lambda m: '\n' + html_table_to_md(m.group(0)) + '\n', content, flags=re.DOTALL)
new_content = re.sub(r'\n*!\[.*?\]\(images/[^)]+\)\n*', '\n', new_content)
```

## Dify上传流程

### 1. 原书 → 直接上传Markdown
- 上传到 Dify 新建"传统经络针法底座"知识库
- embedding模型：MiniMax-Embedding-01（emb-01）
- 如报 `minimax_group_id` 错误：去 MiniMax 控制台找 Group ID，填入 Dify 模型设置

### 2. 分身经验精炼JSON → 必须转JSONL
自定义schema（`{cases:[], acupoint_knowledge:[], golden_quotes:[]}`）Dify不识别，上传后字符数为0。

**转换脚本**：
```python
import json, os

src_dir = '最终知识库上传/'
for fname in os.listdir(src_dir):
    if not fname.endswith('.json') or fname.endswith('.jsonl'): continue
    if '传统经络针法' in fname: continue
    
    with open(os.path.join(src_dir, fname), encoding='utf-8') as f:
        d = json.load(f)
    
    records = []
    def add(key, prefix):
        for item in d.get(key, []):
            if isinstance(item, dict):
                parts = [f"{k}：{v}" for k, v in item.items() if v and str(v).strip()]
                text = prefix + '；'.join(parts) if parts else None
            else:
                text = f'{prefix}{str(item)}'
            if text:
                records.append({'content': text, 'source': key})
    
    add('cases', '【案例】')
    add('acupoint_knowledge', '【穴位知识】')
    add('treatment_principles', '【调理原则】')
    add('golden_quotes', '【金句】')
    add('keywords', '【关键词】')
    add('refined_principles', '【精炼原则】')
    add('refined_quotes', '【精炼金句】')
    
    out = os.path.join(src_dir, fname.replace('.json', '.jsonl'))
    with open(out, 'w', encoding='utf-8') as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
    print(f'{fname} → {os.path.basename(out)} ({len(records)}条)')
```

### 3. 关联到App
Dify App → 检索设置 → 关联知识库 → 挂载底座知识库（个人经验库在前，底座在后）

## 两层知识库架构
```
AI分身个人知识库（清洗后JSONL）→ 各自分身独立调用
共享底座知识库（原书Markdown）  → 所有分身共享检索
```
检索优先级在 Dify App 设置里控制，不需要改 Starsower_v2 代码。

## Dify App知识库挂载顺序
推荐：个人经验库在前（优先召回），底座知识库在后（兜底补充）。

## 关键教训（2026-07-28）
1. **LightRAG废弃**：191块仅原文32%，顺序乱，file_path=unknown_source，直接用OCR markdown
2. **原书不清洗**：违规词（传统经络针法/用针/患者/治疗等）在书里原样保留，靠AI输出层REDLINE拦截
3. **JSON上传必须转JSONL**：Dify不认自定义schema，会报0字符
4. **输出文件记录精确大小**：避免混淆中间文件和最终文件
