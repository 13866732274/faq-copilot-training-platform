# 数据库备份与恢复（最小化运维预案）

本文档对应 P0-5，目标是让运维在不改业务代码的前提下，完成每日备份与按需恢复。

## 1. 适用范围

- 项目：`chattrainer`
- 数据源：`backend/.env` 中的 `DATABASE_URL`
- 脚本：
  - 备份：`scripts/backup.sh`
  - 恢复：`scripts/restore.sh`

## 2. 依赖要求

- Linux 环境
- 已安装 `mysql` / `mysqldump` 客户端
- 能访问 `DATABASE_URL` 指向的数据库

建议安装命令（Ubuntu）：

```bash
sudo apt-get update
sudo apt-get install -y mysql-client
```

## 3. 备份执行

在项目根目录执行：

```bash
bash scripts/backup.sh
```

默认行为：

- 从 `backend/.env` 读取 `DATABASE_URL`
- 生成压缩备份：`backups/mysql/<库名>_YYYYmmdd_HHMMSS.sql.gz`
- 自动清理 30 天前的旧备份

可选参数（环境变量）：

```bash
BACKUP_DIR=/data/chattrainer-backups RETENTION_DAYS=15 bash scripts/backup.sh
```

## 4. 恢复执行

示例（需要显式确认）：

```bash
bash scripts/restore.sh --file backups/mysql/chattrainer_20260307_081500.sql.gz
```

跳过确认（慎用）：

```bash
bash scripts/restore.sh --file backups/mysql/chattrainer_20260307_081500.sql.gz --yes
```

支持文件类型：

- `.sql`
- `.sql.gz`

## 5. 定时任务（crontab）

建议每天凌晨 3:00 自动备份：

```cron
0 3 * * * cd /www/wwwroot/chattrainer && /usr/bin/env bash scripts/backup.sh >> /www/wwwroot/chattrainer/backups/backup.log 2>&1
```

## 6. 恢复演练建议（上线前必做）

每月至少做 1 次演练：

1. 在测试库执行恢复
2. 登录系统检查核心功能：
   - 登录/用户管理
   - 题库导入与列表
   - 练习记录与统计
3. 确认数据完整后记录演练时间与结果

## 7. 注意事项

- 恢复会覆盖目标库同名对象，务必先确认环境（生产/测试）。
- 生产恢复前建议先做一次即时备份，避免误操作不可回退。
- 脚本依赖 `backend/.env` 的 `DATABASE_URL`，变更数据库连接后需同步校验。

## 8. 一键恢复演练（测试库）

新增脚本：`scripts/drill-restore-test.sh`

功能：

- 自动恢复到测试库（不触碰生产库）
- 生成演练报告到 `backups/drill-reports/`
- 包含生产风险硬拦截（库名冲突与命名规则校验）

执行示例：

```bash
# 方式1：使用 backend/.env.test 的 DATABASE_URL
bash scripts/drill-restore-test.sh --yes

# 方式2：显式指定测试库连接串（优先级最高）
DRILL_DATABASE_URL='mysql+asyncmy://user:pass@127.0.0.1:33060/chattrainer_test' \
bash scripts/drill-restore-test.sh --yes

# 仅检查，不执行恢复
bash scripts/drill-restore-test.sh --dry-run
```

注意：

- 测试库名必须包含 `test`/`drill`/`staging`/`sandbox`，否则脚本会硬拦截。
- 若测试库名与生产库名相同，脚本会硬拦截并直接退出。

## 9. 一键一致性巡检（只读）

新增脚本：`scripts/check-consistency.sh`

用途：

- 升级后快速验收医院-科室-用户-题库-练习-审计的关键绑定一致性
- 仅检查，不改任何数据
- 自动生成报告到 `backups/consistency-reports/`

执行示例：

```bash
bash scripts/check-consistency.sh
```

退出码说明：

- `0`：巡检通过
- `2`：存在异常项（需查看报告）

建议：

- 每次执行迁移（`alembic upgrade head`）后，立即执行一次该脚本并归档报告。

## 10. 全仓中文巡检（只扫描不改）

新增脚本：`scripts/check-zh-ui.sh`

用途：

- 扫描前端 UI 可见文案中疑似英文残留（消息提示、弹窗、占位符、标签、模板文本）
- 仅输出清单，不改任何代码
- 自动生成报告到 `backups/i18n-reports/`

执行示例：

```bash
bash scripts/check-zh-ui.sh
```

可选参数：

```bash
# 自定义扫描目录与报告目录
TARGET_DIR=/www/wwwroot/chattrainer/frontend/src \
REPORT_DIR=/www/wwwroot/chattrainer/backups/i18n-reports \
bash scripts/check-zh-ui.sh
```

退出码说明：

- `0`：未发现疑似英文残留
- `2`：发现疑似英文残留（需查看报告并逐项处理）
