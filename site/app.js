// Kickstarter China Tracker — Newsprint frontend
// Loads ./data/projects.json (committed daily by .github/workflows/scrape.yml)

const $ = (q) => document.querySelector(q);
const $$ = (q) => document.querySelectorAll(q);

// ─── i18n ──────────────────────────────────────────────────────
const LANG_KEY = "ks-tracker-lang";
let LANG = localStorage.getItem(LANG_KEY) || "zh";

const I18N = {
  zh: {
    kicker: "实时数据 · cron 每日北京时间 09:00 刷新",
    motto: "All The Crowd-Funded Hardware Fit To Print",
    editionLeft: "北京版",
    editionRightPrefix: "更新于 ",
    dek: "追踪 Kickstarter 上中国背景的消费硬件项目，覆盖 pre-launch / live / 已结束三个阶段。数据通过 KS Discover JSON 直连，每日由 GitHub Actions 重抓一次。",
    loading: "加载中…",
    statusLabel: "状态",
    confLabel: "置信度",
    pwlLabel: "★ 仅看 KS 编辑精选",
    searchPh: "搜索 · 产品 · 公司 · 城市",
    countShow: (n, t) => `共 <b>${t}</b> 项 · 显示 <b>${n}</b> 项`,
    clearFilters: "清除筛选",
    kpi: {
      total: "追踪总数", totalDelta: (h) => `中国背景 高 · ${h}`,
      prelaunch: "未发布", prelaunchDelta: "PRELAUNCH",
      live: "在筹中", liveDelta: (s) => `合计 ${s}`,
      success: "已成功", successDelta: "SUCCESSFUL",
      pwl: "★ 编辑精选", pwlDelta: "PROJECT WE LOVE",
    },
    chips: { all: "全部", prelaunch: "未发布", live: "在筹", successful: "已成功", high: "高", med: "中" },
    statuses: {
      prelaunch: "PRELAUNCH", live: "LIVE", successful: "FUNDED",
      failed: "FAILED", canceled: "CANCELED", suspended: "SUSPENDED", unknown: "—",
    },
    th: {
      project: "PROJECT · 产品 / 创作者", status: "STATUS",
      conf: "CN", pledged: "RAISED",
      backers: "BACKERS", followers: "WATCH",
      percent: "FUNDED", link: "READ",
    },
  },
  en: {
    kicker: "Live · cron refreshes daily at 09:00 Beijing",
    motto: "All The Crowd-Funded Hardware Fit To Print",
    editionLeft: "Beijing Edition",
    editionRightPrefix: "Updated ",
    dek: "The morning newspaper for China-background Kickstarter consumer-hardware projects — pre-launch, live, and recently funded. Data fetched from KS Discover JSON every day by GitHub Actions.",
    loading: "Loading…",
    statusLabel: "Status",
    confLabel: "Confidence",
    pwlLabel: "★ Editor's Picks Only",
    searchPh: "Search · product · brand · city",
    countShow: (n, t) => `<b>${t}</b> total · <b>${n}</b> on view`,
    clearFilters: "Clear filters",
    kpi: {
      total: "Tracked", totalDelta: (h) => `High Confidence · ${h}`,
      prelaunch: "Pre-launch", prelaunchDelta: "PRELAUNCH",
      live: "Live", liveDelta: (s) => `Pledged ${s}`,
      success: "Funded", successDelta: "SUCCESSFUL",
      pwl: "★ Editor's Picks", pwlDelta: "PROJECT WE LOVE",
    },
    chips: { all: "All", prelaunch: "Pre", live: "Live", successful: "Funded", high: "High", med: "Med" },
    statuses: {
      prelaunch: "PRELAUNCH", live: "LIVE", successful: "FUNDED",
      failed: "FAILED", canceled: "CANCELED", suspended: "SUSPENDED", unknown: "—",
    },
    th: {
      project: "PROJECT · BRAND", status: "STATUS",
      conf: "CN", pledged: "RAISED",
      backers: "BACKERS", followers: "WATCH",
      percent: "FUNDED", link: "READ",
    },
  },
};

