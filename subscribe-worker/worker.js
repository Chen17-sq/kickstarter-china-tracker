/**
 * Kickstarter China Tracker — subscribe Worker (KV edition)
 *
 * Endpoints:
 *   POST /                 — append a subscriber (used by site/subscribe.html form)
 *   GET  /list             — read full subscriber list (X-Owner-Token auth)
 *   GET  /count            — public-safe count (no emails)
 *   GET  /health           — public uptime probe + feature-flags status
 *   POST /unsubscribe      — remove a subscriber by email (X-Owner-Token auth)
 *   POST /webhook/resend   — Resend bounce/complaint webhook (Svix-signed; auto-removes bad emails)
 *
 * Subscribers are stored in Cloudflare KV (private, never leaves CF).
 * Older versions of this Worker wrote to data/subscribers.json on the
 * public GitHub repo — that file leaked email addresses to anyone who
 * could clone the repo. KV namespace is the privacy fix.
 *
 * Required Worker bindings / vars:
 *   SUBSCRIBERS_KV         — KV namespace bound as "SUBSCRIBERS_KV" in dashboard
 *   OWNER_TOKEN            — random secret. /list and /unsubscribe require
 *                            header "X-Owner-Token: <OWNER_TOKEN>". Anything
 *                            else gets 403.
 *   ALLOWED_ORIGIN         — comma-separated whitelist of allowed Origins for CORS.
 *                            '*' falls back to allow-all (debug only).
 *   RESEND_WEBHOOK_SECRET  — (optional) Svix signing secret (starts with "whsec_")
 *                            from Resend dashboard. When set, /webhook/resend
 *                            verifies the signature and auto-removes bounced/
 *                            complained emails from KV. Without it, the endpoint
 *                            returns 403 so misconfigured webhooks don't silently
 *                            drop subscribers.
 *   RESEND_API_KEY         — (optional) Resend API key. Used by POST / to send
 *                            a welcome email immediately after a successful
 *                            subscribe. Without it, subscribers still land in
 *                            KV but get no immediate confirmation (they'll see
 *                            the first edition tomorrow morning).
 *   NOTIFY_EMAIL_FROM      — (optional, paired with RESEND_API_KEY) sender used
 *                            for welcome emails. Should match the verified
 *                            sender in Resend, e.g. "KS Tracker <hi@aldrich.fyi>".
 *
 * Abuse protection:
 *   POST / is rate-limited to 5 attempts/minute per IP, tracked via KV
 *   bucket keys with 2-minute TTL. Casual flood scripts get 429.
 *
 * Subscribe-write payload (POST /):
 *   { email: "...", nickname: "..." }
 *
 * Owner-read response (GET /list):
 *   { count: N, subscribers: [{email, nickname, added_at, source}, ...] }
 *
 * Resend webhook setup (one-time, in Resend dashboard → Webhooks → Add):
 *   URL:     https://ks-tracker-subscribe.<account>.workers.dev/webhook/resend
 *   Events:  email.bounced, email.complained
 *   Secret:  copy the "whsec_..." secret → `wrangler secret put RESEND_WEBHOOK_SECRET`
 */

