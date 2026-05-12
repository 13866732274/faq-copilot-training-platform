# 微信自动回复集成方案 — 对接 FAQ AI 问答助手

> 版本：v3.1（代码实装版）  
> 日期：2026-03-16  
> 核心目标：**用一个微信号专门接患者咨询，自动调用已训练好的 FAQ 知识库生成"类真人"回复，引导患者到院就诊。**  
> FAQ 知识库的训练数据从其他渠道获取，跟微信无关。微信只是自动回复的"出口"。

---

## 〇、上线前强制 Checklist（不通过就不能投产）

> 以下三项是本方案的**硬伤**，不解决只能算 70 分。每一项必须有对应的技术落地，不是"注意事项"能敷衍的。

### 硬伤 1：封号风险 ≠ "频率控制就能解决"

| 事实 | 说明 |
|------|------|
| WechatFerry 原理 | DLL 注入微信进程，属于逆向 hook |
| 微信反制手段 | 热更新改签名、加进程保护、内存扫描 |
| 历史频率 | 平均 3-6 个月一次"大清扫"，批量封 7 天→永久 |
| 杀伤力 | 正式号被封 = 患者加不到你 = 业务直接中断 |
| QClaw 优势 | 腾讯自研，不依赖 DLL 注入，封号风险显著低于 WechatFerry |
| QClaw 局限 | 仍依赖微信 PC 客户端运行，不是 100% 零风险 |

**强制要求**：

- [x] **推荐方案改为 QClaw/OpenClaw**（腾讯自研，不注入 DLL，风险远低于 WechatFerry）
- [ ] **企业微信兜底脚本必须在上线前写好**，不是"远期考虑"（见第八章）
- [ ] **切换 SOP 文档化**：从发现封号到企业微信接管，目标 < 30 分钟
- [ ] **测试号先跑 2 周**，期间 0 封号记录才能切正式号
- [ ] **双号热备**：主号异常时备用号 30 秒内接管

---

### 硬伤 2：Windows 宿主机是单点故障

| 故障场景 | 后果 |
|----------|------|
| 断电 / 蓝屏 | 链路中断，患者消息无人应答 |
| 微信崩溃 / 自动更新重启 | Bot 失联 |
| 网络抖动 | API 调用失败 |

**强制要求**：

- [ ] **Hyper-V / VMware 虚拟机 + 快照**：故障后 10 分钟内整机重建
- [ ] **Watchdog 守护进程**（每 60 秒自检）：
  - 检查微信进程是否存活
  - 检查 OpenClaw 是否正常
  - 检查网络到 192.168.9.139 是否通
  - 异常 → 飞书/钉钉/短信告警 + 自动尝试重启
- [ ] **双号热备**（进阶）：主号掉线 → 备用 Windows 实例自动启动 → 30 秒切换
- [ ] **关闭 Windows 自动更新**（GPO 或 服务禁用）
- [ ] **关闭微信自动更新**（QClaw 依赖特定版本范围）

```
Watchdog 伪代码（放在 Windows 计划任务里，每 60 秒执行）
───────────────────────────────────────────────────────
1. 检查进程：tasklist | findstr WeChat.exe → 不存在则重启微信
2. 检查 OpenClaw：HTTP GET http://localhost:OClaw端口/health → 超时则重启
3. 检查 API：curl http://192.168.9.139/api/v1/health → 不通则告警
4. 以上任何一项失败 → 发告警到飞书/钉钉 webhook
```

---

### 硬伤 3：医疗合规灰色地带

| 风险 | 说明 |
|------|------|
| 法律依据 | 《互联网诊疗管理办法》《医疗广告管理办法》 |
| 红线 | 自动回复涉及具体诊疗建议 = "非法执业"，罚款 5 万起 |
| 场景 | 患者问"吃啥药""要不要手术""严重吗"，Bot 如果回答了 = 出事 |

**强制要求**（硬编码到 Bot 和 FAQ 知识库中）：

- [ ] **敏感关键词拦截**——命中即转人工，Bot 绝对不回：
  ```
  吃什么药, 吃啥药, 怎么用药, 开药, 处方, 药物,
  要不要手术, 手术风险, 能治好吗, 严重吗, 会死吗,
  诊断, 确诊, 病因, 化验单, 报告单, CT, 核磁,
  多少钱, 费用, 报销, 医保, 价格,（费用类可选开放）
  ```
- [ ] **首条自动回复固定免责前缀**：
  ```
  "您好，我是XX医院智能助手，以下回复仅供参考，不构成医疗诊断。
   具体情况请到院面诊，由专业医生为您详细评估。"
  ```
