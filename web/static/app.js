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
    const r = await fetch("/api/audit", { method: "POST", body: fd });
    payload = await r.json();
  } catch {
    payload = await loadSample(); // offline demo path
  }
  await setStage("finish");
  render(normalize(payload));
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
  const cards = [
    ["k-income", "Gross receipts", fmt0(s.gross_receipts), "1099-NEC + income"],
    ["k-deduct", "Total deductible", fmt0(s.total_deductible),
      `${fmt0(s.total_expenses_claimed)} claimed`],
    ["k-net", "Net profit", fmt0(s.estimated_net_profit_schedule_c), "Schedule C bottom line"],
    ["k-tax", "Est. SE tax", fmt0(se.tax), "15.3% — Schedule SE"],
  ];
  $("#kpiRow").innerHTML = cards.map(([c, l, v, sub]) => `
    <div class="kpi ${c}">
      <div class="kpi-label">${l}</div>
      <div class="kpi-value">${v}</div>
      <div class="kpi-sub">${sub}</div>
    </div>`).join("");
}

function renderScheduleC() {
  const lines = Object.entries(state.data.ledger.schedule_c_lines)
    .map(([k, v]) => ({ code: k.replace("Line ", ""), ...v }))
    .sort((a, b) => b.claimed - a.claimed);
  const max = Math.max(...lines.map((l) => l.claimed), 1);
  $("#scLineCount").textContent = `${lines.length} lines`;
  $("#scLines").innerHTML = lines.map((l) => {
    const nd = l.deductible === 0;
    return `
    <div class="sc-line">
      <span class="sc-code">${l.code}</span>
      <div class="sc-bar-wrap">
        <div class="sc-bar-top">
          <span class="sc-bar-label">${l.label}</span>
          <span class="muted">${l.count} item${l.count > 1 ? "s" : ""}</span>
        </div>
        <div class="sc-bar-track">
          <div class="sc-bar-fill ${nd ? "nd" : ""}" style="width:${(l.claimed / max) * 100}%"></div>
        </div>
      </div>
      <div class="sc-amt">${fmt(l.deductible)}<small>of ${fmt(l.claimed)}</small></div>
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
  $("#ledgerBody").innerHTML = rows.map((it, i) => {
    const idx = items.indexOf(it);
    const risk = it.kind === "income" ? "income" : it.risk_level;
    const amtCls = it.kind === "income" ? "income-amt" : "";
    const ded = it.kind === "income" ? "—" : fmt(it.deductible_amount);
    const conf = it.kind === "income" ? "" :
      `<span class="conf-bar"><span class="conf-fill" style="width:${(it.confidence || 0) * 100}%"></span></span>`;
    return `<tr data-i="${idx}">
      <td>${it.date || "—"}</td>
      <td><div class="cell-vendor">${it.vendor || "—"}</div>
          <div class="cell-desc">${it.description || ""}</div></td>
      <td><span class="sc-tag">${it.kind === "income" ? "Income · 1040 Sch C L1" : (it.schedule_c_line || "—")}</span></td>
      <td class="num ${amtCls}">${fmt(it.amount)}</td>
      <td class="num">${ded}</td>
      <td>${conf}</td>
      <td><span class="risk risk-${risk}">${it.kind === "income" ? "income" : it.risk_level}</span></td>
    </tr>`;
  }).join("") || `<tr><td colspan="7" style="text-align:center;color:var(--txt-3);padding:30px">No matching items.</td></tr>`;
  $$("#ledgerBody tr[data-i]").forEach((tr) =>
    tr.addEventListener("click", () => openDrawer(items[+tr.dataset.i])));
}

function renderSE() {
  const s = state.data.ledger.summary;
  const se = computeSE(s.estimated_net_profit_schedule_c);
  const row = (l, v, cls = "") => `<div class="se-row ${cls}"><span class="lbl">${l}</span><span class="val">${v}</span></div>`;
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
    `<p class="muted">No items flagged — clean ledger.</p>`;
}

function renderRespan() {
  const r = state.data.respan || {};
  const panel = $("#respanPanel");
  const tel = r.respan_telemetry || {};
  $("#pillRespan").classList.toggle("off", !tel.enabled);
  if (!r.calls) { panel.innerHTML = `<p class="muted">No telemetry for this run.</p>`; return; }
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
    <div class="muted" style="text-align:center">
      Total ${fmt(r.total_cost_usd).replace("$", "$")} · telemetry ${tel.enabled ? "ON" : "off"}
      ${tel.logs_sent ? `· ${tel.logs_sent} logs sent` : ""}
    </div>`;
}

/* ─────────────── detail drawer ─────────────── */
function openDrawer(it) {
  const isIncome = it.kind === "income";
  const dk = (k, v) => `<div class="dk-row"><span class="k">${k}</span><span class="v">${v}</span></div>`;
  $("#drawerPanel").innerHTML = `
    <div class="drawer-head">
      <div>
        <div class="drawer-vendor">${it.vendor || "—"}</div>
        <span class="risk risk-${isIncome ? "income" : it.risk_level}">${isIncome ? "income" : it.risk_level + " risk"}</span>
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
    ${(it.flags || []).length ? `<div class="drawer-flags"><div class="card-head"><h2>Audit flags</h2></div>
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
