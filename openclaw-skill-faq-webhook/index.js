/**
 * OpenClaw Skill: faq-webhook
 *
 * 极简转发：收到微信消息 → POST 到 ChatTrainer Webhook → 拿到回复 → 返回给 OpenClaw 发送。
 * 所有业务逻辑（合规拦截、FAQ 检索、真人模拟）都在服务器端完成。
 * Windows 端零业务代码。
 */

const MANIFEST = require("./manifest.json");
const crypto = require("crypto");
const cfg = MANIFEST.config || {};

const WEBHOOK_URL = cfg.webhook_url || "http://192.168.9.139/api/v1/bot/wechat-faq";
const BOT_SECRET  = cfg.bot_secret  || "";
const HEALTH_URL  = cfg.health_url  || "http://192.168.9.139/api/v1/bot/health";
const RETRY_TIMES = Number(cfg.retry_times || 2);
const FEEDBACK_URL = cfg.feedback_url || `${WEBHOOK_URL.replace(/\/$/, "")}/feedback`;
const MODE_RISK_KEYWORDS = Array.isArray(cfg.mode_risk_keywords)
  ? cfg.mode_risk_keywords
  : ["费用", "价格", "医保", "报销", "疗程", "手术", "住院"];

module.exports = {
  name: MANIFEST.name,
  description: MANIFEST.description,
  version: MANIFEST.version,

  actions: {
    /**
     * 处理收到的微信消息。
     * OpenClaw 会在收到私聊文本消息时自动调用此 action。
     */
    handleMessage: {
      description: "收到微信消息后转发到 ChatTrainer Webhook 获取 AI 回复",
      parameters: {
        sender:   { type: "string", required: true,  description: "发送者 wxid" },
        content:  { type: "string", required: true,  description: "消息文本" },
        is_group: { type: "boolean", required: false, description: "是否群消息" },
        room_id:  { type: "string", required: false, description: "群 ID" },
        msg_type: { type: "string", required: false, description: "消息类型" },
        quality_mode: { type: "string", required: false, description: "auto|fast|balanced|quality，可显式覆盖自动推断" },
      },

      async execute({ sender, content, is_group, room_id, msg_type, quality_mode }) {
        const resolvedMode = resolveQualityMode({
          content: content || "",
          msgType: msg_type || "text",
          explicitMode: quality_mode || "",
        });
        const requestId = createId("req");
        const traceId = createId("trace");
        const senderSafe = sender || "";
        const messageId = createId("wxmsg");
        const sessionId = `wechat:${senderSafe || "unknown"}`;

        for (let i = 0; i <= RETRY_TIMES; i++) {
          try {
          const ts = Math.floor(Date.now() / 1000);
          const nonce = randomNonce();
          const bodyObj = {
            sender: senderSafe,
            content: content || "",
            is_group: is_group || false,
            room_id: room_id || "",
            msg_type: msg_type || "text",
            quality_mode: resolvedMode,
            ts,
            message_id: messageId,
            session_id: sessionId,
            platform: "wechat",
            receiver: "openclaw-main",
            request_id: requestId,
            trace_id: traceId,
            retry_count: i,
            client_ts: ts,
            version: "faq-webhook.v1",
            nonce,
          };
          const body = JSON.stringify(bodyObj);
          const signature = signPayload(BOT_SECRET, body);
          const resp = await fetch(WEBHOOK_URL, {
            method: "POST",
            headers: {
              "Content-Type":  "application/json",
              "X-Hub-Signature-256": `sha256=${signature}`,
              "X-Request-Id": requestId,
              "X-Timestamp": String(ts),
              "X-Nonce": nonce,
              "X-OpenClaw-Version": "2026.3.13",
              "X-Client": "openclaw-faq-webhook",
            },
            body,
            signal: AbortSignal.timeout(15000),
          });

          if (!resp.ok) {
            const errText = await resp.text().catch(() => "");
            if (i >= RETRY_TIMES) {
              console.error(`[faq-webhook] Server ${resp.status}: ${errText.slice(0, 200)}`);
              return null;
            }
            await sleep((i + 1) * 500);
            continue;
          }

          const data = await resp.json();
          // Standardized response: code/message/action/reply/quality_*...
          if (data.action === "skip") {
            return null;
          }
          if (Number(data.code || 0) !== 0 && data.action !== "transfer") {
            if (i >= RETRY_TIMES) {
              console.error(`[faq-webhook] Non-zero code: ${data.code} ${data.message || ""}`);
              return null;
            }
            await sleep((i + 1) * 500);
            continue;
          }

          if (typeof data.delay_sec === "number" && data.delay_sec > 0) {
              await sleep(data.delay_sec * 1000);
          }
          if (typeof data.reply === "string" && data.reply.trim()) {
            return {
              reply: data.reply,
              panel_id: data.panel_id || null,
              candidates: Array.isArray(data.candidates) ? data.candidates.slice(0, 3) : [],
              confidence: data.confidence,
              quality_mode_requested: data.quality_mode_requested || resolvedMode,
              quality_mode_effective: data.quality_mode_effective,
              quality_route_reason: data.quality_route_reason,
              request_id: data.request_id || requestId,
              trace_id: data.trace_id || traceId,
            };
          }
          return null;
          } catch (err) {
            if (i >= RETRY_TIMES) {
              console.error(`[faq-webhook] Request failed: ${err.message}`);
              return null;
            }
            await sleep((i + 1) * 500);
          }
        }
        return null;
      },
    },

    /**
     * 健康检查（Watchdog 可调用）
     */
    healthCheck: {
      description: "检查 ChatTrainer 服务器是否可达",
      parameters: {},
      async execute() {
        try {
          const resp = await fetch(HEALTH_URL, {
            signal: AbortSignal.timeout(5000),
          });
          const data = await resp.json();
          return { status: "ok", server: data };
        } catch (err) {
          return { status: "error", error: err.message };
        }
      },
    },

    submitFeedback: {
      description: "将微信侧采纳/改写/拒绝反馈回传到 ChatTrainer",
      parameters: {
        panel_id: { type: "number", required: true, description: "copilot panel_id" },
        action: { type: "string", required: true, description: "accepted|edited|rejected" },
        candidate_index: { type: "number", required: false, description: "候选索引(0-2)" },
        final_reply: { type: "string", required: false, description: "改写后的最终回复" },
        conversation_id: { type: "string", required: false, description: "会话ID" },
        first_response_ms: { type: "number", required: false, description: "首响耗时ms" },
        session_duration_ms: { type: "number", required: false, description: "会话总耗时ms" },
        message_count: { type: "number", required: false, description: "会话消息条数" },
        request_id: { type: "string", required: false, description: "请求ID（链路追踪）" },
        trace_id: { type: "string", required: false, description: "追踪ID（跨系统）" },
        sender: { type: "string", required: false, description: "发送者wxid" },
        message_id: { type: "string", required: false, description: "微信消息唯一ID" },
        session_id: { type: "string", required: false, description: "会话ID" },
        delivery_status: { type: "string", required: false, description: "sent|failed|dropped" },
        user_feedback: { type: "string", required: false, description: "up|down|neutral" },
      },
      async execute({
        panel_id,
        action,
        candidate_index,
        final_reply,
        conversation_id,
        first_response_ms,
        session_duration_ms,
        message_count,
        request_id,
        trace_id,
        sender,
        message_id,
        session_id,
        delivery_status,
        user_feedback,
      }) {
        const nowTs = Math.floor(Date.now() / 1000);
        const reqId = request_id || createId("req");
        const trId = trace_id || createId("trace");
        const nonce = randomNonce();
        const bodyObj = {
          request_id: reqId,
          trace_id: trId,
          message_id: message_id || "",
          session_id: session_id || "",
          sender: sender || "",
          panel_id: Number(panel_id || 0),
          action: String(action || "").trim().toLowerCase(),
          delivery_status: delivery_status || "sent",
          user_feedback: user_feedback || "",
          candidate_index: Number(candidate_index || 0),
          final_reply: final_reply || "",
          conversation_id: conversation_id || "",
          first_response_ms: Number(first_response_ms || 0),
          session_duration_ms: Number(session_duration_ms || 0),
          message_count: Number(message_count || 0),
          channel: "wechat",
          feedback_ts: nowTs,
          ts: nowTs,
          version: "faq-webhook.v1",
          nonce,
        };
        const body = JSON.stringify(bodyObj);
        const signature = signPayload(BOT_SECRET, body);
        const resp = await fetch(FEEDBACK_URL, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-Hub-Signature-256": `sha256=${signature}`,
            "X-Request-Id": reqId,
            "X-Timestamp": String(nowTs),
            "X-Nonce": nonce,
            "X-OpenClaw-Version": "2026.3.13",
            "X-Client": "openclaw-faq-webhook",
          },
          body,
          signal: AbortSignal.timeout(10000),
        });
        if (!resp.ok) {
          const errText = await resp.text().catch(() => "");
          throw new Error(`feedback failed ${resp.status}: ${errText.slice(0, 200)}`);
        }
        return await resp.json();
      },
    },
  },
};

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function signPayload(secret, payload) {
  return crypto.createHmac("sha256", secret).update(payload).digest("hex");
}

function createId(prefix) {
  if (typeof crypto.randomUUID === "function") return `${prefix}-${crypto.randomUUID()}`;
  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2, 10)}`;
}

function randomNonce() {
  return crypto.randomBytes(8).toString("hex");
}

function resolveQualityMode({ content, msgType, explicitMode }) {
  const mode = String(explicitMode || "").trim().toLowerCase();
  if (["auto", "fast", "balanced", "quality"].includes(mode)) return mode;
  const typeNorm = String(msgType || "text").trim().toLowerCase();
  if (["voice", "audio", "image", "file"].includes(typeNorm)) return "quality";
  const text = String(content || "").trim();
  if (!text) return "auto";
  if (text.length <= 4) return "fast";
  if (MODE_RISK_KEYWORDS.some((kw) => text.includes(String(kw)))) return "quality";
  return "balanced";
}
