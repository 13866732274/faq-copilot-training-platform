# ChatTrainer Backend（当前阶段）

## 1. 安装依赖

```bash
cd /www/wwwroot/chattrainer/backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## 2. 准备 MySQL（可选：Docker MySQL 8.0）

```bash
cd /www/wwwroot/chattrainer
docker compose -f docker-compose.mysql8.yml up -d
```

若使用该容器，请将 `.env` 中 `DATABASE_URL` 改为：

```env
DATABASE_URL=mysql+asyncmy://user:password@127.0.0.1:33060/chattrainer
```

## 3. 本地验证 HTML 解析

```bash
cd /www/wwwroot/chattrainer/backend
PYTHONPATH=. python scripts/parse_sample.py
```

## 4. 启动服务

```bash
cd /www/wwwroot/chattrainer/backend
cp .env.example .env
# 根据实际 MySQL 账号修改 .env 中 DATABASE_URL
PYTHONPATH=. uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## 5. 初始化数据库（Alembic）

```bash
cd /www/wwwroot/chattrainer/backend
source venv/bin/activate
alembic upgrade head
```

## 6. 初始化管理员账号

```bash
cd /www/wwwroot/chattrainer/backend
source venv/bin/activate
PYTHONPATH=. python app/init_admin.py
```

## 7. 接口文档

- Swagger: `http://127.0.0.1:8000/docs`
- 健康检查: `GET /api/v1/health`
- 登录: `POST /api/v1/auth/login`
- 当前用户: `GET /api/v1/auth/me`
- 导入预览: `POST /api/v1/quizzes/upload`
- 确认导入落库: `POST /api/v1/quizzes/confirm`
- 题库列表: `GET /api/v1/quizzes`
- 题目详情: `GET /api/v1/quizzes/{id}`