const KV_KEY = "subscribers";  // single key holds the full list (small enough)

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const cors = corsHeaders(request.headers.get("Origin"), env.ALLOWED_ORIGIN);

    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: cors });
    }

    // ── GET /count — public, returns just a number ─────────────────
    if (request.method === "GET" && url.pathname === "/count") {
      const data = await readList(env);
      return json({ count: data.subscribers.length }, 200, cors);
    }

    // ── GET /health — uptime probe + minimal config diagnostic ─────
    // Returns 200 if KV is reachable, 503 otherwise. Body always includes
    // which optional features are wired up (welcome email, bounce
    // webhook). Safe to expose publicly — no secret values are returned,
    // only "configured / not configured" booleans for each env var.
    if (request.method === "GET" && url.pathname === "/health") {
      let kvOk = false;
      try {
        if (env.SUBSCRIBERS_KV) {
          // Cheap roundtrip — read a key that may or may not exist.
          await env.SUBSCRIBERS_KV.get("__health__");
          kvOk = true;
        }
      } catch (_e) {
        kvOk = false;
      }
      return json(
        {
          ok: kvOk,
          ts: new Date().toISOString(),
          features: {
            kv: kvOk,
            welcome_email: !!(env.RESEND_API_KEY && env.NOTIFY_EMAIL_FROM),
            bounce_webhook: !!env.RESEND_WEBHOOK_SECRET,
            cors_allowlist_configured: !!env.ALLOWED_ORIGIN && env.ALLOWED_ORIGIN !== "*",
          },
        },
        kvOk ? 200 : 503,
        cors,
      );
    }

    // ── GET /list — owner-only, returns full list ──────────────────
    if (request.method === "GET" && url.pathname === "/list") {
      if (!authorized(request, env)) {
        return json({ ok: false, error: "forbidden" }, 403, cors);
      }
      const data = await readList(env);
      return json(data, 200, cors);
    }

    // ── POST /unsubscribe — owner-only ─────────────────────────────
    if (request.method === "POST" && url.pathname === "/unsubscribe") {
      if (!authorized(request, env)) {
        return json({ ok: false, error: "forbidden" }, 403, cors);
      }
      let email = "";
      try {
        const body = await request.json();
        email = (body.email || "").trim();
      } catch (_e) {
        return json({ ok: false, error: "bad payload" }, 400, cors);
      }
      if (!email) return json({ ok: false, error: "email required" }, 400, cors);
      const r = await removeSubscriber(env, email);
      // Flat response shape — keeps the Python client (subscribers.py)
      // simple instead of needing nested-dict parsing.
      return json({ ok: true, removed: r.removed, count: r.count }, 200, cors);
    }

    // ── POST / — subscribe form submission ─────────────────────────
    if (request.method === "POST" && (url.pathname === "/" || url.pathname === "")) {
      // Rate-limit by client IP: max 5 subscribe attempts / minute.
      // Without this, a bot can flood KV with fake addresses; the form
      // has no CAPTCHA and KV writes are cheap to abuse. Bucket is
      // per-IP-per-minute with a 2-minute TTL so transient spikes
      // don't get permanently locked out.
      const rlAllowed = await rateLimitOk(request, env, "subscribe", 5, 60);
      if (!rlAllowed) {
        return json({ ok: false, error: "rate limited" }, 429, cors);
      }
      return handleSubscribe(request, env, cors);
    }

    // ── POST /webhook/resend — Resend bounce/complaint webhook ─────
    // No CORS (server-to-server only). No X-Owner-Token (Resend doesn't
    // know it). Auth is Svix HMAC signature verification with the
    // RESEND_WEBHOOK_SECRET shared secret.
    if (request.method === "POST" && url.pathname === "/webhook/resend") {
      return handleResendWebhook(request, env);
    }

    return json({ ok: false, error: "not found" }, 404, cors);
  },
};

