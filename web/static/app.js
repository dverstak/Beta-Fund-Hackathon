/* ShoeboxIQ — frontend logic.
 * Renders entirely from the `ledger` contract (see web/adapter.py).
 * Talks to /api/audit + /api/ledger; falls back to bundled samples offline. */

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const fmt = (n) =>
  (n < 0 ? "-$" : "$") +
  Math.abs(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const fmt0 = (n) => "$" + Math.round(n).toLocaleString("en-US");

// ── self-employment tax (Schedule SE), computed client-side from net profit.
// Deterministic IRS formula; shown as an estimate for accountant review.
const SE = { netRate: 0.9235, seRate: 0.153, ssWageBase: 168600, ssRate: 0.124, medRate: 0.029 };
function computeSE(netProfit) {
  const base = Math.max(0, netProfit) * SE.netRate;
  const ss = Math.min(base, SE.ssWageBase) * SE.ssRate;
  const med = base * SE.medRate;
  const tax = ss + med;
  return { base, ss, med, tax, halfDeduction: tax / 2 };
}

const state = { files: [], data: null, filter: "all", query: "" };

/* ─────────────── data loading ─────────────── */
async function health() {
  try {
    const r = await fetch("/api/health");
    const j = await r.json();
    $("#pillBackend").classList.toggle("off", !j.backend_available);
  } catch { /* static hosting — leave as-is */ }
}

async function loadSample() {
  // Try the live endpoint first; fall back to bundled JSON for static hosting.
  try {
    const r = await fetch("/api/ledger");
    if (r.ok) return normalize(await r.json());
  } catch {}
  const [ledger, respan] = await Promise.all([
    fetch("/static/sample_ledger.json").then((r) => r.json()),
    fetch("/static/sample_respan.json").then((r) => r.json()).catch(() => ({})),
  ]);
  return normalize({ ledger, respan });
}

async function runAudit() {
  setStage("start");
  const fd = new FormData();
  state.files.forEach((f) => fd.append("files", f));
  let payload;
  try {
    // Async job pattern: submit -> poll. Avoids gateway 504s on long audits
    // (AgentBox closes long-open connections). See web/server.py.
    const sub = await fetch("/api/jobs", { method: "POST", body: fd });
    const { job_id } = await sub.json();
    payload = await pollJob(job_id);
  } catch {
    payload = await loadSample(); // offline / static-hosting fallback
  }
  await setStage("finish");
  render(normalize(payload));
}

// Poll a job until it finishes. Audits can take 30-120s, so poll patiently.
async function pollJob(jobId, { intervalMs = 2000, timeoutMs = 600000 } = {}) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const r = await fetch(`/api/jobs/${jobId}`);
    if (!r.ok) throw new Error("job not found");
    const j = await r.json();
    if (j.status === "done") return j.result;
    if (j.status === "error") throw new Error(j.error || "audit failed");
    await sleep(intervalMs);
  }
  throw new Error("audit timed out");
}

function normalize(p) {
  // Accept both {ledger, respan} and a bare ledger.
  const ledger = p.ledger || p;
  const respan = p.respan || {};
  return { ledger, respan, source: p.source };
}