- [ ] **FAQ 知识库训练时排除诊疗内容**：只保留地址、科室介绍、工作时间、挂号流程、停车指引等安全信息
- [ ] **所有 Bot 回复日志留存**：时间、患者 ID、问题原文、回复原文、置信度、是否转人工
- [ ] **定期审查**：每周抽检 Bot 回复记录，发现越线内容立即调整知识库

---

## 一、方案架构（v3.0 修正版）

### 推荐技术栈：QClaw/OpenClaw（替代 WechatFerry）

| 对比项 | WechatFerry | QClaw/OpenClaw |
|--------|-------------|----------------|
| 原理 | DLL 注入微信进程 | 腾讯自研框架，非侵入式 |
| 封号风险 | **高**（逆向注入，微信主动检测） | **较低**（腾讯自家产品，不改微信进程） |
| 部署复杂度 | 手动安装，版本锁定 | 一键部署，5 分钟 |
| 扩展能力 | 纯 Python 脚本 | 支持 Skill 插件、MCP 协议、Webhook |
| 多平台 | 仅微信 PC | 微信/QQ/WhatsApp/Telegram/Slack |
| 社区 | 开源但个人维护 | 腾讯官方 + 开源社区 |
| 适合场景 | 快速验证 | **生产环境推荐** |

**你本地已安装 OpenClaw，直接用它开发自定义 Skill 来对接 FAQ API。**

### 架构图

```
┌──────────┐         ┌──────────────────────────┐         ┌──────────────────────┐
│  患者微信  │ ──────► │  你的专用微信号             │ ──────► │  你的服务器            │
│          │         │  (Windows 主机)            │         │  192.168.9.139       │
│  "地址在哪" │         │                          │         │                      │
│          │         │  OpenClaw 本地运行          │  HTTP   │  FAQ AI 问答助手      │
│          │         │   └ faq-reply Skill       │ ──────► │  /api/v1/faq/copilot │
│          │ ◄────── │     ├ 合规拦截（敏感词）     │ ◄────── │  返回推荐回复          │
│  收到回复  │         │     ├ 免责前缀              │         │                      │
│          │         │     ├ 模拟真人延迟           │         │                      │
│          │         │     └ 低置信度→转人工通知     │         │                      │
└──────────┘         └──────────────────────────┘         └──────────────────────┘
                              │                                      │
                              │  故障时自动切换                        │
                              ▼                                      │
                     ┌──────────────────┐                            │
                     │  企业微信兜底      │  ─── 同一 FAQ API ──────────┘
                     │  (官方 API, 零封号) │
                     └──────────────────┘
```

---

## 二、对接的就是这个接口

你截图中的"AI 问答助手"页面，后端接口：

```
POST http://192.168.9.139/api/v1/faq/copilot
```

**请求**：
```json
{
  "query": "你们医院地址在哪里？",
  "quality_mode": "auto"
}
```

**返回**：
```json
{
  "data": {
    "recommended_reply": "您好，我院位于XXX路XXX号，地铁X号线XXX站...",
    "confidence": 0.87,
    "quality_mode_effective": "balanced",
    "latency_ms": 2800
  }
}
```

Bot 要做的：把 `recommended_reply` 加上免责前缀发给患者。**就这一件事**。

---

## 三、方案 A（推荐）：OpenClaw 自定义 Skill

你已经安装了 OpenClaw，用它的 Skill 机制对接 FAQ API 是最合理的路线：

### 3.1 Skill 目录结构

在你的 OpenClaw Skills 目录下创建：

```
openclaw/skills/faq-reply/
├── manifest.json          # Skill 描述与配置
├── __init__.py            # Skill 入口
├── faq_client.py          # FAQ API 调用封装
├── compliance.py          # 合规拦截（敏感词 + 免责前缀）
├── humanizer.py           # 模拟真人（延迟 + 内容微调）
├── watchdog.py            # 健康自检
├── config.yaml            # 可热更新的配置
└── requirements.txt       # requests, pyyaml
```

### 3.2 manifest.json

```json
{
  "name": "faq-reply",
  "version": "1.0.0",
  "description": "接收微信患者消息，调用 FAQ AI 问答助手自动回复并引导到院",
  "author": "chattrainer",
  "entry": "__init__.py",
  "permissions": ["network", "messaging"],
  "config": {
    "faq_api_base": "http://192.168.9.139/api/v1",
    "bot_username": "wechat_bot",
    "bot_password": "",
    "confidence_auto": 0.65,
    "confidence_human": 0.35,
    "delay_min_sec": 1.5,
    "delay_max_sec": 4.0,
    "human_notify_wxid": "filehelper",
    "max_reply_per_min": 12,
    "cooldown_same_user_sec": 8,
    "working_hours_start": 8,
    "working_hours_end": 22
  }
}
```

### 3.3 config.yaml（可热更新，不用重启 Skill）

