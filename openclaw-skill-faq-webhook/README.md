# faq-webhook — OpenClaw Skill

将微信消息转发到 ChatTrainer 服务器，由服务器完成 FAQ 匹配和合规处理后返回回复。

## 安装

```bash
# 把整个 faq-webhook 文件夹复制到 OpenClaw Skills 目录
# Linux:
cp -r faq-webhook ~/.openclaw/skills/

# Windows:
# 复制到 C:\Users\<你的用户名>\.openclaw\skills\faq-webhook\

# 热加载
openclaw skills reload faq-webhook
```

## 配置

编辑 `manifest.json` 中的 `config`：

| 字段 | 说明 |
|------|------|
| `webhook_url` | 你的 ChatTrainer 服务器地址 + `/api/v1/bot/wechat-faq` |
| `feedback_url` | （可选）反馈回传地址，默认 `<webhook_url>/feedback` |
| `bot_secret` | 在 ChatTrainer 系统设置中配置的 `bot_webhook_secret` 值 |
| `health_url` | 健康检查地址（Watchdog 用） |
| `mode_risk_keywords` | 自动路由关键词（命中后走 `quality`） |

## 服务器端配置

在 ChatTrainer 后台 → 系统设置 中添加：

- `bot_webhook_secret`：任意强密码字符串（Bot 认证用）
- `bot_config`（可选）：JSON 格式的高级配置

```json
{
  "sensitive_keywords": ["吃什么药", "要不要手术", "严重吗"],
  "confidence_auto": 0.65,
  "confidence_human": 0.35,
  "working_hours_start": 8,
  "working_hours_end": 22,
  "tenant_id": 1,
  "disclaimer": "您好，我是智能助手，以下回复仅供参考，不构成医疗诊断。\n\n"
}
```

## 验证

```bash
# 1. 确认服务器可达
openclaw run-skill faq-webhook healthCheck

# 2. 模拟一条消息
openclaw run-skill faq-webhook handleMessage \
  --sender "test_user" \
  --content "你们医院地址在哪？"
```

## 协议说明（当前版本）

- Skill 调用地址：`/api/v1/bot/wechat-faq`
- 签名头：`X-Hub-Signature-256: sha256=<hmac>`
- 签名算法：`HMAC-SHA256(secret, raw_json_body)`
- 内置重试：默认 2 次（可在 `manifest.json` 调整 `retry_times`）
- 追踪头（新增）：`X-Request-Id` / `X-Timestamp` / `X-Nonce` / `X-OpenClaw-Version` / `X-Client`
- 请求体关键字段（新增）：`message_id` `session_id` `request_id` `trace_id` `retry_count` `version`
- 返回结构（主接口）：
  - `reply`: 实际发送文案（默认候选1）
  - `panel_id`: 与后台 copilot 面板一致，可用于反馈打点
  - `candidates`: 最多 3 条候选回复
  - `confidence / quality_mode_requested / quality_mode_effective / quality_route_reason`: 质量与路由信息
- 反馈回传地址：`/api/v1/bot/wechat-faq/feedback`
  - 入参：`request_id/trace_id/message_id/session_id/panel_id/action/delivery_status/user_feedback` 等

## 质量模式透传（微信端与学员端一致）

- Skill 会自动推断并透传 `quality_mode`：
  - 显式传入 `quality_mode` 时优先使用（`auto|fast|balanced|quality`）
  - 语音/图片/文件消息默认 `quality`
  - 短文本（<=4字）默认 `fast`
  - 命中 `mode_risk_keywords` 默认 `quality`
  - 其余默认 `balanced`
- 服务端会返回 `quality_mode_requested` 与 `quality_mode_effective` 便于追踪。