async function handleSubscribe(request, env, cors) {
  let email = "";
  let nickname = "";
  let creatorUrl = "";  // optional, for creator-type subscribers
  try {
    const ct = request.headers.get("content-type") || "";
    if (ct.includes("application/json")) {
      const body = await request.json();
      email = (body.email || "").trim();
      nickname = (body.nickname || "").trim();
      creatorUrl = (body.creator_url || "").trim();
    } else {
      const form = await request.formData();
      email = (form.get("email") || "").trim();
      nickname = (form.get("nickname") || "").trim();
      creatorUrl = (form.get("creator_url") || "").trim();
    }
  } catch (_e) {
    return json({ ok: false, error: "bad payload" }, 400, cors);
  }

  if (!isValidEmail(email)) {
    return json({ ok: false, error: "invalid email" }, 400, cors);
  }
  nickname = sanitizeNick(nickname);
  if (nickname.length > 60) nickname = nickname.slice(0, 60);

  // Extract creator slug from a KS profile URL.
  // Strict acceptance — reject anything that doesn't look like a real KS URL,
  // so attackers can't sneak in slugs by encoding any URL like
  // 'https://evil.com/profile/realuser'.
  // Accepted forms:
  //   https://www.kickstarter.com/profile/<slug>
  //   http://kickstarter.com/profile/<slug>     (and www variant)
  //   <slug>                                   (bare slug, alphanumeric+_-)
  let creatorSlug = "";
  if (creatorUrl) {
    const KS_URL_RE = /^https?:\/\/(?:www\.)?kickstarter\.com\/profile\/([A-Za-z0-9_-]{1,60})\/?$/i;
    const m = creatorUrl.match(KS_URL_RE);
    if (m) {
      creatorSlug = m[1];
    } else if (/^[A-Za-z0-9_-]{1,60}$/.test(creatorUrl)) {
      // Bare slug typed in directly — accept
      creatorSlug = creatorUrl;
    }
    // Else: ignore (bad URL won't get any slug stored)
  }

  if (!env.SUBSCRIBERS_KV) {
    return json({ ok: false, error: "worker not configured (SUBSCRIBERS_KV not bound)" }, 500, cors);
  }

  try {
    const result = await appendSubscriber(env, email, nickname, creatorSlug);
    if (result.duplicate) {
      return json({ ok: true, duplicate: true, message: "already subscribed" }, 200, cors);
    }
    // Fire-and-forget welcome email. We don't await its completion —
    // if Resend is degraded, the subscribe flow still returns success
    // quickly. Subscriber will get the daily edition tomorrow either way.
    if (env.RESEND_API_KEY && env.NOTIFY_EMAIL_FROM) {
      sendWelcomeEmail(env, email, nickname, !!creatorSlug).catch(() => {});
    }
    return json({
      ok: true,
      count: result.count,
      type: result.type,
    }, 200, cors);
  } catch (e) {
    return json({ ok: false, error: String(e.message || e) }, 500, cors);
  }
}

// ── Rate limiting ───────────────────────────────────────────────────
//
// Per-IP, per-minute bucket counter stored in KV. NOT atomic — there's
// a race between read and write — but for human-rate abuse the slop
// is fine (5 vs 7 attempts in a minute doesn't matter). For real DDoS,
// Cloudflare's free-tier WAF rules would catch it first; this is
// belt-and-suspenders against casual flood scripts.
//
// `tag` lets different endpoints share the rate limit subsystem without
// stepping on each other (e.g. "subscribe" vs "unsubscribe" buckets).
async function rateLimitOk(request, env, tag, limit, windowSec) {
  if (!env.SUBSCRIBERS_KV) return true;  // can't enforce → fail open
  const ip = request.headers.get("CF-Connecting-IP") || "unknown";
  const bucket = Math.floor(Date.now() / 1000 / windowSec);
  const key = `rl:${tag}:${ip}:${bucket}`;
  let count = 0;
  try {
    const raw = await env.SUBSCRIBERS_KV.get(key);
    count = parseInt(raw || "0", 10);
  } catch (_e) {
    // KV read error → fail open. Better to accept legit traffic during
    // a partial KV outage than to lock everyone out.
    return true;
  }
  if (count >= limit) return false;
  try {
    await env.SUBSCRIBERS_KV.put(key, String(count + 1), { expirationTtl: windowSec * 2 });
  } catch (_e) {
    // Ignore — counter stays a bit stale but the request still proceeds
  }
  return true;
}