```yaml
# 合规敏感词 —— 命中任何一个 → 100% 转人工，Bot 不回
# 修改此文件即时生效，不需要重启 OpenClaw
sensitive_keywords:
  # 诊疗类（绝对红线）
  - 吃什么药
  - 吃啥药
  - 怎么用药
  - 开药
  - 处方
  - 药物
  - 要不要手术
  - 手术风险
  - 能治好吗
  - 严重吗
  - 会死吗
  - 诊断
  - 确诊
  - 病因
  - 化验单
  - 报告单

  # 费用类（可选开放，默认拦截）
  - 多少钱
  - 费用
  - 报销
  - 医保

# 免责前缀（每次首条回复强制携带）
disclaimer: "您好，我是智能助手，以下回复仅供参考，不构成医疗诊断。具体情况请到院面诊。\n\n"

# 不处理的消息（寒暄/太短/无意义）
skip_words:
  - 嗯
  - 哦
  - 好
  - 好的
  - ok
  - OK
  - 谢谢
  - 感谢
  - 拜拜
  - 再见
  - "👍"

# 危险词（直接忽略）
block_words:
  - 转账
  - 付款
  - 红包
  - 借钱

# 非工作时间自动回复
off_hours_reply: "您好，您的消息已收到。目前为非工作时间，工作人员将在明天上班后第一时间回复您，感谢您的耐心等待。"
```

### 3.4 compliance.py — 合规拦截模块

```python
"""合规拦截：敏感词检测 + 免责前缀 + 工作时间判断"""

import yaml
from datetime import datetime
from pathlib import Path

_CONFIG_PATH = Path(__file__).parent / "config.yaml"
_config_mtime = 0
_config = {}


def _reload_if_changed():
    global _config, _config_mtime
    try:
        mt = _CONFIG_PATH.stat().st_mtime
        if mt != _config_mtime:
            with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
                _config = yaml.safe_load(f) or {}
            _config_mtime = mt
    except Exception:
        pass


def is_sensitive(text: str) -> bool:
    """检查是否命中敏感词 → True 表示必须转人工"""
    _reload_if_changed()
    keywords = _config.get("sensitive_keywords", [])
    text_lower = text.lower()
    return any(kw in text_lower for kw in keywords)


def is_skip(text: str) -> bool:
    """检查是否是无意义消息"""
    _reload_if_changed()
    return text.strip() in _config.get("skip_words", [])


def is_blocked(text: str) -> bool:
    """检查是否是危险消息"""
    _reload_if_changed()
    return any(w in text for w in _config.get("block_words", []))


def get_disclaimer() -> str:
    _reload_if_changed()
    return _config.get("disclaimer", "")


def is_working_hours() -> bool:
    """是否在工作时间内"""
    _reload_if_changed()
    hour = datetime.now().hour
    start = _config.get("working_hours_start", 8)
    end = _config.get("working_hours_end", 22)
    return start <= hour < end


def get_off_hours_reply() -> str:
    _reload_if_changed()
    return _config.get("off_hours_reply", "您的消息已收到，工作人员将尽快回复您。")
```

### 3.5 faq_client.py — FAQ API 调用封装

```python
"""封装对 ChatTrainer FAQ API 的调用"""

import time
import requests
from loguru import logger


class FaqClient:
    def __init__(self, base_url: str, username: str, password: str):
        self._base = base_url.rstrip("/")
        self._username = username
        self._password = password
        self._token = None
        self._token_ts = 0

    def _ensure_token(self):
        if self._token and time.time() - self._token_ts < 3500:
            return
        try:
            r = requests.post(
                f"{self._base}/auth/login",
                json={"username": self._username, "password": self._password},
                timeout=10,
            )
            r.raise_for_status()
            self._token = r.json()["data"]["access_token"]
            self._token_ts = time.time()
            logger.info("FAQ API token refreshed")
        except Exception as e:
            logger.error(f"Token refresh failed: {e}")
            raise

    def ask(self, query: str, quality_mode: str = "auto") -> dict | None:
        """
        调用 AI 问答助手。
        返回 {"reply": str, "confidence": float, "mode": str} 或 None。
        """
        self._ensure_token()
        try:
            r = requests.post(
                f"{self._base}/faq/copilot",
                json={"query": query, "quality_mode": quality_mode},
                headers={"Authorization": f"Bearer {self._token}"},
                timeout=15,
            )
            if r.status_code == 401:
                self._token = None
                self._ensure_token()
                r = requests.post(
                    f"{self._base}/faq/copilot",
                    json={"query": query, "quality_mode": quality_mode},
                    headers={"Authorization": f"Bearer {self._token}"},
                    timeout=15,
                )
            if r.status_code == 200:
                d = r.json()["data"]
                return {
                    "reply": d.get("recommended_reply", ""),
                    "confidence": d.get("confidence", 0),
                    "mode": d.get("quality_mode_effective", ""),
                }
            logger.warning(f"FAQ API {r.status_code}: {r.text[:200]}")
        except Exception as e:
            logger.error(f"FAQ API error: {e}")
        return None
```

