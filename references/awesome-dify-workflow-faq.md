# Awesome-Dify-Workflow FAQ 参考

Repo: https://github.com/xxx/awesome-dify-workflow (推测)
Stars: 10,720 ★
Forks: 1,076
Last update: 2026-07-28

## 直接相关的 FAQ 踩坑总结

| 场景 | FAQ 解法 | 我们的情况 |
|------|---------|-----------|
| 知识库永久排队 | `.env` 加 `LOG_FILE=/app/logs/server.log`，重启容器 | 未验证，可参考 |
| Docker 镜像拉不下来 | 所有 image 前加 `dockerpull.org/` | 国内服务器常见问题 |
| 大文件上传报错 | nginx 也要改 `client_max_body_size` | 已验证一致 |
| 管理员密码忘了 | `docker exec docker-api-1 flask reset-password` | Dify 1.15.0+ 实测有效 |

## 对经验平台项目的价值

- 大量现成 DSL 文件，导进 Dify Studio 就能用
- 含知识库检索优化的工作流模板 — 直接学检索参数设置
- FAQ 区踩坑总结可减少试错时间

自学入口：dify101.com（推荐的中文教程站）
