/**
 * Kickstarter China Tracker — subscribe Worker (KV edition)
 *
 * Endpoints:
 *   POST /            — append a subscriber (used by site/subscribe.html form)
 *   GET  /list        — read full subscriber list (X-Owner-Token auth)
 *   GET  /count       — public-safe count (no emails)
 *   POST /unsubscribe — remove a subscriber by email (X-Owner-Token auth)
 *
 * Subscribers are stored in Cloudflare KV (private, never leaves CF).
 * Older versions of this Worker wrote to data/subscribers.json on the
 * public GitHub repo — that file leaked email addresses to anyone who
 * could clone the repo. KV namespace is the privacy fix.
 *
 * Required Worker bindings / vars:
 *   SUBSCRIBERS_KV  — KV namespace bound as "SUBSCRIBERS_KV" in dashboard
 *   OWNER_TOKEN     — random secret. /list and /unsubscribe require
 *                     header "X-Owner-Token: <OWNER_TOKEN>". Anything
 *                     else gets 403.
 *   ALLOWED_ORIGIN  — comma-separated whitelist of allowed Origins for CORS.
 *                     '*' falls back to allow-all (debug only).
 *
 * Subscribe-write payload (POST /):
 *   { email: "...", nickname: "..." }
 *
 * Owner-read response (GET /list):
 *   { count: N, subscribers: [{email, nickname, added_at, source}, ...] }
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
      return handleSubscribe(request, env, cors);
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
    return json({
      ok: true,
      count: result.count,
      type: result.type,
    }, 200, cors);
  } catch (e) {
    return json({ ok: false, error: String(e.message || e) }, 500, cors);
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