const COUNTRY_ZH = {
  HK: "香港", CN: "中国大陆", TW: "台湾", MO: "澳门",
  US: "美国 (出海)", GB: "英国 (出海)", DE: "德国 (出海)",
  JP: "日本 (出海)", SG: "新加坡 (出海)", CA: "加拿大 (出海)",
  AU: "澳洲 (出海)", FR: "法国 (出海)", NL: "荷兰 (出海)",
  KR: "韩国 (出海)", ES: "西班牙 (出海)", IT: "意大利 (出海)",
};
const CATEGORY_ZH = {
  "Hardware": "智能硬件", "Product Design": "产品设计", "Gadgets": "电子配件",
  "3D Printing": "3D 打印", "Sound": "音频", "Wearables": "可穿戴",
  "DIY Electronics": "DIY 电子", "Robots": "机器人",
  "Fabrication Tools": "制造工具", "Camera Equipment": "摄影器材",
  "Web": "网络应用", "Apps": "应用", "Software": "软件",
  "Mobile Games": "手机游戏", "Tabletop Games": "桌游", "Video Games": "电子游戏",
  "Design": "设计", "Technology": "科技", "Crafts": "手作",
  "Fashion": "时装", "Accessories": "配饰",
};

const STATUS_ORDER = {
  prelaunch: 0, live: 1, successful: 2, failed: 3,
  canceled: 4, suspended: 5, unknown: 9,
};

function t() { return I18N[LANG]; }
function brandLabel(d) {
  if (LANG === "zh") return d.matched_brand_zh || d.matched_brand || d.creator || d.creator_name || "";
  return d.matched_brand || d.creator || d.creator_name || "";
}
function countryLabel(c) {
  if (!c) return "";
  return LANG === "zh" ? (COUNTRY_ZH[c] || c) : c;
}
function categoryLabel(c) {
  if (!c) return "";
  return LANG === "zh" ? (CATEGORY_ZH[c] || c) : c;
}
function blurbInfo(d) {
  if (LANG === "zh" && d.blurb_zh) return { text: d.blurb_zh, fallback: false };
  if (d.blurb) return { text: d.blurb, fallback: LANG === "zh" };
  return { text: "", fallback: false };
}

// ─── State ─────────────────────────────────────────────────────
let DATA = [];
let GENERATED_AT = "";
let FILTERS = { status: "", conf: "", pwl: false, q: "" };
let SORT = { k: null, dir: "desc" };

// ─── Formatters ────────────────────────────────────────────────
function fmtUSD(n) {
  if (n == null || n === "" || isNaN(Number(n))) return "—";
  const v = Number(n);
  if (v >= 1e6) return "$" + (v / 1e6).toFixed(2).replace(/\.?0+$/, "") + "M";
  if (v >= 1e4) return "$" + Math.round(v / 1e3) + "K";
  if (v >= 1e3) return "$" + (v / 1e3).toFixed(1) + "K";
  return "$" + Math.round(v).toLocaleString();
}
function fmtPct(p) {
  if (p == null || p === "" || isNaN(Number(p))) return "—";
  const v = Number(p);
  if (v >= 10000) return Math.round(v / 100).toLocaleString() + "× goal";
  if (v >= 1000) return Math.round(v).toLocaleString() + "%";
  return Math.round(v) + "%";
}
function fmtNum(n) {
  if (n == null || n === "" || isNaN(Number(n))) return "—";
  return Number(n).toLocaleString();
}
function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

// $/watcher — meaningful for live + ended; null when no watchers data.
function conversionPerWatcher(d) {
  const f = Number(d.followers || 0);
  const p = Number(d.pledged_usd || 0);
  if (f <= 0 || p <= 0) return null;
  return p / f;
}