// ── Welcome email ───────────────────────────────────────────────────
//
// Sent immediately on first successful subscribe. Subscriber gets a
// confirmation + link to the latest edition so they have something to
// read RIGHT NOW; otherwise they'd wait until tomorrow's cron for the
// first real edition, which feels like the form silently swallowed
// their email.
async function sendWelcomeEmail(env, email, nickname, isCreator) {
  const display = nickname && nickname.length ? nickname : email.split("@")[0];
  const subject = "✦ 订阅成功 · Welcome to Kickstarter China Tracker";
  const creatorLine = isCreator
    ? `<p style="margin:0 0 12px;font-family:Lora,Georgia,serif;font-size:15px;line-height:1.55">
         你勾选了"我是 KS Creator" — 每当你的项目出现在追踪列表里，邮件顶部会显示一个针对你的小横幅。</p>`
    : "";
  const html = `<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>${subject}</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>@import url('https://fonts.googleapis.com/css2?family=Lora:ital,wght@0,400;1,400&family=Playfair+Display:wght@700;900&family=Inter:wght@500;700&display=swap');</style>
</head>
<body style="margin:0;padding:24px 12px;background:#F9F9F7;font-family:Lora,Georgia,serif;color:#111">
  <div style="display:none;max-height:0;overflow:hidden;color:transparent;font-size:1px;opacity:0">
    Welcome ${display} — your first edition arrives tomorrow morning at 08:00 Beijing.
  </div>
  <table role="presentation" cellspacing="0" cellpadding="0" border="0"
         style="max-width:600px;margin:0 auto;background:#F9F9F7;
                border:1px solid #111;border-collapse:collapse">
    <tr><td style="padding:0">
      <div style="background:#111;color:#F9F9F7;padding:10px 24px;
                  font-family:Inter,system-ui,sans-serif;font-size:10px;
                  font-weight:700;letter-spacing:2.5px">
        <span style="display:inline-block;width:6px;height:6px;background:#CC0000;border-radius:50%;margin-right:8px;vertical-align:1px"></span>
        SUBSCRIBED · KICKSTARTER CHINA TRACKER
      </div>
      <div style="padding:28px 28px 16px">
        <h1 style="margin:0 0 8px;font-family:'Playfair Display',Georgia,serif;
                   font-weight:900;font-size:34px;line-height:1.05;letter-spacing:-.5px">
          ${display}，欢迎上船。
        </h1>
        <p style="margin:0 0 16px;font-family:Inter,system-ui,sans-serif;font-size:12px;font-weight:700;letter-spacing:.18em;text-transform:uppercase;color:#737373">
          DAILY · 08:00 BEIJING · STARTING TOMORROW
        </p>
        <p style="margin:0 0 12px;font-size:16px;line-height:1.6">
          每天早上你会收到一份 Kickstarter 上中国背景消费硬件项目的追踪报。
          Top 10 prelaunch / Top 10 live / Sleeper Picks，配 KPI 一行流和编辑挑选。
        </p>
        ${creatorLine}
        <p style="margin:0 0 24px;font-size:16px;line-height:1.6">
          想先睹为快？这里是最近一期的视觉版：
        </p>
        <p style="margin:0 0 24px">
          <a href="https://ks.aldrich.fyi/editions/latest.html"
             style="display:inline-block;padding:12px 24px;
                    background:#CC0000;color:#F9F9F7;text-decoration:none;
                    font-family:Inter,system-ui,sans-serif;font-size:13px;
                    font-weight:700;letter-spacing:.18em;text-transform:uppercase">
            阅读最新一期 →
          </a>
        </p>
        <p style="margin:0;font-size:13px;color:#737373;line-height:1.5">
          也可以走 RSS 阅读器：<a href="https://ks.aldrich.fyi/feed.xml" style="color:#737373">ks.aldrich.fyi/feed.xml</a><br>
          想停订？回这封邮件说一声"取消订阅"即可。
        </p>
      </div>
      <div style="background:#111;color:#F9F9F7;padding:14px 24px;
                  font-family:Inter,system-ui,sans-serif;font-size:10px;
                  letter-spacing:2px;text-align:center">
        ✦ &nbsp; ALL THE CROWD-FUNDED HARDWARE FIT TO PRINT &nbsp; ✦
      </div>
    </td></tr>
  </table>
</body>
</html>`;
  // POST to Resend
  const r = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${env.RESEND_API_KEY}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      from: env.NOTIFY_EMAIL_FROM,
      to: [email],
      subject,
      html,
    }),
  });
  if (!r.ok) {
    // Log to Worker console — Cloudflare keeps tail logs for a while.
    // Not fatal; subscriber still got their KV entry.
    const errText = await r.text().catch(() => "");
    console.log(`welcome email to ${email} returned ${r.status}: ${errText.slice(0, 200)}`);
  }
}

// ── KV-backed subscriber storage ───────────────────────────────────

async function readList(env) {
  if (!env.SUBSCRIBERS_KV) return { count: 0, subscribers: [] };
  const raw = await env.SUBSCRIBERS_KV.get(KV_KEY);
  if (!raw) return { count: 0, subscribers: [] };
  try {
    const data = JSON.parse(raw);
    data.subscribers = data.subscribers || [];
    data.count = data.subscribers.length;
    return data;
  } catch (_e) {
    return { count: 0, subscribers: [] };
  }
}