### 3.6 humanizer.py — 模拟真人

```python
"""模拟真人回复：延迟 + 内容微调"""

import time
import random


SUFFIXES = [
    "", "", "", "",  # 大概率不加
    "~",
    "，有其他问题随时问我",
    "，希望能帮到您",
]


def human_delay(text: str, delay_min: float = 1.5, delay_max: float = 4.0):
    """模拟打字延迟"""
    base = random.uniform(delay_min, delay_max)
    typing = len(text) * 0.04
    time.sleep(min(base + typing, 8.0))


def humanize(text: str) -> str:
    """微调回复内容，避免完全重复"""
    suffix = random.choice(SUFFIXES)
    return text.rstrip("。，！!.") + suffix
```

### 3.7 `__init__.py` — Skill 主入口

```python
"""
OpenClaw Skill: faq-reply
接收微信消息 → 合规拦截 → 调 FAQ AI 问答助手 → 模拟真人回复 → 低置信度转人工
"""

import json
import threading
from pathlib import Path
from loguru import logger

from .faq_client import FaqClient
from .compliance import (
    is_sensitive, is_skip, is_blocked,
    get_disclaimer, is_working_hours, get_off_hours_reply,
)
from .humanizer import human_delay, humanize

# 加载 manifest 配置
_manifest_path = Path(__file__).parent / "manifest.json"
with open(_manifest_path, "r", encoding="utf-8") as f:
    _manifest = json.load(f)
_cfg = _manifest.get("config", {})

# FAQ API 客户端
_faq = FaqClient(
    base_url=_cfg["faq_api_base"],
    username=_cfg["bot_username"],
    password=_cfg["bot_password"],
)

# 频率控制
_rate_log: list[float] = []
_user_last: dict[str, float] = {}
_lock = threading.Lock()
_MAX_RPM = _cfg.get("max_reply_per_min", 12)
_COOLDOWN = _cfg.get("cooldown_same_user_sec", 8)
_CONF_AUTO = _cfg.get("confidence_auto", 0.65)
_CONF_HUMAN = _cfg.get("confidence_human", 0.35)

# 记录是否已发过免责前缀（按会话）
_disclaimer_sent: set[str] = set()


def _rate_ok() -> bool:
    import time
    now = time.time()
    with _lock:
        _rate_log[:] = [t for t in _rate_log if now - t < 60]
        if len(_rate_log) >= _MAX_RPM:
            return False
        _rate_log.append(now)
        return True


def _cooldown_ok(user_id: str) -> bool:
    import time
    now = time.time()
    last = _user_last.get(user_id, 0)
    if now - last < _COOLDOWN:
        return False
    _user_last[user_id] = now
    return True


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  OpenClaw Skill 标准入口
#  OpenClaw 收到微信消息后会调用 execute()
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def execute(message: dict) -> dict | None:
    """
    OpenClaw 消息处理入口。
    message 结构（参考 OpenClaw 文档）:
    {
        "sender": "wxid_xxx",          # 发送者 wxid
        "content": "你们医院在哪？",    # 消息文本
        "is_group": false,             # 是否群消息
        "room_id": "",                 # 群 ID（群消息时）
        "msg_type": "text",            # 消息类型
    }

    返回:
    {"reply": "回复文本"} → OpenClaw 自动发送
    None → 不回复
    """
    text = (message.get("content") or "").strip()
    sender = message.get("sender", "")
    is_group = message.get("is_group", False)

    # ── 基本过滤 ──
    if not text or len(text) <= 1:
        return None
    if is_group:
        return None  # 暂不处理群消息
    if message.get("msg_type") != "text":
        return None
    if is_skip(text):
        return None
    if is_blocked(text):
        return None

    # ── 频率控制 ──
    if not _cooldown_ok(sender):
        logger.debug(f"[{sender}] cooldown skip")
        return None
    if not _rate_ok():
        logger.warning("rate limit exceeded")
        return None

    logger.info(f"← [{sender}] {text}")

    # ── 合规拦截：敏感词 → 100% 转人工 ──
    if is_sensitive(text):
        logger.info(f"→✋ [{sender}] 敏感词命中，转人工")
        _notify_human(sender, text, "敏感词命中")
        return {
            "reply": "您的问题我已记录，稍后会有专业工作人员为您详细解答，请稍等。"
        }

    # ── 非工作时间 ──
    if not is_working_hours():
        logger.info(f"→🌙 [{sender}] 非工作时间")
        return {"reply": get_off_hours_reply()}

    # ── 调用 FAQ AI 问答助手 ──
    result = _faq.ask(text, quality_mode="auto")

    if not result or not result.get("reply"):
        _notify_human(sender, text, "API 无响应")
        return None

    reply = result["reply"]
    conf = result["confidence"]

    # ── 免责前缀（每个会话首条必带） ──
    if sender not in _disclaimer_sent:
        reply = get_disclaimer() + reply
        _disclaimer_sent.add(sender)

    # ── 按置信度决策 ──
    if conf >= _CONF_AUTO:
        final = humanize(reply)
        human_delay(final)
        logger.info(f"→ [{sender}] conf={conf:.2f} | {final[:80]}...")
        return {"reply": final}

    elif conf >= _CONF_HUMAN:
        final = humanize(reply)
        human_delay(final)
        _notify_human(sender, text, f"中置信({conf:.2f})")
        logger.info(f"→⚠ [{sender}] conf={conf:.2f}")
        return {"reply": final}

    else:
        _notify_human(sender, text, f"低置信({conf:.2f})")
        logger.info(f"→✋ [{sender}] conf={conf:.2f} 转人工")
        return {
            "reply": "您的问题我已记录，稍后工作人员会为您回复，请稍等。"
        }


def _notify_human(patient_id: str, question: str, reason: str):
    """通知人工介入（通过 OpenClaw 的消息 API 发给指定 wxid）"""
    notify_wxid = _cfg.get("human_notify_wxid", "filehelper")
    try:
        # OpenClaw 提供的发送接口（具体参考你安装版本的文档）
        from openclaw.messaging import send_text
        send_text(
            to=notify_wxid,
            content=f"[Bot 转人工] {reason}\n患者: {patient_id}\n问题: {question}",
        )
    except ImportError:
        logger.warning("openclaw.messaging not available, notify skipped")
    except Exception as e:
        logger.error(f"Notify failed: {e}")
```

