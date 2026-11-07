/* ---------- views ---------- */
const V = document.getElementById("view");
const stat = (k, v, s, t = "") => `<div class="k">${esc(k)}</div><div class="v ${t}">${esc(v)}</div>${s ? `<div class="s">${esc(s)}</div>` : ""}`;
function tile(k, v, s, t = "") { return `<div class="tile">${stat(k, v, s, t)}</div>`; }
function checksHtml(list) { return list.map(c => `<div class="banner ${c.level === "warning" ? "warn" : "info"}">${icon(c.level === "warning" ? ALERT : INFO)}<div><b>${esc(c.title)}</b>${esc(c.detail)}</div></div>`).join(""); }
function noticeBar(list) {
  if (!list.length) return "";
  const n = list.length;
  return `<details class="banner warn"><summary>${icon(ALERT)}${n} thing${n === 1 ? "" : "s"} to check<span>${esc(list[0].title)}</span><em class="open"></em></summary>
    <div class="banner-list">${list.map(c => `<p><b>${esc(c.title)}</b>${esc(c.detail)}</p>`).join("")}</div></details>`;
}
function catTotals(rows) {
  const c = {}; rows.forEach(r => Object.entries(r.cats).forEach(([k, v]) => c[k] = (c[k] || 0) + v));
  return Object.entries(c).sort((a, b) => b[1] - a[1]);
}
// A negative card balance is money owed. Cards with no balance entered are left out.
function owedTile() {
  const cards = D.accounts.filter(a => a.type === "credit"), known = cards.filter(a => a.balance !== null);
  if (!known.length) return "";
  const owed = sum(known, a => a.balance), missing = cards.length - known.length;
  return tile("Owed on cards", money(owed), missing ? `${missing} card${missing === 1 ? "" : "s"} not set` : "calculated from what you entered", gain(owed));
}
function activeRecurring() { return D.recurring.filter(r => r.active && r.kind === "expense"); }
function periodNote(rows) {
  if (rows.length === 1) return "";
  const n = completed(rows).length, early = rows.filter(r => !hasBills(r.month)).length;
  return `average of ${n} complete month${n === 1 ? "" : "s"}` + (early ? `; ${early} earlier skipped, no checking history` : "");
}

