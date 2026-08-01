# Dify 输入预处理规则级联Bug：知识chunk被规则多次篡改

## 问题现象
Dify streaming 界面回答出现重复词叠加，如：
- "传统经络针法**理理法理法法**"
- "传统经络针法**理法理法**"

但 blocking API 测试正常；Dify 界面开新对话也正常——说明不是知识库内容本身的问题。

## 根因：三阶段叠加

```
阶段1（输入预处理）：知识chunk文本被pre_prompt规则篡改
  chunk里的"经络理法" → 匹配"法理→理法" → 变成"传统经络针法理理法"

阶段2（模型生成）：模型从已被篡改的上下文生成文本
  输出"传统经络针法理理法"

阶段3（输出后处理）：post-process规则再次叠加
  匹配"理法→理法" → 变成"传统经络针法理理法理法"
```

## 实际完整链路（2026-07-27 实测）

Dify blocking API 直调正确，但 Starsower_v2 → Dify 错误。差异在于 Starsower_v2 的 enriched_prompt 包含了 avatars.system_prompt（带规则5），Dify 模型收到的输入 context 已带篡改规则。

```
Starsower_v2 chat.py REDLINE_REPLACE（3条有害规则）
  ("传统经络针法", "经络理法")  ← 长词优先匹配遮蔽短词
  ("内针", "内针理法")          ← 短词再次触发
  ("法理", "理法")              ← 和 Dify pre_prompt 规则重复

→ Dify 返回 "经络理法分享"
→ chat.py _apply_redline 处理后 → "传统经络针法理理法理法法分享"
```

## 修复原则

### 原则1：禁止规则里绝对不能出现错误变体
❌ 错误写法：
```
禁止出现：传统经络针法理理法法、传统经络针法理理法理法法
```
→ 模型会把禁止列表当学习样本，反而生成这些表述

✅ 正确写法：
```
标准表达是"经络理法"，只能说这4个字，不得使用任何其他后缀或变体
```

### 原则2：输入预处理规则不能和知识库已有内容冲突
"法理→理法" 这种通用替换会误伤 chunk 里已经正确的内容。

### 原则3：开新对话测 vs 续接对话测
- 续接对话（模型记住了错误上下文）→ 永远错
- 开新对话（全新 conversation_id）→ 正确

## 完整三处修复（2026-07-27 实测，必须同时执行）

### 第1处：Dify app_model_configs.pre_prompt（规则5）
```sql
UPDATE app_model_configs
SET pre_prompt = regexp_replace(pre_prompt, '\n5\. ?"法理"→"理法"', '', 'g')
WHERE app_id IN (SELECT id FROM apps WHERE name LIKE '%老师甲%');
docker restart docker-api-1
```

### 第2处：Starsower_v2 avatars 表 system_prompt（规则5）
```python
conn.execute("""
  UPDATE avatars
  SET system_prompt = replace(system_prompt, '\n5. "法理"→"理法"', '')
""")
```

### 第3处：Starsower_v2 chat.py REDLINE_REPLACE（3条规则）
从 REDLINE_REPLACE 删除这3条：
- `("传统经络针法", "经络理法")`
- `("内针", "内针理法")`
- `("法理", "理法")`

改完必须重启 Starsower_v2：
```bash
pkill -9 -f "uvicorn.*starsower"
cd /opt/myapp
nohup /opt/myapp/venv/bin/python3 -m uvicorn main:app --host 0.0.0.0 --port 8001 &
```

### 为什么三处都要改？
| 只改 Dify pre_prompt | → 问题依旧 |
| 只改 Starsower avatars | → 问题依旧 |
| 只改 chat.py REDLINE | → 问题依旧 |
| 三处全改 | → 问题消失 ✓ |

## 验证修复（用全新 user_id）
```bash
curl -s --max-time 40 -X POST "http://localhost:8001/api/chat" \
  -H "Content-Type: application/json" \
  -d '{"avatar_id":1,"message":"传统经络针法是什么","user_id":"brand_new_user"}'
# 期望：无 "理理法理法法"，无 "理理法法"
```

## streaming vs blocking API 差异
- **blocking API**：只走提示词，不触发 RAG 检索 pipeline，可能正确
- **streaming API**：走完整 RAG pipeline（知识检索 → 拼 context → 输入预处理 → 模型生成 → 输出后处理），更容易受预处理规则影响
- **结论**：blocking 正确不等于 streaming 正确，诊断时 blocking + 新 user_id 只能排除知识库问题，不能排除 RAG pipeline 中的预处理规则问题
- **正确诊断**：在 Dify 界面开新对话（New Conversation）测试

## 温度参数影响
- 高 temperature（默认）→ 模型更容易产生重复模式
- 低 temperature（0.1）→ 输出更精准稳定
- 老师甲：temperature=0.1, top_p=0.3（低温度，更精准）
- 老师乙/老师戊/老师丙/老师丁：默认温度（更高，更发散，可能更容易出重复词）