// Naïve linear projection for live: $/day × total_campaign_days.
function projectedTotal(d) {
  if (d.status !== "live") return null;
  const launched = Number(d.launched_at || 0);
  const deadline = Number(d.deadline || 0);
  const pledged = Number(d.pledged_usd || 0);
  if (launched <= 0 || deadline <= launched) return null;
  const now = Date.now() / 1000;
  const daysIn = (now - launched) / 86400;
  const totalDays = (deadline - launched) / 86400;
  if (daysIn < 0.5) return null;
  return (pledged / daysIn) * totalDays;
}

function fmtDeltaInt(n) {
  if (n == null || n === 0 || isNaN(Number(n))) return "";
  const v = Number(n);
  return (v > 0 ? "+" : "") + v.toLocaleString();
}
function fmtDeltaUSD(n) {
  if (n == null || isNaN(Number(n)) || Math.abs(Number(n)) < 1) return "";
  const v = Number(n);
  return (v > 0 ? "+" : "−") + fmtUSD(Math.abs(v));
}

function fmtTimeline(d) {
  const now = Date.now() / 1000;
  if (d.status === "prelaunch") {
    const start = d.state_changed_at || d.created_at;
    if (!start) return "";
    const days = Math.max(0, Math.floor((now - Number(start)) / 86400));
    return LANG === "zh" ? `已预热 ${days} 天` : `${days}d in pre-launch`;
  }
  if (d.status === "live") {
    const parts = [];
    if (d.launched_at) {
      const since = Math.max(0, Math.floor((now - Number(d.launched_at)) / 86400));
      parts.push(LANG === "zh" ? `上线 ${since} 天` : `${since}d in`);
    }
    if (d.deadline) {
      const remain = Math.max(0, Math.floor((Number(d.deadline) - now) / 86400));
      parts.push(LANG === "zh" ? `剩 ${remain} 天` : `${remain}d left`);
    }
    return parts.join(" · ");
  }
  if (d.status === "successful" || d.status === "failed" || d.status === "canceled") {
    if (!d.deadline) return "";
    const ago = Math.floor((now - Number(d.deadline)) / 86400);
    if (ago < 0) return "";
    if (ago < 1) return LANG === "zh" ? "今日结束" : "ended today";
    if (ago < 60) return LANG === "zh" ? `${ago} 天前结束` : `ended ${ago}d ago`;
    const dt = new Date(Number(d.deadline) * 1000);
    return (LANG === "zh" ? "结束于 " : "ended ") + dt.toISOString().slice(0, 10);
  }
  return "";
}

// ─── Sort ──────────────────────────────────────────────────────
function defaultSort(a, b) {
  const oa = STATUS_ORDER[a.status] ?? 9;
  const ob = STATUS_ORDER[b.status] ?? 9;
  if (oa !== ob) return oa - ob;
  if (a.status === "prelaunch") {
    const fa = Number(a.followers || 0), fb = Number(b.followers || 0);
    if (fa !== fb) return fb - fa;
    if (!!b.project_we_love !== !!a.project_we_love) {
      return (b.project_we_love ? 1 : 0) - (a.project_we_love ? 1 : 0);
    }
  }
  const pa = Number(a.pledged_usd || 0), pb = Number(b.pledged_usd || 0);
  if (pa !== pb) return pb - pa;
  return (a.title || "").localeCompare(b.title || "", "zh");
}
function applySort() {
  if (!SORT.k) {
    DATA.sort(defaultSort);
    return;
  }
  const k = SORT.k, dir = SORT.dir === "asc" ? 1 : -1;
  DATA.sort((a, b) => {
    const av = a[k], bv = b[k];
    const an = Number(av), bn = Number(bv);
    if (!isNaN(an) && !isNaN(bn) && av !== "" && bv !== "" && av != null && bv != null) {
      return (an - bn) * dir;
    }
    return String(av ?? "").localeCompare(String(bv ?? ""), "zh") * dir;
  });
}

