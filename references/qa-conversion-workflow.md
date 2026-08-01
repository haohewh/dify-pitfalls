# Q&A 格式转换工作流（2026-07-29 实测）

## 问题根因

Dify 知识库 chunk 是「字段堆砌格式」，向量检索匹配率低：
```
【案例】id：CASE-009；condition：左脚红肿疼痛；symptoms：['左脚第二趾及脚背红肿疼痛', '刺痛']；acupoints：[...]；treatment_method：...；effect：...
```
用户问"脚肿痛91岁女"，和整段包含几十个字段的 chunk 做向量相似度，匹配率低。

## 解法

转换为 Q&A 格式，每条独立向量化：
```
问：左脚红肿疼痛怎么按揉？
答：91岁女性左脚红肿疼痛，属足阳明胃经。可按揉太冲、内庭、足临泣等穴位...

问：左脚红肿疼痛有什么效果？
答：4-5次后脚背皮肤出现皱纹，疼痛减轻，持续1月余恢复正常...
```

## 已生成的 Q&A 文件

| 老师 | 案例数 | Q&A条数 | 文件 |
|------|--------|---------|------|
| 老师乙 | 85 | 317条 | `老师乙经验精炼_QA.md` |
| 老师戊 | 72 | 329条 | `老师戊经验精炼_QA.md` |
| 老师丙 | 72 | 324条 | `老师丙经验精炼_QA.md` |
| 老师丁 | 22 | 111条 | `老师丁经验精炼_QA.md` |
| 老师甲 | 28 | 162条 | `老师甲经验精炼_QA.md` |

路径：`D:\AI\AI产品\25 AI经验平台经验\最终知识库上传\`

## 上传步骤

1. Dify Studio 打开对应知识库
2. **删除旧文档**（老师甲经验精炼_合规.md）
3. 上传 `_QA.md` 文件
4. **分段格式选「Q&A」**（不是「段落」或「全文档」）
5. 等索引完成（状态变 `completed`）
6. 逐个操作，每次间隔 ≥2 分钟（避免 MiniMax RPM 限流）

## Q&A 生成脚本逻辑

```python
import re, json

def clean_array(s):
    """清理 ['a', 'b'] 格式为 'a、b'"""
    if not s or not s.startswith('['):
        return s
    try:
        arr = json.loads(s.replace("'", '"'))
        return '、'.join(arr)
    except:
        items = re.findall(r"['\"](.+?)['\"]", s)
        return '、'.join(items)

def convert_case_to_qa(case_text, case_id):
    """将单个案例块转为多条 Q&A"""
    qa_lines = []
    fields = {}
    for seg in case_text.split('；'):
        seg = seg.strip()
        if '：' in seg:
            k, v = seg.split('：', 1)
            fields[k.strip()] = v.strip()
    
    condition = fields.get('condition', '')
    symptoms = clean_array(fields.get('symptoms', ''))
    meridian = fields.get('meridian_analysis', '')
    acupoints = clean_array(fields.get('acupoints', ''))
    treatment = fields.get('treatment_method', '')
    effect = fields.get('effect', '')
    principles = clean_array(fields.get('key_principles', ''))
    patient = fields.get('patient_info', '')
    
    # 症状问法
    if symptoms:
        qa_lines.append(f"问：{condition}有什么症状？\n答：{symptoms}。")
    # 穴位问法
    if acupoints:
        qa_lines.append(f"问：{condition}按揉哪些穴位？\n答：{acupoints}。")
    # 方法问法
    if treatment:
        qa_lines.append(f"问：{condition}怎么按揉？\n答：{treatment}。")
    # 效果问法
    if effect:
        qa_lines.append(f"问：{condition}效果怎么样？\n答：{effect}。")
    # 原则问法
    if principles:
        qa_lines.append(f"问：{condition}按揉要遵循什么原则？\n答：{principles}。")
    # 综合问法
    if meridian:
        qa_lines.append(f"问：{condition}属于哪条经络？怎么分析？\n答：{meridian}。")
    
    return qa_lines

# 主循环：读文件 → 解析案例块 → 输出 Q&A
```
