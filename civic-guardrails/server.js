import { createHttpPassthroughProxy, AbstractHook } from "@civic/passthrough-mcp-server";
import fs from "fs";

const UPSTREAM_URL = process.env.UPSTREAM_MCP_URL || "http://jobs-mcp:8001/mcp";
const AUDIT_LOG    = process.env.AUDIT_LOG_PATH    || "/logs/audit.jsonl";
const PORT         = parseInt(process.env.PORT      || "8002");

// ── Audit log helper ─────────────────────────────────────────────────────────

function writeAudit(entry) {
  try {
    fs.appendFileSync(AUDIT_LOG, JSON.stringify({ ...entry, ts: new Date().toISOString() }) + "\n");
  } catch (e) {
    console.error("[audit] write failed:", e.message);
  }
}

// ── Prompt injection patterns ────────────────────────────────────────────────

const INJECTION_PATTERNS = [
  /ignore\s+(previous|all|prior)\s+instructions/i,
  /system\s*prompt/i,
  /\bDAN\b/,
  /<\s*\/?script/i,
  /\bexec\s*\(/i,
  /\beval\s*\(/i,
  /\bdrop\s+table\b/i,
  /[<>]{2,}/,
];

const PII_PATTERNS = [
  [/[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}/g, "[email]"],
  [/(\+?44[\s\-]?|0)[1-9][\d\s\-]{7,12}/g, "[phone]"],
  [/\+\d{1,3}[\s\-]?\d{6,14}/g, "[phone]"],
];

// ── Hook 1: Rate limiter ─────────────────────────────────────────────────────

class RateLimitHook extends AbstractHook {
  get name() { return "windrush-rate-limit"; }

  constructor(maxRequests = 30, windowMs = 60_000) {
    super();
    this._max = maxRequests;
    this._window = windowMs;
    this._counts = new Map(); // key → { count, resetAt }
    // Evict expired entries every minute to prevent unbounded growth
    setInterval(() => {
      const now = Date.now();
      for (const [k, v] of this._counts) if (now > v.resetAt) this._counts.delete(k);
    }, 60_000);
  }

  async processCallToolRequest(request, requestExtra) {
    const key = requestExtra?.sessionId ?? "default";
    const now = Date.now();
    let entry = this._counts.get(key);
    if (!entry || now > entry.resetAt) {
      entry = { count: 0, resetAt: now + this._window };
      this._counts.set(key, entry);
    }
    entry.count++;
    if (entry.count > this._max) {
      writeAudit({ hook: this.name, fired: true, reason: "rate limit exceeded", session: key });
      console.warn(`[GUARDRAIL] Rate limit hit for session ${key}`);
      return {
        resultType: "respond",
        response: {
          content: [{ type: "text", text: "Rate limit exceeded — too many job searches. Please wait a moment." }],
          isError: true,
        },
      };
    }
    return { resultType: "continue", request };
  }
}

// ── Hook 2: Search query injection guardrail ─────────────────────────────────

class SearchGuardrailHook extends AbstractHook {
  get name() { return "windrush-search-guardrail"; }

  async processCallToolRequest(request, requestExtra) {
    if (request.params?.name !== "search_jobs") {
      return { resultType: "continue", request };
    }

    const query = request.params?.arguments?.query ?? "";
    for (const pattern of INJECTION_PATTERNS) {
      if (pattern.test(query)) {
        writeAudit({
          hook: this.name,
          fired: true,
          reason: `Injection pattern matched: ${pattern}`,
          query: query.slice(0, 80),
        });
        console.warn(`[GUARDRAIL] Blocked injection in search query: ${query.slice(0, 80)}`);
        return {
          resultType: "respond",
          response: {
            content: [{ type: "text", text: "GUARDRAIL_BLOCK: Suspicious search query was rejected." }],
            isError: true,
          },
        };
      }
    }

    writeAudit({ hook: this.name, fired: false, tool: "search_jobs", query: query.slice(0, 80) });
    return { resultType: "continue", request };
  }
}

// ── Hook 3: PII scrub on job description responses ───────────────────────────

class PiiScrubHook extends AbstractHook {
  get name() { return "windrush-pii-scrub"; }

  async processCallToolResult(response, originalRequest, requestExtra) {
    if (originalRequest?.params?.name !== "search_jobs") {
      return { resultType: "continue", response };
    }

    let text = JSON.stringify(response);
    const original = text;
    for (const [pattern, replacement] of PII_PATTERNS) {
      text = text.replace(pattern, replacement);
    }

    if (text !== original) {
      writeAudit({ hook: this.name, fired: true, detail: "PII removed from job search response" });
      console.info("[GUARDRAIL] PII redacted from job response");
      return { resultType: "continue", response: JSON.parse(text) };
    }

    return { resultType: "continue", response };
  }
}

// ── Hook 4: Audit log ────────────────────────────────────────────────────────

class AuditHook extends AbstractHook {
  get name() { return "windrush-audit"; }

  async processCallToolRequest(request, requestExtra) {
    writeAudit({
      hook: this.name,
      event: "request",
      tool: request.params?.name,
      args: JSON.stringify(request.params?.arguments ?? {}).slice(0, 200),
      session: requestExtra?.sessionId,
    });
    return { resultType: "continue", request };
  }

  async processCallToolResult(response, originalRequest, requestExtra) {
    writeAudit({
      hook: this.name,
      event: "response",
      tool: originalRequest?.params?.name,
      isError: response.isError ?? false,
      session: requestExtra?.sessionId,
    });
    return { resultType: "continue", response };
  }
}

// ── Start proxy ───────────────────────────────────────────────────────────────

const [upstreamUrl, mcpPath] = (() => {
  const url = new URL(UPSTREAM_URL);
  const path = url.pathname || "/mcp";
  url.pathname = "";
  return [url.toString().replace(/\/$/, ""), path];
})();

const proxy = await createHttpPassthroughProxy({
  port: PORT,
  mcpPath: "/mcp",
  target: {
    transportType: "httpStream",
    url: upstreamUrl,
    mcpPath: mcpPath,
  },
  hooks: [
    new RateLimitHook(30, 60_000),
    new SearchGuardrailHook(),
    new PiiScrubHook(),
    new AuditHook(),
  ],
});

console.log(`[civic-guardrails] Proxy running on :${PORT}/mcp → ${UPSTREAM_URL}`);
console.log(`[civic-guardrails] Audit log: ${AUDIT_LOG}`);