// ─── Render ────────────────────────────────────────────────────
function rowHtml(d) {
  const pwl = d.project_we_love ? '<span class="pwl">✦</span>' : "";
  const title = escapeHtml(d.title || "(untitled)");
  const company = escapeHtml(brandLabel(d));
  const loc = escapeHtml(d.location || "");
  const cat = escapeHtml(categoryLabel(d.category));
  const tl = escapeHtml(fmtTimeline(d));
  // Conversion + projection (meta line, only for live/ended where it makes sense)
  const cpw = conversionPerWatcher(d);
  const proj = projectedTotal(d);
  const cpwStr = (cpw && (d.status === "live" || d.status === "successful"))
    ? `${fmtUSD(cpw)}/W` : "";
  const projStr = proj ? `Proj. ${fmtUSD(proj)}` : "";
  const priceStr = d.min_pledge_usd ? `起步价 ${fmtUSD(d.min_pledge_usd)}` : "";
  const meta = [tl, company, loc, cat, priceStr, cpwStr, projStr].filter(Boolean).join(" · ");
  const b = blurbInfo(d);
  const blurbHtml = b.text
    ? `<div class="cell-blurb${b.fallback ? " is-fallback" : ""}">${escapeHtml(b.text)}</div>`
    : "";
  const status = d.status || "unknown";
  const pctVal = Number(d.percent_funded || 0);
  let pctCls = "pct under";
  if (pctVal >= 100 && pctVal < 1000) pctCls = "pct";
  else if (pctVal >= 1000) pctCls = "pct huge";
  const url = d.url || "";

  // Inline deltas (red, JetBrains Mono, only when positive)
  const dPledged = fmtDeltaUSD(d.delta_pledged_usd);
  const dBackers = fmtDeltaInt(d.delta_backers);
  const dFollowers = fmtDeltaInt(d.delta_followers);
  const dPledgedHtml = dPledged ? ` <span class="delta">${dPledged}</span>` : "";
  const dBackersHtml = dBackers ? ` <span class="delta">${dBackers}</span>` : "";
  const dFollowersHtml = dFollowers ? ` <span class="delta">${dFollowers}</span>` : "";

  return `<tr>
    <td>
      <div class="cell-title">${pwl}${title}</div>
      ${blurbHtml}
      <div class="cell-meta">${meta}</div>
    </td>
    <td><span class="status ${status}">${escapeHtml(t().statuses[status] || status)}</span></td>
    <td class="hide-sm">
      <span class="conf ${d.china_confidence === "高" ? "high" : ""}">${escapeHtml(d.china_confidence || "?")}</span>
      <div class="country">${escapeHtml(countryLabel(d.country))}</div>
    </td>
    <td class="num">
      <div class="dollar">${fmtUSD(d.pledged_usd)}${dPledgedHtml}</div>
      ${d.goal_usd ? `<div class="goal">/ ${fmtUSD(d.goal_usd)}</div>` : ""}
    </td>
    <td class="num hide-md">${fmtNum(d.backers)}${dBackersHtml}</td>
    <td class="num hide-md">${fmtNum(d.followers)}${dFollowersHtml}</td>
    <td class="num hide-md"><span class="${pctCls}">${fmtPct(d.percent_funded)}</span></td>
    <td>${url ? `<a class="link" href="${escapeHtml(url)}" target="_blank" rel="noopener">KS →</a>` : ""}</td>
  </tr>`;
}

function renderTable(rows) {
  const th = t().th;
  $("#table-host").innerHTML = `
    <table>
      <thead><tr>
        <th data-k="title">${escapeHtml(th.project)}</th>
        <th data-k="status">${escapeHtml(th.status)}</th>
        <th data-k="china_confidence" class="hide-sm">${escapeHtml(th.conf)}</th>
        <th data-k="pledged_usd" class="num">${escapeHtml(th.pledged)}</th>
        <th data-k="backers" class="num hide-md">${escapeHtml(th.backers)}</th>
        <th data-k="followers" class="num hide-md">${escapeHtml(th.followers)}</th>
        <th data-k="percent_funded" class="num hide-md">${escapeHtml(th.percent)}</th>
        <th class="no-sort">${escapeHtml(th.link)}</th>
      </tr></thead>
      <tbody>${rows.map(rowHtml).join("")}</tbody>
    </table>`;

  $$("thead th[data-k]").forEach((th) => {
    if (SORT.k === th.dataset.k) {
      th.classList.add("sort-key");
      if (SORT.dir === "asc") th.classList.add("asc");
    }
    th.addEventListener("click", () => {
      const k = th.dataset.k;
      if (SORT.k === k) SORT.dir = SORT.dir === "asc" ? "desc" : "asc";
      else { SORT.k = k; SORT.dir = "desc"; }
      applySort();
      render();
    });
  });
}