async function writeList(env, data) {
  data.count = data.subscribers.length;
  await env.SUBSCRIBERS_KV.put(KV_KEY, JSON.stringify(data));
}

async function appendSubscriber(env, email, nickname, creatorSlug) {
  const data = await readList(env);
  // Case-insensitive dedup
  const exists = data.subscribers.some(
    (s) => (s.email || "").toLowerCase() === email.toLowerCase(),
  );
  if (exists) {
    return { duplicate: true, count: data.subscribers.length };
  }
  const isCreator = !!creatorSlug;
  data.subscribers.push({
    email,
    nickname: nickname || email.split("@")[0],
    added_at: new Date().toISOString().slice(0, 10),
    source: "form",
    type: isCreator ? "creator" : "investor",
    ...(creatorSlug ? { creator_slug: creatorSlug } : {}),
  });
  await writeList(env, data);
  return {
    duplicate: false,
    count: data.subscribers.length,
    type: isCreator ? "creator" : "investor",
  };
}

async function removeSubscriber(env, email) {
  const data = await readList(env);
  const before = data.subscribers.length;
  data.subscribers = data.subscribers.filter(
    (s) => (s.email || "").toLowerCase() !== email.toLowerCase(),
  );
  const removed = before - data.subscribers.length;
  if (removed > 0) await writeList(env, data);
  return { removed, count: data.subscribers.length };
}

// ── Helpers ────────────────────────────────────────────────────────

// Constant-time string compare — never short-circuits on length mismatch,
// so attackers can't time-attack the length. We mix length difference
// into the diff and walk the longer string with character-XOR.
function authorized(request, env) {
  if (!env.OWNER_TOKEN) return false;
  const provided = request.headers.get("X-Owner-Token") || "";
  const expected = env.OWNER_TOKEN;
  let diff = provided.length ^ expected.length;
  const len = Math.max(provided.length, expected.length);
  for (let i = 0; i < len; i++) {
    const a = i < provided.length ? provided.charCodeAt(i) : 0;
    const b = i < expected.length ? expected.charCodeAt(i) : 0;
    diff |= a ^ b;
  }
  return diff === 0;
}

function isValidEmail(s) {
  return /^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$/.test(s) && s.length <= 254;
}

function sanitizeNick(s) {
  return s.replace(/[ -]/g, "").replace(/\s+/g, " ").trim();
}

function corsHeaders(requestOrigin, whitelistEnv) {
  const list = (whitelistEnv || "*").split(",").map((s) => s.trim()).filter(Boolean);
  let allow = list[0] || "*";
  if (list.includes("*")) {
    allow = "*";
  } else if (requestOrigin && list.includes(requestOrigin)) {
    allow = requestOrigin;
  }
  return {
    "Access-Control-Allow-Origin": allow,
    "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, X-Owner-Token",
    "Access-Control-Max-Age": "86400",
    "Vary": "Origin",
  };
}

function json(payload, status, extra) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", ...(extra || {}) },
  });
}