### 3.8 安装与启动

```bash
# 在你的 Windows 机器上（已安装 OpenClaw 的那台）

# 1. 把 faq-reply 目录放到 OpenClaw Skills 目录
# 默认路径：C:\Users\你的用户名\.openclaw\skills\faq-reply\
# 或：你的 OpenClaw 安装目录\skills\faq-reply\

# 2. 安装依赖
cd <openclaw-skills-path>/faq-reply
pip install requests pyyaml loguru

# 3. 修改 manifest.json 中的配置
# - faq_api_base: 你的服务器地址
# - bot_username / bot_password: 在 ChatTrainer 后台创建的 Bot 账号
# - human_notify_wxid: 你自己的微信 wxid

# 4. 修改 config.yaml 中的敏感词、免责前缀等

# 5. 重启 OpenClaw
openclaw restart
# 或在 OpenClaw 界面中刷新 Skills

# 6. 验证 Skill 已加载
openclaw skill list
# 应该能看到 faq-reply v1.0.0
```

---

## 四、方案 B（备用）：纯 Python 脚本 + WechatFerry

如果你的 OpenClaw 版本不支持自定义 Skill，或者有兼容性问题，可以退回到直接用 WechatFerry 的方案。**但封号风险更高**。

核心逻辑跟方案 A 完全一样（合规拦截、免责前缀、模拟真人、置信度分级），只是把 OpenClaw 的消息接口换成 WechatFerry：

```python
"""备用方案：WechatFerry + FAQ API（封号风险较高）"""

from wcferry import Wcf, WxMsg
# ... 其余逻辑与方案 A 的 __init__.py 相同
# 区别仅在于消息收发用 wcf.send_text() 而非 OpenClaw 的 messaging API

# 完整脚本见 v2.0 版本文档
```

> 建议：**优先走方案 A**。只有 OpenClaw 确实无法使用时才退回方案 B。

---

## 五、方案 C（首选 — 已实装代码）：OpenClaw Webhook 模式

> **已确认你的 OpenClaw 版本 2026.3.13 支持 Skill + Webhook。此方案已有完整代码。**

```
患者微信 → OpenClaw 收到消息
   → faq-webhook Skill 转发到服务器 POST /api/v1/bot/webhook
   → 服务器处理（合规拦截 + FAQ 检索 + 真人模拟）
   → 返回结构化回复
   → OpenClaw 按 delay_sec 延迟后发给患者
```

### 优势
- Windows 端零业务代码 → **只当消息网关**
- 所有逻辑集中在 192.168.9.139 → **升级/监控/审计最方便**
- 不需要 JWT Token 管理 → 用 **X-Bot-Secret 共享密钥**认证

### 5.1 服务器端（已实装）

**文件**：`backend/app/api/bot_webhook.py`（已创建）

