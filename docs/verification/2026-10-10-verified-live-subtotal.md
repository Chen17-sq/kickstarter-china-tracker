# Verified live fundraising subtotal — 2026-10-10

## Scope and evidence

Reviewed against main `64639daf10c1e998f29fec3052f0370cd478fa33`.
The six open PRs at review time were dependency upgrades; none implemented this change.
The previously mentioned `/workspace/scratch/1df2b22fa195/` patch and verification
files were unavailable in this environment and were not reused.

The snapshot generated at `2026-10-10T03:31:42Z` contains 132 live projects. At
verification time, 131 have valid fresh USD observations. Their computed subtotal
is **$17,017,406.82772803** (displayed **$17.02M**). Silas All in
(`/projects/fuci/silas-all-in`) has no valid current observation and remains in the
132-project denominator. Its old amount is excluded. These figures are evidence
for this snapshot, not constants in the implementation.

Before: complete live total is unavailable, hiding the verified 131-project amount.
After: `total_live_usd: null`, `verified_live_usd_subtotal: 17017406.82772803`,
`live_usd_coverage: {verified: 131, total: 132}`.

Chinese: `已验证小计 $17.02M，131/132 项；全量合计未更新`.
English: `Verified subtotal $17.02M · 131/132 projects; full total not updated`.

The shared Python aggregate feeds API, Markdown, message summaries and HTML/plain
email rendering. Both web pages use the same JavaScript aggregate, with Python/
JavaScript parity tests. No source observations, project statuses, historical
snapshots, generated production artifacts, collection code, workflows or delivery
switches are modified. Full totals remain null with incomplete coverage. Verified
zero is counted; missing coverage never becomes zero. Evaluation uses the original
observation time and a 30-hour freshness limit, not the snapshot timestamp.

## Automated verification

Run from the repository root:

```sh
.venv/bin/python -m pytest scraper/tests/ -q
.venv/bin/ruff check scraper/
node subscribe-worker/test_worker.mjs
node --check site/funds.js
node --check site/app.js
git diff --check
```

Local results: **380 pytest passed**, **Ruff passed**, **17 Worker tests passed**,
Worker esbuild bundle passed, JavaScript syntax checks and diff whitespace checks
passed. The first offline esbuild attempt lacked a cached package; rerunning with
an isolated temporary npm cache completed successfully.

The new tests cover partial/full coverage, stale and legacy observations, true
zero, no valid values/no live projects, invalid types, non-finite/overflow values,
wrong currency, future/expired/naive/invalid times, exact freshness boundary,
timezone offsets, recovery and rerun aging. Node executes the actual shared web
helper against the same fixtures. Isolated API/report/email tests prohibit socket
connections, assert no output files are written, and verify source data is unchanged.
They also exposed and fixed report rendering without any prelaunch projects and
sorting invalid pledged amounts.

## Isolated preview

A copy of `site/` and the unchanged `data/projects.json` was placed under
`/private/tmp/tracker-subtotal-preview`. Pure `build_payload`, `make_report`,
`build_html` and `build_plaintext` renderers wrote previews only there. No notifier
entrypoint, archive writer, collector, recipient lookup or sending method ran.
The local preview server binds only `127.0.0.1:8876`.

The public static API reflects freshness at generation time; a consumer retaining
it must evaluate the observation timestamps again before calling values fresh.
Web pages evaluate freshness at rendering time. This change cannot reconstruct
missing historical observations or verify source collection; it only reports the
available evidence without losing valid partial coverage.