// ─── Today's Front Page hero ─────────────────────────────────
function renderHero() {
  if (!DATA.length) {
    document.getElementById("hero").hidden = true;
    return;
  }
  // Top movers by USD delta (live + prelaunch combined)
  const movers = DATA
    .filter((p) => (p.delta_pledged_usd || 0) > 0 || (p.delta_followers || 0) > 0)
    .sort((a, b) => {
      const da = Number(a.delta_pledged_usd || 0);
      const db = Number(b.delta_pledged_usd || 0);
      if (da !== db) return db - da;
      return Number(b.delta_followers || 0) - Number(a.delta_followers || 0);
    })
    .slice(0, 3);

  const prelaunch = DATA
    .filter((p) => p.status === "prelaunch")
    .sort((a, b) => {
      if (!!b.project_we_love !== !!a.project_we_love) {
        return (b.project_we_love ? 1 : 0) - (a.project_we_love ? 1 : 0);
      }
      return Number(b.followers || 0) - Number(a.followers || 0);
    })
    .slice(0, 3);

  const live = DATA
    .filter((p) => p.status === "live")
    .sort((a, b) => Number(b.pledged_usd || 0) - Number(a.pledged_usd || 0))
    .slice(0, 3);

  const langZh = LANG === "zh";
  document.getElementById("heroLabel").textContent =
    langZh ? "今日头版 · 自动生成" : "TODAY'S FRONT PAGE · AUTO-GENERATED";
  document.getElementById("heroTitle").textContent =
    langZh ? "今日头版" : "Today's Front Page";
  document.getElementById("heroMeta").textContent =
    GENERATED_AT ? GENERATED_AT.replace("T", " ").slice(0, 16) + " UTC" : "—";
  document.getElementById("heroMoversLabel").textContent =
    langZh ? "🔥 Top Movers · 24小时变化" : "🔥 Top Movers · Δ 24H";
  document.getElementById("heroPreLabel").textContent =
    langZh ? "⏳ 未发布 · 关注数 Top 3" : "⏳ Prelaunch · Top Watchers";
  document.getElementById("heroLiveLabel").textContent =
    langZh ? "🔴 在筹中 · 已筹 Top 3" : "🔴 Live · Top USD Raised";

  function story(rank, p, opts) {
    const url = escapeHtml(p.url || "#");
    const title = escapeHtml(p.title || "(untitled)");
    const star = p.project_we_love
      ? '<span class="pwl" style="font-size:13px">✦</span> '
      : "";
    const blurb = escapeHtml(p.blurb_zh || p.blurb || "");
    const blurbHtml = blurb
      ? `<div class="blurb">${blurb}</div>`
      : "";
    let valHtml = "";
    if (opts.kind === "mover") {
      const dp = Number(p.delta_pledged_usd || 0);
      const df = Number(p.delta_followers || 0);
      if (dp > 0) {
        valHtml = `<div class="v delta">+${escapeHtml(fmtUSD(dp))}</div><div class="l">USD Δ</div>`;
      } else if (df > 0) {
        valHtml = `<div class="v delta">+${df.toLocaleString()}</div><div class="l">WATCH Δ</div>`;
      }
    } else if (opts.kind === "prelaunch") {
      valHtml = `<div class="v">${fmtNum(p.followers)}</div><div class="l">${langZh ? "关注" : "WATCH"}</div>`;
    } else if (opts.kind === "live") {
      valHtml = `<div class="v">${fmtUSD(p.pledged_usd)}</div><div class="l">${fmtNum(p.backers)} ${langZh ? "支持" : "BACK"}</div>`;
    }
    return `<div class="hero-story">
      <span class="rank">${String(rank).padStart(2, "0")}</span>
      <div class="body">
        <a href="${url}" target="_blank" rel="noopener">${star}${title}</a>
        ${blurbHtml}
      </div>
      <div class="right">${valHtml}</div>
    </div>`;
  }

  const moversHtml = movers.length
    ? movers.map((p, i) => story(i + 1, p, { kind: "mover" })).join("")
    : `<div class="hero-empty">${langZh ? "等待第一份对比快照…" : "awaiting first delta…"}</div>`;
  const preHtml = prelaunch.length
    ? prelaunch.map((p, i) => story(i + 1, p, { kind: "prelaunch" })).join("")
    : `<div class="hero-empty">${langZh ? "—" : "—"}</div>`;
  const liveHtml = live.length
    ? live.map((p, i) => story(i + 1, p, { kind: "live" })).join("")
    : `<div class="hero-empty">${langZh ? "—" : "—"}</div>`;

  document.getElementById("heroMovers").innerHTML = moversHtml;
  document.getElementById("heroPre").innerHTML = preHtml;
  document.getElementById("heroLive").innerHTML = liveHtml;
  document.getElementById("hero").hidden = false;
}

