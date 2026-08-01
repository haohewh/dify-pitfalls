# Dify 踩坑记录（Dify Pitfalls）

> 从真实生产环境中踩出来的 Dify 坑，全部亲测修复，绝不纸上谈兵。

## 项目简介

本项目沉淀了我们在生产环境部署、运维 Dify 平台过程中遇到的 **63 个真实 Bug** 及完整解决方案，外加 **29 篇深度专题文档**（知识库上传、Nginx 配置、插件调试、模型接入等）。

每一个坑都是"现象 → 排查路径 → 根因 → 解决方案"四段式记录，**可直接照着排查**，不用重新踩一遍。

## 内容目录

```
difycaikeng/
├── SKILL.md                    # 核心：63 个 Bug 记录（Bug1 ~ Bug55+）
├── references/                 # 29 篇深度专题文档
│   ├── 知识库上传类：dify-upload-md-workflow / json-reupload-workflow / md-json-dify-upload-workflow ...
│   ├── 部署运维类：dify-inplace-upgrade / dify-custom-basepath-build / weaviate-version-upgrade ...
│   ├── Nginx 类：nginx-config-rewrite-rule / nginx-joint-chat-routing / nginx-two-instances ...
│   ├── 插件类：plugin-credential-debug-workflow / custom-model-add-workflow ...
│   ├── 模型类：chain-diagnosis-116 / hybrid-search-weights-issue / token-mismatch-diagnosis-playbook ...
│   └── 业务集成类：starsower-dify-integration / qa-conversion-workflow / kb-rebuild-workflow ...
└── scripts/                    # 实用脚本（健康检查等）
```

## 踩坑分类（按高频场景）

| 分类 | 典型坑 | 涉及 Bug |
|------|--------|---------|
| **部署升级** | 容器重启路由丢失、原地升级失败、版本稳定性 | Bug1/3/15+ |
| **知识库上传** | 上传格式错误、JSON 重传、检索质量为 0 | Bug24/25+ |
| **模型接入** | 自定义模型添加、维度不匹配、Token 不一致 | 专题文档 |
| **Nginx 路由** | 子路径代理、重写规则、双实例 | 专题文档 |
| **插件调试** | 凭据加密、调试工作流 | 专题文档 |
| **业务集成** | 与业务系统对接、联合咨询路由 | 专题文档 |

## 使用方式

1. 遇到 Dify 问题时，先搜 `SKILL.md` 里的 Bug 标题（按现象关键词）
2. 找不到再翻 `references/` 对应分类的专题文档
3. 每个 Bug 都是"现象 → 排查 → 根因 → 解决"完整链路，照着排查即可

## 适合人群

- 在**国内服务器**上部署/运维 Dify 的团队（避坑价值最大）
- 使用 Dify 知识库做 RAG 应用的开发者
- 对接 Dify 与业务系统（微信、支付、分身/Agent）的工程师

## 贡献

欢迎提交 PR 补充你踩过的坑——格式见 `SKILL.md`（四段式：现象/排查/根因/解决）。

## License

[MIT](LICENSE)
