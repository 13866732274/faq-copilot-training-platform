# ChatTrainer 服务器交接与二开说明

本文件用于在服务器上继续开发、排障、交接给新同事或交给 Cursor 时快速对齐上下文。

## 1) 当前部署概览（内网）

- 访问地址：`http://192.168.9.139`
- API 健康检查：`http://192.168.9.139/api/v1/health`
- 运行模式：前后端分离（Nginx 托管前端静态资源 + 反向代理后端 API）
- 部署环境（目标机）：
  - Nginx `1.24.0`
  - MariaDB `10.11.6`
  - Node.js `20.x`
  - Python `3.10` + `venv`

## 2) 目录与关键文件

- 项目根目录：`/www/wwwroot/chattrainer`
- 后端目录：`/www/wwwroot/chattrainer/backend`
- 前端目录：`/www/wwwroot/chattrainer/frontend`
- 后端环境变量：`/www/wwwroot/chattrainer/backend/.env`
- 前端打包产物：`/www/wwwroot/chattrainer/frontend/dist`
- Nginx 站点配置：`/www/server/panel/vhost/nginx/192.168.9.139.conf`
- systemd 服务文件：`/etc/systemd/system/chattrainer-backend.service`
- 项目总文档：`/www/wwwroot/咨询话术模拟训练系统-项目开发文档.md`

## 3) 端口与流量路径

- 外部访问：`80`（HTTP）
- SSH：`10286`
- 宝塔面板：`34283`
- 后端服务：`127.0.0.1:8000`（仅本机监听，不直接暴露）
- 请求链路：`Browser -> Nginx:80 -> /api/* -> FastAPI:8000`

## 4) 数据库约定

- 数据库类型：MariaDB `10.11.6`
- 数据库名：`chattrainer`
- 字符集建议：`utf8mb4`
- 排序规则建议：`utf8mb4_unicode_ci`
- ORM/迁移：SQLAlchemy + Alembic
- 迁移命令（后端目录）：
  - `./venv/bin/alembic upgrade head`

## 5) 服务管理命令（常用）

### 后端服务

- 查看状态：`systemctl status chattrainer-backend`
- 重启服务：`systemctl restart chattrainer-backend`
- 查看日志：`journalctl -u chattrainer-backend -f`

### Nginx

- 配置检测：`nginx -t`
- 重载配置：`systemctl reload nginx`
- 错误日志：`/www/wwwlogs/nginx_error.log`

### 健康检查

- 本机后端：`curl -s http://127.0.0.1:8000/api/v1/health`
- 经过 Nginx：`curl -s http://127.0.0.1/api/v1/health`

## 6) 继续开发与发布流程（建议）

1. 在服务器修改代码（或从开发机同步代码）。
2. 后端改动：
   - `cd /www/wwwroot/chattrainer/backend`
   - `./venv/bin/pip install -r requirements.txt`（依赖变化时）
   - `./venv/bin/alembic upgrade head`（有迁移时）
   - `systemctl restart chattrainer-backend`
3. 前端改动：
   - `cd /www/wwwroot/chattrainer/frontend`
   - `npm install`（依赖变化时）
   - `npm run build`
   - `systemctl reload nginx`
4. 验证：
   - `curl -s http://127.0.0.1/api/v1/health`
   - 浏览器访问首页与关键页面

### 增量发布（推荐）

在开发机执行：

- `cd /www/wwwroot/chattrainer`
- `bash scripts/incremental_deploy.sh /www/wwwroot/migration-vars.env`

可选参数：

- `--with-backend-deps`（后端先安装依赖）
- `--with-frontend-deps`（前端先安装依赖）
- `--no-doc`（不同步项目总文档）

### 一键初始化新租户（含租户超级管理员）

脚本位置：`/www/wwwroot/chattrainer/backend/scripts/bootstrap_tenant_admin.py`

示例（交互式）：

- `cd /www/wwwroot/chattrainer/backend`
- `PYTHONPATH=. ./venv/bin/python scripts/bootstrap_tenant_admin.py`

示例（非交互）：

- `PYTHONPATH=. ./venv/bin/python scripts/bootstrap_tenant_admin.py --tenant-code hz-nanke --tenant-name 杭州男科 --username admin --password 123456 --real-name 杭州男科管理员 --operator platform_super_admin --allow-existing --reset-password`

效果：

- 自动创建租户（不存在时）
- 自动创建该租户的 `super_admin` 账号（租户内全权限）
- 自动初始化该租户 `system_settings`
- 自动写入 `audit_logs(action=tenant_bootstrap)`

## 7) 已知约束与注意事项

- 该服务器用于内网运行，当前按 HTTP 方案部署（未启用公网证书）。
- 不要把数据库密码、API Key 提交到 Git 仓库。
- `.env`、`migration-vars.env` 等含敏感信息文件，建议仅服务器本机保存并限制权限。
- 如要迁移到新服务器，优先使用已提供的迁移脚本与变量文件。

## 8) 给服务器端 Cursor 的“最少上下文清单”

每次开新对话，先告诉它这 8 件事：

1. 项目根目录是 `/www/wwwroot/chattrainer`
2. 主文档是 `/www/wwwroot/咨询话术模拟训练系统-项目开发文档.md`
3. 后端是 FastAPI + SQLAlchemy + Alembic（`backend`）
4. 前端是 Vue3 + Vite + Element Plus（`frontend`）
5. 数据库是 MariaDB，库名 `chattrainer`
6. 后端服务名 `chattrainer-backend`，Nginx 配置在 `192.168.9.139.conf`
7. 修改后要执行：后端重启、前端 build、健康检查
8. 所有改动要同步更新主文档的实施记录

## 9) 给 Cursor 的首条提示词模板（可直接复制）

```text
你现在在服务器上继续开发 ChatTrainer。
请先读取：
1) /www/wwwroot/chattrainer/SERVER_HANDOFF.md
2) /www/wwwroot/咨询话术模拟训练系统-项目开发文档.md

项目路径：/www/wwwroot/chattrainer
技术栈：FastAPI + SQLAlchemy + Alembic + Vue3 + Vite + Element Plus
数据库：MariaDB，库名 chattrainer
服务：systemd=chattrainer-backend，Nginx 站点配置= /www/server/panel/vhost/nginx/192.168.9.139.conf

要求：
- 先做现状检查（服务状态、健康检查、最近变更）
- 再按文档优先级执行未完成项
- 每次改动后完成构建/重启/验证
- 最后把实施记录写回项目文档
```