function renderKpis() {
  const counts = { prelaunch: 0, live: 0, successful: 0, failed: 0 };
  let pwl = 0, high = 0, totalUsd = 0;
  DATA.forEach((d) => {
    counts[d.status] = (counts[d.status] || 0) + 1;
    if (d.project_we_love) pwl++;
    if (d.china_confidence === "高") high++;
    if (d.status === "live") totalUsd += Number(d.pledged_usd || 0);
  });
  const k = t().kpi;
  $("#kpis").innerHTML = `
    <div class="kpi"><div class="label">${escapeHtml(k.total)}</div>
      <div class="num">${DATA.length}</div>
      <div class="delta">${escapeHtml(k.totalDelta(high))}</div></div>
    <div class="kpi is-pre"><div class="label">${escapeHtml(k.prelaunch)}</div>
      <div class="num">${counts.prelaunch}</div>
      <div class="delta">${escapeHtml(k.prelaunchDelta)}</div></div>
    <div class="kpi is-live"><div class="label">${escapeHtml(k.live)}</div>
      <div class="num">${counts.live}</div>
      <div class="delta">${escapeHtml(k.liveDelta(fmtUSD(totalUsd)))}</div></div>
    <div class="kpi"><div class="label">${escapeHtml(k.success)}</div>
      <div class="num">${counts.successful}</div>
      <div class="delta">${escapeHtml(k.successDelta)}</div></div>
    <div class="kpi"><div class="label">${escapeHtml(k.pwl)}</div>
      <div class="num">${pwl}</div>
      <div class="delta">${escapeHtml(k.pwlDelta)}</div></div>`;
}

function applyFilters(rows) {
  return rows.filter((d) => {
    if (FILTERS.status && d.status !== FILTERS.status) return false;
    if (FILTERS.conf && d.china_confidence !== FILTERS.conf) return false;
    if (FILTERS.pwl && !d.project_we_love) return false;
    if (FILTERS.q) {
      const hay = [
        d.title, d.creator, d.creator_name, d.matched_brand, d.matched_brand_zh,
        d.location, d.country, d.category, d.blurb, d.blurb_zh,
      ].filter(Boolean).join(" ").toLowerCase();
      if (!hay.includes(FILTERS.q)) return false;
    }
    return true;
  });
}

function render() {
  const visible = applyFilters(DATA);
  const hasFilter = FILTERS.q || FILTERS.status || FILTERS.conf || FILTERS.pwl;
  $("#count").innerHTML =
    t().countShow(visible.length.toLocaleString(), DATA.length.toLocaleString()) +
    (hasFilter
      ? ` · <a href="#" id="clearF" style="color:inherit;border-bottom:2px solid var(--accent);text-decoration:none;font-weight:700">${escapeHtml(t().clearFilters)}</a>`
      : "");
  if ($("#clearF")) {
    $("#clearF").addEventListener("click", (e) => {
      e.preventDefault();
      FILTERS = { status: "", conf: "", pwl: false, q: "" };
      $("#q").value = ""; $("#onlyPwl").checked = false;
      buildChips(); render();
    });
  }
  renderTable(visible);
}