**端点**：

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/bot/webhook` | 消息处理主接口 |
| GET | `/api/v1/bot/health` | 健康检查（Watchdog 用） |

**认证**：请求头 `X-Bot-Secret` 必须匹配系统设置中的 `bot_webhook_secret`。

**请求体**：
```json
{
  "sender": "wxid_xxx",
  "content": "你们医院地址在哪？",
  "is_group": false,
  "msg_type": "text"
}
```

**返回体**：
```json
{
  "action": "reply",
  "reply": "您好，我是智能助手...我院位于XXX路XXX号...",
  "confidence": 0.87,
  "transfer_reason": "",
  "delay_sec": 3.2
}
```

**action 值**：
| action | 含义 | OpenClaw 行为 |
|--------|------|--------------|
| `skip` | 不回复 | 忽略 |
| `reply` | 自动回复 | 等待 delay_sec 后发送 reply |
| `transfer` | 转人工 | 发送 reply（如"稍后工作人员回复"）+ 通知你 |

**内置合规逻辑**：
- 敏感词命中 → `action=transfer`，Bot 不给诊疗建议
- 首条消息 → 自动加免责前缀
- 非工作时间 → 自动回复"已收到，明天回复"
- 所有操作写入 `faq_copilot_logs` 表，mode 格式 `bot:reply:auto` / `bot:transfer:sensitive_keyword`

### 5.2 OpenClaw Skill（已创建模板）

**文件**：`openclaw-skill-faq-webhook/`（复制到 Windows 上的 `~/.openclaw/skills/faq-webhook/`）

只有 2 个核心文件：
- `manifest.json`：配置 webhook_url 和 bot_secret
- `index.js`：收到消息 → POST 到服务器 → 等 delay_sec → 返回 reply

```bash
# Windows 上安装
xcopy /E faq-webhook %USERPROFILE%\.openclaw\skills\faq-webhook\
# 修改 manifest.json 中的 bot_secret
# 热加载
openclaw skills reload faq-webhook
```

### 5.3 系统设置配置

在 ChatTrainer 后台 → 系统设置 中添加两个 key：

**必填**：
```
key: bot_webhook_secret
value: 一个强密码字符串（例如 sk-bot-xxxxxxxxxxxx）
```

**可选**（高级配置，JSON 格式）：
```
key: bot_config
value:
{
  "sensitive_keywords": ["吃什么药", "要不要手术", "严重吗", "诊断", "确诊", "处方"],
  "confidence_auto": 0.65,
  "confidence_human": 0.35,
  "working_hours_start": 8,
  "working_hours_end": 22,
  "tenant_id": 1,
  "disclaimer": "您好，我是智能助手，以下回复仅供参考，不构成医疗诊断。\n\n",
  "delay_min_sec": 1.5,
  "delay_max_sec": 4.0
}
```

> `bot_config` 不配置时使用代码中的默认值（已内置完整敏感词列表和合规规则）。

---

## 六、OpenClaw Embedding 修复（选方案 A）

你的 OpenClaw `memory_search` 报错是因为没有 Embedding 后端。你已经有百炼 Dashscope 的 API Key，直接用它：

### 修复步骤（5 分钟）

编辑 `~/.openclaw/config.json`，添加：

```json
{
  "embedding": {
    "provider": "openai-compatible",
    "baseUrl": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "apiKey": "your_dashscope_api_key",
    "model": "text-embedding-v3",
    "dimensions": 1024
  }
}
```

> 百炼的 Embedding API 兼容 OpenAI 格式，所以 provider 填 `openai-compatible` 即可。

```bash
# 重启 gateway 使配置生效
openclaw gateway restart

# 验证
openclaw test memory_search --query "测试搜索"
# 不再报 fetch failed 就算修好了
```

---

## 七、不需要创建 Bot 专用账号

方案 C（Webhook 模式）**不需要在 ChatTrainer 里创建用户账号**。原因：

- Webhook 端点用 `X-Bot-Secret` 认证，不走 JWT/用户体系
- Bot 的操作日志直接写入 `faq_copilot_logs`，`user_id=NULL`，`mode` 字段以 `bot:` 前缀区分
- 在 AI 问答统计页面，可以通过 `mode LIKE 'bot:%'` 过滤出 Bot 的所有调用

---

## 八、测试验证流程

### 阶段 1：Webhook 接口验证（10 分钟，不需要微信）

先在系统设置中配置 `bot_webhook_secret`，然后重启后端，用 curl 直接测试：

```bash
# 1. 健康检查
curl http://192.168.9.139/api/v1/bot/health
# 应返回 {"status":"ok","timestamp":"..."}

# 2. 测试正常问题
curl -X POST http://192.168.9.139/api/v1/bot/webhook \
  -H "Content-Type: application/json" \
  -H "X-Bot-Secret: 你配置的密钥" \
  -d '{"sender":"test_001","content":"你们医院地址在哪？","msg_type":"text"}'
# 应返回 action=reply，有 recommended_reply 和 delay_sec

