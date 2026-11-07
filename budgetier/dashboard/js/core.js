"use strict";
const D = JSON.parse(document.getElementById("data").textContent);
const TX = D.txns.map((t, i) => ({i, date: t[0], month: t[0].slice(0, 7), acct: t[1], desc: t[2], merchant: t[3], cat: t[4], kind: t[5], amt: t[6], edited: !!t[7]}));
const ACCT = {}; D.accounts.forEach(a => ACCT[a.index] = a);
const TABS = ["Overview", "Spending", "Budgets", "Recurring", "Largest", "Savings", "Transactions", "Rules", "Accounts", "Help"];
const icon = p => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${p}</svg>`;
const ICONS = {
  Overview: '<rect x="3.5" y="3.5" width="7" height="8" rx="1.5"/><rect x="13.5" y="3.5" width="7" height="5" rx="1.5"/><rect x="13.5" y="11.5" width="7" height="9" rx="1.5"/><rect x="3.5" y="14.5" width="7" height="6" rx="1.5"/>',
  Spending: '<circle cx="12" cy="12" r="8.5"/><path d="M12 3.5V12l6 6"/>',
  Budgets: '<circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="4.5"/><path d="M12 12h.01"/>',
  Recurring: '<path d="M4 11a8 8 0 0 1 13.7-5.2L20 8"/><path d="M20 3.5V8h-4.5"/><path d="M20 13a8 8 0 0 1-13.7 5.2L4 16"/><path d="M4 20.5V16h4.5"/>',
  Largest: '<path d="M4 20h16"/><path d="M7 16V10"/><path d="M12 16V5"/><path d="M17 16v-3"/>',
  Savings: '<path d="M3.5 17 9.5 11l4 4 7-8"/><path d="M15.5 7h5v5"/>',
  Accounts: '<rect x="3" y="5.5" width="18" height="13" rx="2.5"/><path d="M3 10h18"/><path d="M7 15h3"/>',
  Rules: '<path d="M4 7h10"/><path d="M18 7h2"/><circle cx="16" cy="7" r="2"/><path d="M4 17h2"/><path d="M10 17h10"/><circle cx="8" cy="17" r="2"/>',
  Help: '<circle cx="12" cy="12" r="8.5"/><path d="M9.5 9.5a2.5 2.5 0 1 1 3.6 2.2c-.7.4-1.1.9-1.1 1.8"/><path d="M12 16.8h.01"/>',
  Transactions: '<path d="M8 6h12"/><path d="M8 12h12"/><path d="M8 18h12"/><path d="M4 6h.01"/><path d="M4 12h.01"/><path d="M4 18h.01"/>',
};
const SUN = '<circle cx="12" cy="12" r="4"/><path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6 7 7M17 17l1.4 1.4M5.6 18.4 7 17M17 7l1.4-1.4"/>';
const ALERT = '<path d="M12 4 3 19.5h18L12 4Z"/><path d="M12 10v4.5"/><path d="M12 17.2h.01"/>';
const PLUS = '<path d="M12 5v14"/><path d="M5 12h14"/>';
const FOLDER = '<path d="M3.5 7.5a2 2 0 0 1 2-2h4l2 2.5h7a2 2 0 0 1 2 2v7.5a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2Z"/>';
const SHEET = '<rect x="4" y="3.5" width="16" height="17" rx="2"/><path d="M4 9.5h16"/><path d="M4 15h16"/><path d="M10 9.5v11"/>';
const INFO = '<circle cx="12" cy="12" r="8.5"/><path d="M12 11v5"/><path d="M12 8h.01"/>';
const S = {tab: "Overview", range: "12", accts: new Set(D.accounts.map(a => a.index)), txq: "", txcat: "", txkind: "", txsort: "date", txdir: -1, txshow: 200, recAll: false, largeAll: false};
const CSS = n => `var(--${n})`;
const CAT_COLOR = {}; D.categories.slice(0, 8).forEach((c, i) => CAT_COLOR[c] = CSS("c" + i));
const color = c => CAT_COLOR[c] || CSS("other");

const esc = s => String(s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const money = (n, d = 0) => (n < 0 ? "-" : "") + "$" + Math.abs(n).toLocaleString("en-US", {minimumFractionDigits: d, maximumFractionDigits: d});
const cents = n => money(n, 2);
const tone = n => n < 0 ? "neg" : n > 0 ? "pos" : "";
const gain = n => n > 0 ? "pos" : "";  // ordinary spending isn't a problem, so it isn't red
const short = n => { const a = Math.abs(n); return (n < 0 ? "-$" : "$") + (a >= 1000 ? (a / 1000).toFixed(1).replace(/\.0$/, "") + "k" : Math.round(a)); };
const mName = (m, y = true) => new Date(+m.slice(0, 4), +m.slice(5) - 1, 1).toLocaleString("en-US", y ? {month: "short", year: "numeric"} : {month: "short"});
const spanName = (a, b) => `${mName(a.slice(0, 7))} to ${mName(b.slice(0, 7))}`;
const dName = d => new Date(+d.slice(0, 4), +d.slice(5, 7) - 1, +d.slice(8)).toLocaleDateString("en-US", {month: "short", day: "numeric", year: "numeric"});

function allMonths() {
  const first = TX.length ? TX[0].month : D.end.slice(0, 7), out = [];
  let [y, m] = first.split("-").map(Number);
  const end = D.end.slice(0, 7);
  for (;;) { const k = `${y}-${String(m).padStart(2, "0")}`; out.push(k); if (k >= end) break; if (++m > 12) { m = 1; y++; } }
  return out;
}
const MONTHS = allMonths();

function rangeMonths() {
  const r = S.range;
  if (r === "all") return MONTHS;
  if (/^\d+$/.test(r)) return MONTHS.slice(-Number(r));
  if (r.length === 4) return MONTHS.filter(m => m.startsWith(r));
  return [r];
}
function rangeLabel() { const o = document.getElementById("range"); return o.options[o.selectedIndex].text; }

function selected() {
  const ms = new Set(rangeMonths());
  return TX.filter(t => ms.has(t.month) && S.accts.has(t.acct));
}
const SPENDING = new Set(["expense", "refund", "estimate"]);
function monthly(tx, months) {
  const out = {}; months.forEach(m => out[m] = {month: m, income: 0, spending: 0, cats: {}});
  for (const t of tx) {
    const m = out[t.month]; if (!m) continue;
    if (t.kind === "income") m.income += t.amt;
    else if (SPENDING.has(t.kind)) { m.spending -= t.amt; m.cats[t.cat] = (m.cats[t.cat] || 0) - t.amt; }
  }
  return months.map(k => out[k]);
}
// Before checking history starts, a month has card spending but no rent or income.
// Averages skip those, and the month still in progress, or they read far too low.
function hasBills(m) {
  const checking = D.accounts.some(a => a.type === "checking" && S.accts.has(a.index));
  return !checking || !D.coverageFrom || m >= D.coverageFrom;
}
function completed(rows) { const c = rows.filter(r => r.month !== D.partialMonth && hasBills(r.month)); return c.length ? c : rows; }
function billed(rows) { const c = rows.filter(r => hasBills(r.month)); return c.length ? c : rows; }
const sum = (a, f) => a.reduce((s, x) => s + f(x), 0);

