# 第2批索引下线（灰度版）

目标：按步骤逐个下线索引，并在每一步执行 SQL `EXPLAIN` 校验，避免性能回退。

> 校验脚本会自动生成 Markdown 报告并归档到 `backups/index-check-reports/`。

## 步骤设计

- `20260309_03`：下线 `practices.idx_practice_user`
- `20260309_04`：下线 `practices.idx_practice_hospital`
- `20260309_05`：下线 `audit_logs.idx_audit_logs_action`

每一步都支持独立回滚（`alembic downgrade -1`）。

## 执行前准备

在 `backend` 目录执行：

```bash
./venv/bin/alembic current
./venv/bin/python scripts/check_index_regression.py --step all
```

## 灰度执行流程（推荐）

### Step 1：下线 `idx_practice_user`

```bash
./venv/bin/alembic upgrade 20260309_03
./venv/bin/python scripts/check_index_regression.py --step practice_user
```

期望命中索引：
- `idx_practice_user_id`

### Step 2：下线 `idx_practice_hospital`

```bash
./venv/bin/alembic upgrade 20260309_04
./venv/bin/python scripts/check_index_regression.py --step practice_hospital
```

期望命中索引：
- `idx_practice_hospital_created_at`

### Step 3：下线 `idx_audit_logs_action`

```bash
./venv/bin/alembic upgrade 20260309_05
./venv/bin/python scripts/check_index_regression.py --step audit_action
```

期望命中索引：
- `idx_audit_logs_action_created_id`

## 回滚策略

任一步发现回退：

```bash
./venv/bin/alembic downgrade -1
```

然后复测：

```bash
./venv/bin/python scripts/check_index_regression.py --step all
```

## 仅控制台模式（可选）

```bash
./venv/bin/python scripts/check_index_regression.py --step all --no-report
```
