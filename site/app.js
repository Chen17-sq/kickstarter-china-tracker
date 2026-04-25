// Kickstarter China Tracker — Editorial frontend
// Loads ./data/projects.json (committed every 4h by .github/workflows/scrape.yml)

const $ = (q) => document.querySelector(q);
const $$ = (q) => document.querySelectorAll(q);

const STATUS_ZH = {
  prelaunch: "未发布",
  live: "在筹中",
  successful: "已成功",
  failed: "未达标",
  canceled: "已取消",
  suspended: "已暂停",
  unknown: "—",
};
const STATUS_ORDER = {
  prelaunch: 0, live: 1, successful: 2, failed: 3,
  canceled: 4, suspended: 5, unknown: 9,
};

// ─── State ─────────────────────────────────────────────────────
let DATA = [];
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
  const v = Number(p) * 100;
  if (v >= 1000) return Math.round(v).toLocaleString() + "%";
  return v.toFixed(0) + "%";
}
function fmtNum(n) {
  if (n == null || n === "" || isNaN(Number(n))) return "—";
  return Number(n).toLocaleString();
}
function fmtDate(iso) {
  if (!iso) return "";
  return iso.replace("T", " ").replace("Z", " UTC");
}
function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

// ─── Sort ──────────────────────────────────────────────────────
function defaultSort(a, b) {
  const oa = STATUS_ORDER[a.status] ?? 9;
  const ob = STATUS_ORDER[b.status] ?? 9;
  if (oa !== ob) return oa - ob;
  // Within prelaunch: followers (when we have them) then PWL
  if (a.status === "prelaunch") {
    const fa = Number(a.followers || 0), fb = Number(b.followers || 0);
    if (fa !== fb) return fb - fa;
    if (!!b.project_we_love !== !!a.project_we_love) {
      return (b.project_we_love ? 1 : 0) - (a.project_we_love ? 1 : 0);
    }
  }
  // Within live/ended: dollars pledged
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
  const pwl = d.project_we_love ? '<span class="pwl">★</span>' : "";
  const title = escapeHtml(d.title || "(untitled)");
  const company = escapeHtml(d.matched_brand || d.creator || d.creator_name || "");
  const loc = escapeHtml(d.location || "");
  const cat = escapeHtml(d.category || "");
  const meta = [company, loc, cat].filter(Boolean).join(" · ");
  const status = d.status || "unknown";
  const pctVal = Number(d.percent_funded || 0) * 100;
  let pctCls = "pct under";
  if (pctVal >= 100 && pctVal < 1000) pctCls = "pct";
  else if (pctVal >= 1000) pctCls = "pct huge";
  const url = d.url || "";

  return `<tr>
    <td>
      <div class="cell-title">${pwl}${title}</div>
      <div class="cell-meta">${meta}</div>
    </td>
    <td><span class="status ${status}">${STATUS_ZH[status] || status}</span></td>
    <td class="hide-sm">
      <span class="conf ${d.china_confidence === "高" ? "high" : ""}">${escapeHtml(d.china_confidence || "?")}</span>
      <div class="country">${escapeHtml(d.country || "")}</div>
    </td>
    <td class="num">
      <div class="dollar">${fmtUSD(d.pledged_usd)}</div>
      ${d.goal_usd ? `<div class="goal">/ ${fmtUSD(d.goal_usd)}</div>` : ""}
    </td>
    <td class="num hide-md">${fmtNum(d.backers)}</td>
    <td class="num hide-md">${fmtNum(d.followers)}</td>
    <td class="num hide-md"><span class="${pctCls}">${fmtPct(d.percent_funded)}</span></td>
    <td>${url ? `<a class="link" href="${escapeHtml(url)}" target="_blank" rel="noopener">KS →</a>` : ""}</td>
  </tr>`;
}

