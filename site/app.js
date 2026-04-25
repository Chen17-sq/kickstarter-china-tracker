// Kickstarter China Tracker — front-end
// Loads ./data/projects.json (deployed by .github/workflows/deploy.yml)

const $ = (q) => document.querySelector(q);
const STATUS_LABEL = {
  prelaunch: "未发布",
  live: "在筹中",
  successful: "已结束（成功）",
  failed: "已结束（未达标）",
  unknown: "—",
};
const ORDER = { prelaunch: 0, live: 1, successful: 2, failed: 3, unknown: 9 };

function parseInt0(x) {
  const n = parseInt(String(x ?? "").replace(/[^0-9]/g, ""), 10);
  return Number.isFinite(n) ? n : 0;
}

function chinaBadge(v) {
  const cls = v === "高" ? "high" : v === "中" ? "med" : "low";
  return `<span class="badge ${cls}">${v || "?"}</span>`;
}
function statusPill(s) {
  return `<span class="pill ${s}">${STATUS_LABEL[s] || s}</span>`;
}

let DATA = [];
let GENERATED_AT = "";

async function load() {
  try {
    const r = await fetch("./data/projects.json", { cache: "no-store" });
    if (!r.ok) throw new Error("HTTP " + r.status);
    const j = await r.json();
    DATA = j.projects || [];
    GENERATED_AT = j.generated_at || "";
    DATA.sort((a, b) => {
      const oa = ORDER[a.status] ?? 9, ob = ORDER[b.status] ?? 9;
      if (oa !== ob) return oa - ob;
      const fa = parseInt0(a.followers), fb = parseInt0(b.followers);
      if (fa !== fb) return fb - fa;
      return (a.title || a.name || "").localeCompare(b.title || b.name || "");
    });
    $("#updated").textContent = "更新于 " + GENERATED_AT;
    boot();
  } catch (e) {
    document.body.insertAdjacentHTML("beforeend",
      `<div class="err">加载 data/projects.json 失败：${e.message}<br>
       这通常意味着第一次 GitHub Actions cron 还没跑完。运行
       <code>python -m scraper.run</code> 本地试一下，或者去 Actions 页面手动触发一次。</div>`);
  }
}

function render(rows) {
  const host = $("#table-host");
  host.innerHTML = `
    <table>
      <thead><tr>
        <th data-k="title">产品 / 公司</th>
        <th data-k="china_confidence">中国</th>
        <th data-k="location">总部</th>
        <th data-k="status">状态</th>
        <th data-k="followers">Followers</th>
        <th data-k="backers">Backers</th>
        <th data-k="pledged_native">已筹</th>
        <th data-k="funded_pct">完成率</th>
        <th data-k="days_to_go">剩余</th>
        <th data-k="title">链接</th>
      </tr></thead>
      <tbody>${rows.map(rowHtml).join("")}</tbody>
    </table>`;
  $("#count").textContent = `显示 ${rows.length} / ${DATA.length}`;
  const counts = { prelaunch: 0, live: 0, successful: 0 };
  let high = 0, pwl = 0;
  rows.forEach(r => {
    counts[r.status] = (counts[r.status] || 0) + 1;
    if (r.china_confidence === "高") high++;
    if (r.project_we_love) pwl++;
  });
  $("#kpis").innerHTML = `
    <div class="stat">未发布 <b>${counts.prelaunch}</b></div>
    <div class="stat">在筹 <b>${counts.live}</b></div>
    <div class="stat">已结束 <b>${counts.successful}</b></div>
    <div class="stat">中国背景 高 <b>${high}</b></div>
    <div class="stat">★ KS 精选 <b>${pwl}</b></div>`;

  document.querySelectorAll("thead th").forEach(th => {
    th.addEventListener("click", () => {
      const k = th.dataset.k;
      DATA.sort((a, b) => {
        const av = (a[k] ?? "").toString();
        const bv = (b[k] ?? "").toString();
        const an = parseFloat(av.replace(/[^0-9.]/g, ""));
        const bn = parseFloat(bv.replace(/[^0-9.]/g, ""));
        if (!isNaN(an) && !isNaN(bn)) return bn - an;
        return av.localeCompare(bv, "zh");
      });
      apply();
    });
  });
}

function rowHtml(d) {
  const pwl = d.project_we_love ? `<span class="pwl" title="Project We Love">★</span> ` : "";
  const url = d.url || d.ks_url || "";
  const title = d.title || d.name || "(untitled)";
  const subtitle = d.subtitle || d.subcategory || "";
  const company = d.matched_brand || d.creator || d.company || "";
  return `<tr>
    <td>${pwl}<span class="name">${title}</span><div class="muted">${company} · ${subtitle}</div></td>
    <td>${chinaBadge(d.china_confidence)}</td>
    <td>${d.location || d.hq || "—"}</td>
    <td>${statusPill(d.status)}</td>
    <td><div class="num">${d.followers ?? "—"}</div></td>
    <td><div class="num">${d.backers ?? "—"}</div></td>
    <td>${d.pledged_native || d.raised_native || "—"}<div class="small">${d.goal_native ? "of " + d.goal_native : ""}</div></td>
    <td>${d.funded_pct ? `<span class="funded">${typeof d.funded_pct === 'number' ? d.funded_pct + '%' : d.funded_pct}</span>` : "—"}</td>
    <td>${d.days_to_go ?? "—"}</td>
    <td>${url ? `<a href="${url}" target="_blank" rel="noopener">KS ↗</a>` : ""}</td>
  </tr>`;
}

function apply() {
  const q = $("#q").value.trim().toLowerCase();
  const s = $("#status").value;
  const c = $("#china").value;
  const op = $("#onlyPwl").checked;
  const out = DATA.filter(d => {
    if (s && d.status !== s) return false;
    if (c && d.china_confidence !== c) return false;
    if (op && !d.project_we_love) return false;
    if (q) {
      const hay = `${d.title || d.name || ""} ${d.creator || d.company || ""} ${d.location || d.hq || ""} ${d.category || ""} ${d.subtitle || d.subcategory || ""} ${d.highlight || ""}`.toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });
  render(out);
}

function boot() {
  ["q", "status", "china"].forEach(id => $("#" + id).addEventListener("input", apply));
  $("#onlyPwl").addEventListener("change", apply);
  apply();
}

load();