# 3. 测试敏感词拦截
curl -X POST http://192.168.9.139/api/v1/bot/webhook \
  -H "Content-Type: application/json" \
  -H "X-Bot-Secret: 你配置的密钥" \
  -d '{"sender":"test_002","content":"我要吃什么药？","msg_type":"text"}'
# 应返回 action=transfer，transfer_reason=sensitive_keyword

# 4. 测试密钥错误
curl -X POST http://192.168.9.139/api/v1/bot/webhook \
  -H "Content-Type: application/json" \
  -H "X-Bot-Secret: wrong_secret" \
  -d '{"sender":"test","content":"test","msg_type":"text"}'
# 应返回 401
```

### 阶段 2：OpenClaw Skill 加载验证（30 分钟）

```bash
# 在 Windows 上

# 1. 复制 Skill
xcopy /E faq-webhook %USERPROFILE%\.openclaw\skills\faq-webhook\

# 2. 修改 manifest.json 中的 bot_secret

# 3. 热加载
openclaw skills reload faq-webhook

# 4. 验证
openclaw skill list
# 应该能看到 faq-webhook v1.0.0

# 5. 测试健康检查
openclaw run-skill faq-webhook healthCheck

# 6. 模拟消息
openclaw run-skill faq-webhook handleMessage \
  --sender "test_user" \
  --content "你们医院地址在哪？"
```

### 阶段 3：真实微信测试（1-2 天）

```
1. 用测试号登录微信 PC
2. 启动 OpenClaw（确认 faq-webhook Skill 已激活）
3. 用另一个微信给测试号发消息："你们医院在哪？"
4. 观察：
   a. OpenClaw 日志有没有收到消息
   b. 服务器日志有没有 Webhook 调用记录
   c. 患者有没有收到自动回复
   d. 发"吃什么药"是否正确拦截（不给诊疗建议）
   e. 首条消息是否带免责前缀
5. 在 ChatTrainer → AI 问答统计 中确认能看到 mode=bot:* 的日志
6. 持续测试 2 周，确认稳定且未被封号
```

### 阶段 4：切正式号（第 3 周）

全部通过才能投产：
- [ ] 测试号 2 周未被封号
- [ ] 敏感词拦截 100% 生效（所有医疗诊断类关键词都转人工）
- [ ] 免责前缀每个新会话首条必出现
- [ ] 低置信度正确转人工
- [ ] Watchdog 告警机制验证通过
- [ ] 企业微信兜底脚本已写好并测试通过
- [ ] 合规审查人员确认回复内容无问题
- [ ] 所有 Bot 回复日志可在后台查询

---

## 八、企业微信兜底方案（并行准备，不是远期）

**这个必须在正式号上线前就写好、测试通过、随时能切。**

### 为什么不是"远期"

| 场景 | 后果 |
|------|------|
| 微信封号 | 如果没有兜底 → 所有患者加不到你 → 业务中断 |
| 有兜底 | 30 分钟内切到企业微信 → 业务继续 |

### 企业微信方案概要

```
患者关注企业微信 → 发消息 → 企业微信 API 回调
  → 你的服务器 /api/v1/bot/wecom-webhook
  → 调同一个 FAQ API
  → 通过企业微信 API 发回复
```

**核心优势**：官方 API，零封号风险。  
**唯一劣势**：患者要加企业微信而不是个人微信。

### 准备步骤

- [ ] 注册企业微信（如果还没有）
- [ ] 创建一个"患者咨询"应用
- [ ] 拿到 CorpID、AgentID、Secret
- [ ] 写一个 `/api/v1/bot/wecom-webhook` 端点（逻辑跟个人微信版完全一样）
- [ ] 测试通过
- [ ] 写好《封号切换 SOP》文档

### 切换 SOP（目标 < 30 分钟）

```
1. [0 min] 发现封号 → 确认不是误判
2. [2 min] 在所有对外渠道更新为企业微信二维码（官网、推广页、其他渠道）
3. [5 min] 启动企业微信 Bot（如果还没启动的话）
4. [5-30 min] 通知已有患者通过其他方式（短信/公众号推送）加企业微信
5. [持续] 评估是否需要新微信号或切换为长期企业微信方案
```

---

## 十、技术选型总结

| 方案 | 适用场景 | 封号风险 | 代码状态 | 推荐度 |
|------|----------|----------|----------|--------|
| **C: OpenClaw Webhook** | 逻辑集中在服务器（首选） | 低 | **✅ 已实装** | ★★★★★ |
| **A: OpenClaw Skill** | 逻辑在 Windows 本地 | 低 | 模板已提供 | ★★★★☆ |
| **B: WechatFerry** | OpenClaw 不可用时退路 | **高** | 脚本已提供 | ★★☆☆☆ |
| **企业微信 API** | 兜底方案 / 长期稳定 | **零** | 待开发 | 并行准备 |

**推荐路线**：

```
第 1 周：
  ├ 服务器：重启后端（bot_webhook.py 已就绪）+ 配置 bot_webhook_secret
  ├ Windows：复制 faq-webhook Skill → 热加载 → curl 测通 Webhook
  ├ Windows：修复 OpenClaw Embedding（~/.openclaw/config.json 加 Dashscope）
  └ 测试号：真实微信收发验证