function renderTable(rows) {
  $("#table-host").innerHTML = `
    <table>
      <thead><tr>
        <th data-k="title">项目 / 创作者</th>
        <th data-k="status">状态</th>
        <th data-k="china_confidence" class="hide-sm">置信度</th>
        <th data-k="pledged_usd" class="num">已筹</th>
        <th data-k="backers" class="num hide-md">Backers</th>
        <th data-k="followers" class="num hide-md">Followers</th>
        <th data-k="percent_funded" class="num hide-md">完成率</th>
        <th class="no-sort">链接</th>
      </tr></thead>
      <tbody>${rows.map(rowHtml).join("")}</tbody>
    </table>`;

  // sort indicators
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

function renderKpis() {
  const counts = { prelaunch: 0, live: 0, successful: 0, failed: 0 };
  let pwl = 0, high = 0, totalUsd = 0;
  DATA.forEach((d) => {
    counts[d.status] = (counts[d.status] || 0) + 1;
    if (d.project_we_love) pwl++;
    if (d.china_confidence === "高") high++;
    if (d.status === "live") totalUsd += Number(d.pledged_usd || 0);
  });

  $("#kpis").innerHTML = `
    <div class="kpi"><div class="label">追踪总数</div>
      <div class="num">${DATA.length}</div>
      <div class="delta">中国背景 高 · ${high}</div></div>
    <div class="kpi is-pre"><div class="label">未发布</div>
      <div class="num">${counts.prelaunch}</div>
      <div class="delta">prelaunch</div></div>
    <div class="kpi is-live"><div class="label">在筹中</div>
      <div class="num">${counts.live}</div>
      <div class="delta">已筹 ${fmtUSD(totalUsd)}</div></div>
    <div class="kpi"><div class="label">已成功</div>
      <div class="num">${counts.successful}</div>
      <div class="delta">successful</div></div>
    <div class="kpi"><div class="label">★ KS 精选</div>
      <div class="num">${pwl}</div>
      <div class="delta">project we love</div></div>`;
}

function applyFilters(rows) {
  return rows.filter((d) => {
    if (FILTERS.status && d.status !== FILTERS.status) return false;
    if (FILTERS.conf && d.china_confidence !== FILTERS.conf) return false;
    if (FILTERS.pwl && !d.project_we_love) return false;
    if (FILTERS.q) {
      const hay = [
        d.title, d.creator, d.creator_name, d.matched_brand,
        d.location, d.country, d.category, d.blurb,
      ].filter(Boolean).join(" ").toLowerCase();
      if (!hay.includes(FILTERS.q)) return false;
    }
    return true;
  });
}

function render() {
  const visible = applyFilters(DATA);
  $("#count").innerHTML =
    `显示 <b>${visible.length.toLocaleString()}</b> / ${DATA.length.toLocaleString()} 个项目` +
    (FILTERS.q || FILTERS.status || FILTERS.conf || FILTERS.pwl
      ? ` · <a href="#" id="clearF" style="color:inherit;border-bottom:1px solid currentColor;text-decoration:none">清除筛选</a>`
      : "");
  if ($("#clearF")) {
    $("#clearF").addEventListener("click", (e) => {
      e.preventDefault();
      FILTERS = { status: "", conf: "", pwl: false, q: "" };
      $("#q").value = ""; $("#onlyPwl").checked = false;
      buildChips();
      render();
    });
  }
  renderTable(visible);
}

// ─── Chips & filters ────────────────────────────────────────────
function makeChips(hostId, options, key) {
  const el = $(hostId);
  el.innerHTML = options.map((o) =>
    `<button class="chip${FILTERS[key] === o.value ? " active" : ""}" data-v="${escapeHtml(o.value)}">${escapeHtml(o.label)}</button>`
  ).join("");
  el.querySelectorAll(".chip").forEach((c) => {
    c.addEventListener("click", () => {
      FILTERS[key] = c.dataset.v;
      makeChips(hostId, options, key);
      render();
    });
  });
}

function buildChips() {
  makeChips("#statusChips", [
    { value: "", label: "全部" },
    { value: "prelaunch", label: "未发布" },
    { value: "live", label: "在筹" },
    { value: "successful", label: "已成功" },
  ], "status");
  makeChips("#confChips", [
    { value: "", label: "全部" },
    { value: "高", label: "高" },
    { value: "中", label: "中" },
  ], "conf");
}

// ─── Boot ──────────────────────────────────────────────────────
async function load() {
  try {
    const r = await fetch("./data/projects.json", { cache: "no-store" });
    if (!r.ok) throw new Error("HTTP " + r.status);
    const j = await r.json();
    DATA = j.projects || [];
    applySort();
    $("#updated").textContent = "更新于 " + fmtDate(j.generated_at);
    boot();
  } catch (e) {
    document.body.insertAdjacentHTML("beforeend",
      `<div class="wrap"><div class="err">
        加载 <code>./data/projects.json</code> 失败：${escapeHtml(e.message)}<br>
        本地试 <code>python -m scraper.run</code>，或者去 GitHub Actions 手动触发一次 scrape。
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
  renderKpis();
  render();
}

load();
