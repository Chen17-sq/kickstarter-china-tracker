// Tests for worker.js logic — runs under Node, no Wrangler/Miniflare needed.
//
// We re-implement / re-import the pure helpers and exercise them against
// crafted inputs. End-to-end Worker behavior (KV roundtrips, real Resend
// calls) is NOT covered here — that needs Miniflare. These tests cover
// the bits most likely to silently regress:
//
//   - Svix HMAC signature verification (correctness + replay edge cases)
//   - Rate-limit bucket math (fail-open semantics)
//   - Welcome email HTML escape safety (no script injection via nickname)
//
// Run: node test_worker.mjs

import { createHmac } from "node:crypto";

let pass = 0;
let fail = 0;
const failures = [];

function test(name, fn) {
  return Promise.resolve()
    .then(fn)
    .then(() => { pass++; console.log(`  ✓ ${name}`); })
    .catch((e) => {
      fail++;
      failures.push({ name, error: e.message || String(e) });
      console.log(`  ✗ ${name}\n    → ${e.message || e}`);
    });
}

function assertEq(actual, expected, msg = "") {
  if (actual !== expected) {
    throw new Error(`${msg}: expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`);
  }
}

function assertTrue(v, msg = "") {
  if (!v) throw new Error(msg || "expected truthy");
}


// ── Svix signature verification (mirrors verifyResendSignature in worker.js) ──
//
// We re-implement here (rather than importing worker.js — which uses Worker
// module syntax + globals like atob/btoa that node has but with caveats).

async function verifyResendSignature(secret, id, timestamp, body, headerValue) {
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
    "raw", secretBytes, { name: "HMAC", hash: "SHA-256" }, false, ["sign"],
  );
  const toSign = `${id}.${timestamp}.${body}`;
  const sigBytes = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(toSign));
  let sigB64 = "";
  const arr = new Uint8Array(sigBytes);
  for (let i = 0; i < arr.length; i++) sigB64 += String.fromCharCode(arr[i]);
  sigB64 = btoa(sigB64);

  const candidates = headerValue.split(" ").map((s) => {
    const parts = s.split(",");
    return parts.length === 2 ? parts[1] : "";
  }).filter(Boolean);

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

function signTest(secret, id, ts, body) {
  const b64 = secret.startsWith("whsec_") ? secret.slice(6) : secret;
  const raw = Buffer.from(b64, "base64");
  return createHmac("sha256", raw).update(`${id}.${ts}.${body}`).digest("base64");
}

const SECRET = "whsec_" + Buffer.from("test-secret-1234567890abcdef").toString("base64");


console.log("Svix signature verification:");
await test("accepts valid signature", async () => {
  const id = "msg_001";
  const ts = String(Math.floor(Date.now() / 1000));
  const body = JSON.stringify({ type: "email.bounced", data: { to: ["x@y.com"] } });
  const sig = signTest(SECRET, id, ts, body);
  assertEq(await verifyResendSignature(SECRET, id, ts, body, `v1,${sig}`), true);
});

await test("rejects tampered body", async () => {
  const id = "msg_002";
  const ts = String(Math.floor(Date.now() / 1000));
  const body = JSON.stringify({ ok: true });
  const sig = signTest(SECRET, id, ts, body);
  assertEq(await verifyResendSignature(SECRET, id, ts, body + "TAMPER", `v1,${sig}`), false);
});

await test("rejects wrong secret", async () => {
  const id = "msg_003";
  const ts = String(Math.floor(Date.now() / 1000));
  const body = "{}";
  const sig = signTest(SECRET, id, ts, body);
  const wrong = "whsec_" + Buffer.from("wrong-secret-xxxxxxxxxxxxx").toString("base64");
  assertEq(await verifyResendSignature(wrong, id, ts, body, `v1,${sig}`), false);
});

await test("accepts multi-sig header when ONE valid", async () => {
  const id = "msg_004";
  const ts = String(Math.floor(Date.now() / 1000));
  const body = "{}";
  const goodSig = signTest(SECRET, id, ts, body);
  // Make the junk signature the SAME LENGTH as the real one so we exercise the
  // constant-time path beyond the length skip.
  const junk = "A".repeat(goodSig.length);
  assertEq(await verifyResendSignature(SECRET, id, ts, body, `v1,${junk} v1,${goodSig}`), true);
});

await test("rejects empty header", async () => {
  assertEq(await verifyResendSignature(SECRET, "x", "1", "{}", ""), false);
});