// ─── Chips ─────────────────────────────────────────────────────
function makeChips(hostId, options, key) {
  const el = $(hostId);
  el.innerHTML = options.map((o) =>
    `<button class="chip${FILTERS[key] === o.value ? " active" : ""}" data-v="${escapeHtml(o.value)}">${escapeHtml(o.label)}</button>`
  ).join("");
  el.querySelectorAll(".chip").forEach((c) => {
    c.addEventListener("click", () => {
      FILTERS[key] = c.dataset.v;
      makeChips(hostId, options, key); render();
    });
  });
}
function buildChips() {
  const c = t().chips;
  makeChips("#statusChips", [
    { value: "", label: c.all },
    { value: "prelaunch", label: c.prelaunch },
    { value: "live", label: c.live },
    { value: "successful", label: c.successful },
  ], "status");
  makeChips("#confChips", [
    { value: "", label: c.all },
    { value: "高", label: c.high },
    { value: "中", label: c.med },
  ], "conf");
}

// ─── Edition number = days since 2026-04-25 (project birthday) ──
function editionNumber() {
  const start = new Date("2026-04-25T00:00:00Z");
  const now = new Date();
  const days = Math.max(1, Math.floor((now - start) / 86400000) + 1);
  return String(days);
}

// ─── Apply masthead text per LANG ─────────────────────────────
function applyChrome() {
  const T = t();
  $("#kicker").textContent = T.kicker;
  $("#editionMotto").textContent = T.motto;
  $("#editionLeft").textContent = T.editionLeft;
  $("#dek").textContent = T.dek;
  $("#lblStatus").textContent = T.statusLabel;
  $("#lblConf").textContent = T.confLabel;
  $("#lblPwl").textContent = T.pwlLabel;
  $("#q").placeholder = T.searchPh;
  const editionNo = editionNumber();
  $("#editionNo").textContent = editionNo;
  $("#footEdition").textContent = editionNo;
  $("#updated").textContent = GENERATED_AT
    ? GENERATED_AT.replace("T", " ").replace("Z", " UTC")
    : "—";
  document.documentElement.lang = LANG === "zh" ? "zh-CN" : "en";
  $$("#langToggle button").forEach((b) =>
    b.classList.toggle("active", b.dataset.l === LANG));
}

function setLang(lang) {
  if (lang === LANG) return;
  LANG = lang;
  localStorage.setItem(LANG_KEY, LANG);
  applyChrome(); buildChips(); renderHero(); renderKpis(); render();
}

// ─── Boot ──────────────────────────────────────────────────────
async function load() {
  applyChrome();
  $$("#langToggle button").forEach((b) =>
    b.addEventListener("click", () => setLang(b.dataset.l)));
  try {
    const r = await fetch("./data/projects.json", { cache: "no-store" });
    if (!r.ok) throw new Error("HTTP " + r.status);
    const j = await r.json();
    DATA = j.projects || [];
    GENERATED_AT = j.generated_at || "";
    applySort();
    applyChrome(); boot();
  } catch (e) {
    document.body.insertAdjacentHTML("beforeend",
      `<div class="wrap"><div class="err">
        ${LANG === "zh" ? "加载" : "Failed to load"} <code>./data/projects.json</code>: ${escapeHtml(e.message)}
      </div></div>`);
  }
}

function boot() {
  buildChips();
  $("#q").addEventListener("input", (e) => {
    FILTERS.q = e.target.value.trim().toLowerCase();
    render();
  });
  $("#onlyPwl").addEventListener("change", (e) => {
    FILTERS.pwl = e.target.checked;
    render();
  });
  renderHero(); renderKpis(); render();
}

load();