第 2 周：
  ├ 企业微信兜底脚本开发 + 切换 SOP
  └ 测试号持续观察封号情况

第 3 周：
  ├ 确认安全后切正式号
  └ 部署 Watchdog 守护进程
  
持续：每周审查 Bot 回复记录，调整知识库和敏感词
```

---

## 十一、你需要准备什么

| 序号 | 事项 | 状态 |
|------|------|------|
| 1 | Windows 电脑（已安装 OpenClaw 2026.3.13） | ✅ 已有 |
| 2 | OpenClaw Skill 目录确认 | ✅ 已确认 `~/.openclaw/skills/` |
| 3 | 修复 OpenClaw Embedding | ⬜ 改 config.json 加 Dashscope（5 分钟） |
| 4 | 服务器 Webhook 端点 | ✅ 代码已就绪 `bot_webhook.py` |
| 5 | 系统设置配 `bot_webhook_secret` | ⬜ 配完重启后端 |
| 6 | 复制 faq-webhook Skill 到 Windows | ⬜ 待操作 |
| 7 | 测试微信号 | ⬜ 待准备 |
| 8 | Windows 能访问 192.168.9.139 | ⬜ 待确认 |
| 9 | FAQ 知识库已训练好 | ⬜ 待确认 |
| 10 | 注册企业微信（兜底方案） | ⬜ 待准备 |

---

## 附录 A：Watchdog 守护脚本（Windows）

保存为 `watchdog.py`，用 Windows 任务计划程序每分钟运行：

```python
"""Windows Watchdog：每 60 秒自检微信 + OpenClaw + 网络"""

import subprocess
import sys
import time
import requests
from datetime import datetime


FAQ_API_HEALTH = "http://192.168.9.139/api/v1/health"
ALERT_WEBHOOK = ""  # 飞书/钉钉 webhook URL（留空则只打印日志）
LOG_FILE = "watchdog.log"


def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def alert(msg: str):
    log(f"ALERT: {msg}")
    if ALERT_WEBHOOK:
        try:
            requests.post(ALERT_WEBHOOK, json={"msg_type": "text", "content": {"text": f"[Bot Watchdog] {msg}"}}, timeout=5)
        except Exception:
            pass


def check_process(name: str) -> bool:
    try:
        result = subprocess.run(["tasklist"], capture_output=True, text=True, timeout=10)
        return name.lower() in result.stdout.lower()
    except Exception:
        return False


def check_api() -> bool:
    try:
        r = requests.get(FAQ_API_HEALTH, timeout=5)
        return r.status_code == 200
    except Exception:
        return False


def main():
    issues = []

    if not check_process("WeChat.exe"):
        issues.append("WeChat.exe not running")

    if not check_process("openclaw"):
        issues.append("OpenClaw not running")

    if not check_api():
        issues.append(f"FAQ API unreachable: {FAQ_API_HEALTH}")

    if issues:
        alert(" | ".join(issues))
    else:
        log("OK - all checks passed")


if __name__ == "__main__":
    main()
```

---

## 附录 B：完整文件清单

```
你的服务器 192.168.9.139（已实装）：
  backend/app/api/bot_webhook.py     # ✅ Webhook 端点（合规+FAQ+真人模拟）
  backend/app/main.py                # ✅ 已注册 bot_webhook router

你的 Windows 机器上（复制过去即可）：
  ~/.openclaw/skills/faq-webhook/
    ├── manifest.json                # ✅ Skill 配置（改 bot_secret 即可）
    ├── index.js                     # ✅ 转发逻辑（零业务代码）
    └── README.md                    # 使用说明
  watchdog.py                        # 守护进程（附录 A）

方案 A 备选（如果走 Skill 模式而非 Webhook）：
  ~/.openclaw/skills/faq-reply/
    ├── manifest.json
    ├── __init__.py                  # 完整业务逻辑
    ├── faq_client.py                # FAQ API 调用
    ├── compliance.py                # 合规拦截
    ├── humanizer.py                 # 模拟真人
    └── config.yaml                  # 敏感词/免责前缀（热更新）

项目仓库中的模板目录：
  chattrainer/openclaw-skill-faq-webhook/   # 复制到 Windows

文档：
  chattrainer/微信自动回复集成方案-QClaw技术可行性分析.md  # 本文件
```