/* ─────────────── pipeline animation ─────────────── */
const STEPS = ["ingest", "extract", "categorize", "risk", "ledger"];
function stepEl(s) { return $(`.step[data-step="${s}"]`); }
async function setStage(mode) {
  const pipe = $("#pipeline");
  if (mode === "start") {
    pipe.classList.remove("hidden");
    $("#dropzone").style.opacity = ".4";
    $$(".step").forEach((e) => e.classList.remove("active", "done"));
    for (const s of STEPS) {
      stepEl(s).classList.add("active");
      await sleep(360 + Math.random() * 260);
      stepEl(s).classList.remove("active");
      stepEl(s).classList.add("done");
    }
  } else {
    await sleep(180);
  }
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/* ─────────────── render ─────────────── */
function render(data) {
  state.data = data;
  $("#intake").classList.add("hidden");
  $("#results").classList.remove("hidden");
  window.scrollTo({ top: 0, behavior: "smooth" });
  renderKPIs();
  renderScheduleC();
  renderTable();
  renderSE();
  renderFlagged();
  renderRespan();
}

function renderKPIs() {
  const s = state.data.ledger.summary;
  const se = computeSE(s.estimated_net_profit_schedule_c);
  $("#lhYear").textContent = state.data.ledger.tax_year;
  $("#lhSource").textContent =
    state.data.source === "live" ? "live audit" : "sample data";
  const cards = [
    ["k-income", "Line 1", "Gross receipts", fmt0(s.gross_receipts), "1099-NEC + income"],
    ["k-deduct", "Line 28", "Total deductible", fmt0(s.total_deductible),
      `${fmt0(s.total_expenses_claimed)} claimed`],
    ["k-net", "Line 31", "Net profit", fmt0(s.estimated_net_profit_schedule_c), "business bottom line"],
    ["k-tax", "Sch SE", "Self-employment tax", fmt0(se.tax), "15.3% est."],
  ];
  $("#kpiRow").innerHTML = cards.map(([c, ref, l, v, sub]) => `
    <div class="kpi ${c}">
      <span class="kpi-ref">${ref}</span>
      <div class="kpi-label">${l}</div>
      <div class="kpi-value">${v}</div>
      <div class="kpi-sub">${sub}</div>
    </div>`).join("");
}

// Sort by IRS line order (how a real Schedule C reads); non-deductible last.
function lineOrder(code) {
  if (code === "NONDEDUCTIBLE") return 1e6;
  return parseInt(code, 10) * 10 + (code.replace(/\d/g, "").charCodeAt(0) || 0);
}

function renderScheduleC() {
  const lines = Object.entries(state.data.ledger.schedule_c_lines)
    .map(([k, v]) => ({ code: k.replace("Line ", ""), ...v }))
    .sort((a, b) => lineOrder(a.code) - lineOrder(b.code));
  $("#scLineCount").textContent = `${lines.length} lines · Form 1040`;
  $("#scLines").innerHTML = lines.map((l) => {
    const nd = l.deductible === 0;
    const limited = !nd && Math.abs(l.deductible - l.claimed) > 0.005;
    const codeDisp = l.code === "NONDEDUCTIBLE" ? "N/D" : l.code;
    const amt = nd
      ? `${fmt(l.claimed)} <span class="struck">disallowed</span>`
      : limited
        ? `${fmt(l.deductible)} <span class="struck">${fmt(l.claimed)}</span>`
        : fmt(l.deductible);
    return `
    <div class="formline ${nd ? "is-nd" : ""}">
      <span class="fl-code ${nd ? "nd" : ""}" title="${l.code === "NONDEDUCTIBLE" ? "Non-deductible" : "Schedule C Line " + l.code}">${codeDisp}</span>
      <span class="fl-label">${l.label}</span>
      <span class="fl-count">${l.count}×</span>
      <span class="fl-leader"></span>
      <span class="fl-amt">${amt}</span>
    </div>`;
  }).join("");
}

function renderTable() {
  const items = state.data.ledger.line_items;
  const q = state.query.toLowerCase();
  const rows = items.filter((it) => {
    if (state.filter === "income" && it.kind !== "income") return false;
    if (state.filter === "expense" && it.kind !== "expense") return false;
    if (state.filter === "flagged" && (it.flags || []).length === 0) return false;
    if (q && !`${it.vendor} ${it.description}`.toLowerCase().includes(q)) return false;
    return true;
  });
  $("#ledgerBody").innerHTML = rows.map((it) => {
    const idx = items.indexOf(it);
    const isIncome = it.kind === "income";
    const status = isIncome ? "income" : it.risk_level;
    const statusLabel = isIncome ? "income" : it.risk_level;
    const amtCls = isIncome ? "income-amt" : "";
    const ded = isIncome ? "—" : fmt(it.deductible_amount);
    const conf = isIncome ? "" : confDots(it.confidence || 0);
    const line = isIncome ? "L1 · gross receipts" : (it.schedule_c_line || "—");
    return `<tr data-i="${idx}">
      <td class="cell-date">${it.date || "—"}</td>
      <td><div class="cell-vendor">${it.vendor || "—"}</div>
          <div class="cell-desc">${it.description || ""}</div></td>
      <td><span class="sc-tag">${line}</span></td>
      <td class="num ${amtCls}">${fmt(it.amount)}</td>
      <td class="num">${ded}</td>
      <td>${conf}</td>
      <td><span class="stat stat-${status}">${statusLabel}</span></td>
    </tr>`;
  }).join("") || `<tr><td colspan="7" style="text-align:center;color:var(--ink-3);padding:30px">No matching items.</td></tr>`;
  $$("#ledgerBody tr[data-i]").forEach((tr) =>
    tr.addEventListener("click", () => openDrawer(items[+tr.dataset.i])));
}

function confDots(c) {
  const filled = Math.round(Math.max(0, Math.min(1, c)) * 5);
  return `<span class="conf-dots" title="${(c * 100).toFixed(0)}% confidence">` +
    "●".repeat(filled) + `<span class="o">${"●".repeat(5 - filled)}</span></span>`;
}

function renderSE() {
  const s = state.data.ledger.summary;
  const se = computeSE(s.estimated_net_profit_schedule_c);
  const row = (l, v, cls = "") =>
    `<div class="se-row ${cls}"><span class="lbl">${l}</span><span class="ldr"></span><span class="val">${v}</span></div>`;
  $("#seCalc").innerHTML =
    row("Net profit (Schedule C)", fmt(s.estimated_net_profit_schedule_c)) +
    row("× 92.35% net earnings", fmt(se.base)) +
    row("Social Security (12.4%)", fmt(se.ss)) +
    row("Medicare (2.9%)", fmt(se.med)) +
    row("Self-employment tax", fmt(se.tax), "total") +
    `<div class="se-note">Half of SE tax (${fmt(se.halfDeduction)}) is deductible on
     Form 1040 Schedule 1. SS portion caps at the ${fmt0(SE.ssWageBase)} wage base.
     Estimate only — not tax advice.</div>`;
}

function renderFlagged() {
  const flagged = state.data.ledger.line_items
    .filter((it) => (it.flags || []).length)
    .sort((a, b) => (b.risk_level === "high") - (a.risk_level === "high"));
  $("#flaggedCount").textContent = `${flagged.length} to review`;
  $("#flagged").innerHTML = flagged.map((it) => `
    <div class="flag-item ${it.risk_level}">
      <div class="flag-top">
        <span class="flag-vendor">${it.vendor || "—"}</span>
        <span class="flag-amt">${fmt(it.amount)}</span>
      </div>
      <div class="flag-line">${it.schedule_c_line || it.description || ""}</div>
      <ul class="flag-reasons">${it.flags.map((f) => `<li>${f}</li>`).join("")}</ul>
    </div>`).join("") ||
    `<p class="respan-foot">No items flagged — clean ledger.</p>`;
}

function renderRespan() {
  const r = state.data.respan || {};
  const panel = $("#respanPanel");
  const tel = r.respan_telemetry || {};
  $("#pillRespan").classList.toggle("off", !tel.enabled);
  if (!r.calls) { panel.innerHTML = `<p class="respan-foot">No telemetry for this run.</p>`; return; }
  const profiles = Object.entries(r.by_profile || {});
  const maxCost = Math.max(...profiles.map(([, v]) => v.cost_usd), 1e-9);
  panel.innerHTML = `
    <div class="respan-top">
      <div class="respan-stat"><div class="v">${r.calls}</div><div class="l">LLM calls</div></div>
      <div class="respan-stat"><div class="v">${(r.total_tokens / 1000).toFixed(1)}k</div><div class="l">tokens</div></div>
      <div class="respan-stat"><div class="v">$${r.avg_cost_per_call_usd.toFixed(4)}</div><div class="l">/ document</div></div>
    </div>
    <div class="respan-profiles">
      ${profiles.map(([name, v]) => `
        <div class="respan-prof">
          <span class="name">${name.replace("form_", "").replace("_", " ")}</span>
          <span class="track"><span class="fill" style="width:${(v.cost_usd / maxCost) * 100}%"></span></span>
          <span class="cost">$${v.cost_usd.toFixed(4)}</span>
        </div>`).join("")}
    </div>
    <div class="respan-foot">
      Total ${fmt(r.total_cost_usd)} · telemetry ${tel.enabled ? "ON" : "off"}${tel.logs_sent ? ` · ${tel.logs_sent} logs sent` : ""}
    </div>`;
}

/* ─────────────── detail drawer ─────────────── */
function openDrawer(it) {
  const isIncome = it.kind === "income";
  const dk = (k, v) => `<div class="dk-row"><span class="k">${k}</span><span class="ldr"></span><span class="v">${v}</span></div>`;
  const status = isIncome ? "income" : it.risk_level;
  $("#drawerPanel").innerHTML = `
    <div class="drawer-head">
      <div>
        <div class="drawer-vendor">${it.vendor || "—"}</div>
        <span class="stat stat-${status}">${isIncome ? "income" : it.risk_level + " risk"}</span>
      </div>
      <button class="drawer-close" data-close>×</button>
    </div>
    <div class="drawer-amt">${fmt(it.amount)}</div>
    <div class="dk">
      ${dk("Date", it.date || "—")}
      ${dk("Source file", it.source)}
      ${dk("Document profile", it.profile)}
      ${dk("Schedule C line", isIncome ? "1040 Schedule C · Line 1 (gross receipts)" : (it.schedule_c_line || "—"))}
      ${isIncome ? "" : dk("Deductible %", it.deductible_pct + "%")}
      ${isIncome ? "" : dk("Deductible amount", fmt(it.deductible_amount))}
      ${isIncome ? "" : dk("Confidence", ((it.confidence || 0) * 100).toFixed(0) + "%")}
      ${it.payment_method ? dk("Payment", it.payment_method) : ""}
    </div>
    ${it.rationale ? `<div class="rationale"><span class="lbl">Agent rationale</span>${it.rationale}</div>` : ""}
    ${(it.flags || []).length ? `<div class="drawer-flags"><div class="sheet-head"><h2>Audit flags</h2></div>
      <ul class="flag-reasons">${it.flags.map((f) => `<li>${f}</li>`).join("")}</ul></div>` : ""}
    <div class="rationale" style="margin-top:14px"><span class="lbl">Extracted data</span>
      <div class="raw-json">${escapeJSON(it.raw || {})}</div></div>`;
  $("#drawer").classList.remove("hidden");
  $$("[data-close]", $("#drawer")).forEach((b) => b.onclick = closeDrawer);
}
function closeDrawer() { $("#drawer").classList.add("hidden"); }
function escapeJSON(o) {
  return JSON.stringify(o, null, 2).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
}

/* ─────────────── exports ─────────────── */
function exportFile(kind) {
  const { ledger } = state.data;
  let content, name, type;
  if (kind === "json") {
    content = JSON.stringify(ledger, null, 2); name = "ledger.json"; type = "application/json";
  } else if (kind === "csv") {
    const cols = ["date", "vendor", "description", "kind", "amount", "schedule_c_line",
      "deductible_pct", "deductible_amount", "confidence", "risk_level", "flags"];
    const rows = ledger.line_items.map((it) =>
      cols.map((c) => {
        let v = c === "flags" ? (it.flags || []).join("; ") : it[c];
        v = v == null ? "" : String(v);
        return /[",\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v;
      }).join(","));
    content = [cols.join(","), ...rows].join("\n"); name = "ledger.csv"; type = "text/csv";
  } else {
    content = markdownReport(ledger); name = "audit_report.md"; type = "text/markdown";
  }
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([content], { type }));
  a.download = name; a.click(); URL.revokeObjectURL(a.href);
}
function markdownReport(l) {
  const s = l.summary;
  const se = computeSE(s.estimated_net_profit_schedule_c);
  let out = `# Schedule C Compliance Audit — Tax Year ${l.tax_year}\n\n## Summary\n`;
  out += `- Gross receipts: **${fmt(s.gross_receipts)}**\n`;
  out += `- Total deductible: **${fmt(s.total_deductible)}**\n`;
  out += `- Estimated net profit (Schedule C): **${fmt(s.estimated_net_profit_schedule_c)}**\n`;
  out += `- Estimated self-employment tax (Schedule SE): **${fmt(se.tax)}**\n`;
  out += `- Flagged items: **${s.flagged_items}** (${s.high_risk_items} high-risk)\n\n`;
  out += `## Schedule C Expense Lines\n| Line | Category | # | Claimed | Deductible |\n|---|---|---|---|---|\n`;
  for (const [line, v] of Object.entries(l.schedule_c_lines))
    out += `| ${line} | ${v.label} | ${v.count} | ${fmt(v.claimed)} | ${fmt(v.deductible)} |\n`;
  out += `\n_Not tax advice — for accountant review._\n`;
  return out;
}

/* ─────────────── intake / file handling ─────────────── */
function renderChips() {
  $("#fileChips").innerHTML = state.files.map((f, i) =>
    `<span class="file-chip">${f.name}<span class="x" data-i="${i}">×</span></span>`).join("");
  $$("#fileChips .x").forEach((x) => x.onclick = (e) => {
    e.stopPropagation(); state.files.splice(+x.dataset.i, 1); renderChips();
  });
}
function addFiles(list) { state.files.push(...list); renderChips(); }

/* ─────────────── wiring ─────────────── */
function init() {
  health();
  const dz = $("#dropzone"), input = $("#fileInput");
  dz.onclick = (e) => { if (!e.target.closest(".btn") && !e.target.closest(".x")) input.click(); };
  input.onchange = () => addFiles([...input.files]);
  ["dragover", "dragenter"].forEach((ev) =>
    dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add("drag"); }));
  ["dragleave", "drop"].forEach((ev) =>
    dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.remove("drag"); }));
  dz.addEventListener("drop", (e) => addFiles([...e.dataTransfer.files]));

  $("#runBtn").onclick = runAudit;
  $("#demoBtn").onclick = async () => { await setStage("start"); render(await loadSample()); };

  $("#search").oninput = (e) => { state.query = e.target.value; renderTable(); };
  $("#filterSeg").onclick = (e) => {
    const b = e.target.closest("button"); if (!b) return;
    $$("#filterSeg button").forEach((x) => x.classList.remove("active"));
    b.classList.add("active"); state.filter = b.dataset.f; renderTable();
  };
  $$(".col-export [data-export], [data-export]").forEach((b) =>
    b.addEventListener("click", () => exportFile(b.dataset.export)));
  $("#newAuditBtn").onclick = () => {
    $("#results").classList.add("hidden");
    $("#intake").classList.remove("hidden");
    $("#pipeline").classList.add("hidden");
    $("#dropzone").style.opacity = "1";
    state.files = []; renderChips();
  };
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeDrawer(); });

  // Deep-link straight to the results view: /?demo=1
  if (new URLSearchParams(location.search).get("demo") === "1") {
    loadSample().then(render);
  }
}
init();