// ── Resend webhook (bounce / complaint auto-cleanup) ────────────────
//
// Resend POSTs here on email.bounced (hard bounces) and email.complained
// (spam reports). We verify the Svix signature, parse the event, and
// auto-remove the offending address from KV. Soft bounces are ignored —
// they're usually transient (full inbox, temp DNS issue) and the address
// is worth keeping.
//
// Svix signature format (what Resend sends):
//   svix-id:        unique message ID (string)
//   svix-timestamp: epoch seconds (string)
//   svix-signature: "v1,<base64-sig> v1,<base64-sig> ..." (space-separated
//                   if multiple secret versions are active)
//
// Verification: HMAC-SHA256 of `${id}.${timestamp}.${body}` using the
// signing secret (base64-decoded from `whsec_<...>`). Reject if no match,
// or if timestamp is more than 5 minutes old (replay protection).
async function handleResendWebhook(request, env) {
  if (!env.RESEND_WEBHOOK_SECRET) {
    // Safer to 403 than to silently accept — if Resend's webhook is hitting
    // a misconfigured Worker, we want loud failure (Resend's dashboard
    // will surface the 403) instead of silently dropping subscribers.
    return json({ ok: false, error: "webhook not configured" }, 403);
  }

  const body = await request.text();  // need raw body for signature
  const svixId = request.headers.get("svix-id");
  const svixTs = request.headers.get("svix-timestamp");
  const svixSig = request.headers.get("svix-signature");

  if (!svixId || !svixTs || !svixSig) {
    return json({ ok: false, error: "missing svix headers" }, 400);
  }

  // Replay protection: reject events more than 5 minutes old
  const now = Math.floor(Date.now() / 1000);
  const ts = parseInt(svixTs, 10);
  if (!Number.isFinite(ts) || Math.abs(now - ts) > 300) {
    return json({ ok: false, error: "timestamp too old or invalid" }, 400);
  }

  const ok = await verifyResendSignature(env.RESEND_WEBHOOK_SECRET, svixId, svixTs, body, svixSig);
  if (!ok) {
    return json({ ok: false, error: "bad signature" }, 401);
  }

  let event;
  try {
    event = JSON.parse(body);
  } catch (_e) {
    return json({ ok: false, error: "bad json" }, 400);
  }

  const type = event && event.type;
  const data = (event && event.data) || {};
  // Resend's `to` is always an array (even when single recipient)
  const toList = Array.isArray(data.to) ? data.to : (data.to ? [data.to] : []);
  if (!toList.length) {
    return json({ ok: true, action: "ignored", reason: "no recipient", type }, 200);
  }

  // Decision: which event types cause removal?
  //   email.bounced + bounce.type == "Permanent"  → remove (hard bounce)
  //   email.bounced + bounce.type == "Transient"  → keep (soft, retry-able)
  //   email.complained                            → remove (spam report)
  //   anything else                                → ignore
  let shouldRemove = false;
  let reason = "";
  if (type === "email.complained") {
    shouldRemove = true;
    reason = "spam complaint";
  } else if (type === "email.bounced") {
    // Resend bounce structure: data.bounce = { type: "Permanent"|"Transient"|"Undetermined", ... }
    const bounceType = (data.bounce && data.bounce.type) || "Undetermined";
    if (bounceType === "Permanent") {
      shouldRemove = true;
      reason = "hard bounce";
    } else {
      // Soft bounce — log but keep the subscriber
      return json({ ok: true, action: "ignored", reason: `soft bounce (${bounceType})`, to: toList }, 200);
    }
  } else {
    return json({ ok: true, action: "ignored", reason: `event type "${type}" not actionable` }, 200);
  }

  // Remove every recipient address from KV
  const results = [];
  for (const email of toList) {
    try {
      const r = await removeSubscriber(env, String(email).trim());
      results.push({ email, removed: r.removed, count: r.count });
    } catch (e) {
      results.push({ email, error: String(e.message || e) });
    }
  }
  return json({ ok: true, action: "removed", reason, results, type }, 200);
}

async function verifyResendSignature(secret, id, timestamp, body, headerValue) {
  // Secret is "whsec_<base64>"; decode the suffix as raw bytes.
  const b64 = secret.startsWith("whsec_") ? secret.slice(6) : secret;
  let secretBytes;
  try {
    const raw = atob(b64);
    secretBytes = new Uint8Array(raw.length);
    for (let i = 0; i < raw.length; i++) secretBytes[i] = raw.charCodeAt(i);
  } catch (_e) {
    return false;
  }
  const key = await crypto.subtle.importKey(
    "raw",
    secretBytes,
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const toSign = `${id}.${timestamp}.${body}`;
  const sigBytes = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(toSign));
  // Base64 encode
  let sigB64 = "";
  const arr = new Uint8Array(sigBytes);
  for (let i = 0; i < arr.length; i++) sigB64 += String.fromCharCode(arr[i]);
  sigB64 = btoa(sigB64);

  // Header value: "v1,base64sig v1,base64sig2 ..." — accept if any match
  const candidates = headerValue.split(" ").map((s) => {
    const parts = s.split(",");
    return parts.length === 2 ? parts[1] : "";
  }).filter(Boolean);

  // Constant-time compare against each candidate
  for (const cand of candidates) {
    if (cand.length !== sigB64.length) continue;
    let diff = 0;
    for (let i = 0; i < cand.length; i++) {
      diff |= cand.charCodeAt(i) ^ sigB64.charCodeAt(i);
    }
    if (diff === 0) return true;
  }
  return false;
}