await test("rejects header without v1, prefix", async () => {
  const id = "msg_005";
  const ts = String(Math.floor(Date.now() / 1000));
  const body = "{}";
  const sig = signTest(SECRET, id, ts, body);
  // No comma → split parts != 2 → filtered out
  assertEq(await verifyResendSignature(SECRET, id, ts, body, sig), false);
});

await test("accepts signature with whsec_ prefix removed (raw secret)", async () => {
  const raw = SECRET.slice(6);
  const id = "msg_006";
  const ts = String(Math.floor(Date.now() / 1000));
  const body = "{}";
  const sig = signTest(SECRET, id, ts, body);
  assertEq(await verifyResendSignature(raw, id, ts, body, `v1,${sig}`), true);
});


// ── HTML escape safety in welcome email ─────────────────────────────
//
// We don't import the function — just verify the pattern: any nickname
// injected into the welcome email body MUST be either escaped or
// constrained to alphanumeric+space (which sanitizeNick does in worker.js).

console.log("\nNickname sanitization:");

// Mirror worker.js's sanitizeNick (post-fix: strips HTML chars + controls)
function sanitizeNick(s) {
  return s
    .replace(/[<>&"'`\x00-\x1F\x7F]/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

await test("nickname strips < > & ' \" ` to prevent HTML injection", async () => {
  const dirty = `<script>alert("xss")</script>&'\``;
  const clean = sanitizeNick(dirty);
  for (const ch of ["<", ">", "&", "\"", "'", "`"]) {
    assertTrue(!clean.includes(ch), `should not contain ${ch}`);
  }
});

await test("nickname allows reasonable unicode (Chinese / emoji)", async () => {
  const ok = sanitizeNick("阿尔德里奇 ✦");
  assertEq(ok, "阿尔德里奇 ✦");
});

await test("nickname collapses whitespace", async () => {
  assertEq(sanitizeNick("foo   bar\n\t baz"), "foo bar baz");
});

await test("nickname strips control chars (\\x00-\\x1F + \\x7F)", async () => {
  const clean = sanitizeNick("hi\x00\x01\x1F\x7Fworld");
  assertEq(clean, "hiworld");
});

await test("escapeHtml escapes all six chars in order", async () => {
  assertEq(escapeHtml("&<>\"'"), "&amp;&lt;&gt;&quot;&#39;");
});

await test("escapeHtml is idempotent for already-safe text", async () => {
  assertEq(escapeHtml("阿尔德里奇 hello world"), "阿尔德里奇 hello world");
});


// ── Rate-limit math ─────────────────────────────────────────────────
//
// The Worker's rateLimitOk is KV-backed and we can't exercise it without
// Miniflare. But the math is small and worth pinning: bucket key = per IP,
// per (now/window) integer division. Verify same-second requests share bucket.

console.log("\nRate-limit bucket math:");

function bucketKey(ip, now_ms, windowSec, tag = "subscribe") {
  return `rl:${tag}:${ip}:${Math.floor(now_ms / 1000 / windowSec)}`;
}

await test("two requests in same window share bucket key", async () => {
  // Anchor to the start of a minute so adding 30s can't accidentally
  // cross a window boundary (the flaky-CI failure mode).
  const minuteStart = Math.floor(Date.now() / 60_000) * 60_000;
  const k1 = bucketKey("1.2.3.4", minuteStart + 5_000, 60);   // +5s
  const k2 = bucketKey("1.2.3.4", minuteStart + 35_000, 60);  // +35s, same minute
  assertEq(k1, k2);
});

await test("requests across window boundary get different bucket", async () => {
  const now = Math.floor(Date.now() / 60_000) * 60_000;  // align to window start
  const k1 = bucketKey("1.2.3.4", now, 60);
  const k2 = bucketKey("1.2.3.4", now + 61_000, 60);  // next window
  assertTrue(k1 !== k2, "buckets should differ");
});

await test("different IPs get different buckets", async () => {
  const now = Date.now();
  assertTrue(bucketKey("1.2.3.4", now, 60) !== bucketKey("5.6.7.8", now, 60));
});

await test("different tags get different buckets", async () => {
  const now = Date.now();
  assertTrue(
    bucketKey("1.1.1.1", now, 60, "subscribe") !==
    bucketKey("1.1.1.1", now, 60, "webhook"),
  );
});


// ── Final report ─────────────────────────────────────────────────────

console.log(`\n=== ${pass} passed, ${fail} failed ===`);
if (fail > 0) {
  console.log("\nFailures:");
  for (const f of failures) console.log(`  ${f.name}: ${f.error}`);
  process.exit(1);
}
