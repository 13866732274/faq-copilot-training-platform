# 咨询话术模拟训练与智能知识库系统

源码仓库：<https://github.com/13866732274/faq-copilot-training-platform>

本项目面向咨询团队的新员工培训、优秀话术沉淀、FAQ 智能知识库、AI 辅助回复和运营统计场景。

## 核心能力

- 历史咨询对话导入：支持微 E 聊 / VEL 导出数据，以及 HTML、CSV、Excel 等格式。
- 案例库与模拟训练：将优秀对话转为可训练案例，支持咨询员模拟回复、标准答案对比和复盘。
- FAQ 智能知识库：通过问答抽取、Embedding、聚类和大模型精炼生成可复用知识条目。
- AI 问答助手：支持语义搜索、快捷回复候选、采纳打点和高置信秒回。
- 后台管理：用户、角色、权限、租户、科室、分类标签、任务、日志、统计报表等管理能力。
- OpenClaw / 微信 Webhook：支持作为外部咨询渠道的 AI 推荐回复接口。

## 技术栈

- 前端：Vue 3、TypeScript、Vite、Element Plus、Pinia、Vue Router、ECharts
- 后端：FastAPI、SQLAlchemy 2.x、Alembic、MySQL/MariaDB
- 异步任务：Celery、Redis、BackgroundTasks fallback
- AI：阿里云 DashScope / 通义千问、text-embedding-v3
- 部署：Nginx、systemd、Linux

## 目录说明

```text
backend/                    FastAPI 后端服务
frontend/                   Vue 3 前端项目
openclaw-skill-faq-webhook/ OpenClaw Webhook Skill 示例
scripts/                    运维和辅助脚本
docs/                       项目文档与交付说明
```

## 本地配置

复制环境变量示例：

```bash
cp backend/.env.example backend/.env
```

然后按实际环境填写：

- `DATABASE_URL`
- `JWT_SECRET_KEY`
- `DASHSCOPE_API_KEY`
- `BOT_WEBHOOK_SECRET`
- `FAQ_BOT_USERNAME`
- `FAQ_BOT_PASSWORD`

注意：真实 `.env`、API Key、数据库密码、日志和构建产物不要提交到 Git 仓库。

## AI 模型配置建议

当前推荐：

- FAQ 管道 / quality 模式：`qwen-plus`
- Copilot auto / fast / balanced：`qwen-turbo`
- Embedding：`text-embedding-v3`

系统已支持高置信直通，命中高质量 FAQ 时跳过 LLM，降低延迟和调用成本。
