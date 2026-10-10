/* Shared read-only aggregate contract for the dashboard and statistics page. */
(function (root) {
  "use strict";
  function observationTime(value) {
    if (typeof value !== "string") return NaN;
    // Require a real calendar date and an explicit timezone, matching the backend.
    const match = /^(\d{4})-(\d{2})-(\d{2})T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.exec(value);
    if (!match) return NaN;
    const year = Number(match[1]), month = Number(match[2]), day = Number(match[3]);
    const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
    const days = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
    if (year < 1 || month < 1 || month > 12 || day < 1 || day > days[month - 1]) return NaN;
    const parts = value.slice(11).match(/^(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(?:Z|[+-](\d{2}):(\d{2}))$/);
    if (Number(parts[1]) > 23 || Number(parts[2]) > 59 || Number(parts[3]) > 59 ||
        Number(parts[4] || 0) > 23 || Number(parts[5] || 0) > 59) return NaN;
    return Date.parse(value);
  }
  function livePledgedTotals(projects, now = Date.now()) {
    const live = projects.filter(p => p.status === "live");
    const values = live.flatMap(p => {
      const value = p.pledged_usd, meta = p.observations?.pledged_usd;
      const age = now - observationTime(meta?.observed_at);
      return typeof value === "number" && Number.isFinite(value) && value >= 0 &&
        meta?.status === "fresh" && meta?.unit === "USD" && age >= 0 && age <= 30 * 3600000
        ? [value] : [];
    });
    // Compensated summation avoids losing small project amounts in large totals.
    let sum = 0, correction = 0;
    for (const value of values) {
      const next = sum + value;
      correction += Math.abs(sum) >= Math.abs(value) ? (sum - next) + value : (value - next) + sum;
      sum = next;
    }
    const amount = sum + correction;
    const subtotal = values.length && Number.isFinite(amount) ? amount : null;
    return {
      total_live_usd: values.length && values.length === live.length ? subtotal : null,
      verified_live_usd_subtotal: subtotal,
      live_usd_coverage: {verified: values.length, total: live.length},
    };
  }
  function livePledgedText(totals, lang, fmtUSD) {
    const {verified, total} = totals.live_usd_coverage;
    const full = totals.total_live_usd, subtotal = totals.verified_live_usd_subtotal;
    const count = `${verified}/${total}`;
    if (lang === "en") {
      if (full !== null) return `Full total ${fmtUSD(full)} · ${count} projects`;
      return `Verified subtotal ${subtotal === null ? "not updated" : fmtUSD(subtotal)} · ${count} projects; full total not updated`;
    }
    if (full !== null) return `全量合计 ${fmtUSD(full)}，${count} 项`;
    return `已验证小计 ${subtotal === null ? "未更新" : fmtUSD(subtotal)}，${count} 项；全量合计未更新`;
  }
  const api = {livePledgedTotals, livePledgedText};
  root.KSFunds = api;
  if (typeof module !== "undefined") module.exports = api;
})(globalThis);
