// Rent would fill the list, and bills are already on Recurring. A one-off from a merchant
// that also bills you stays, because its amount is outside what the bill has ever been.
const isBill = t => D.recurring.some(r => r.kind === "expense" && r.merchant === t.merchant && -t.amt >= r.low && -t.amt <= r.high);
function largest() {
  const tx = selected().filter(t => t.kind === "expense"), shown = S.largeAll ? tx : tx.filter(t => !isBill(t));
  const top = shown.slice().sort((a, b) => a.amt - b.amt).slice(0, 25), hidden = tx.length - shown.length;
  const by = {};
  tx.forEach(t => { const m = by[t.merchant] = by[t.merchant] || {name: t.merchant, value: 0, n: 0, q: t.merchant}; m.value -= t.amt; m.n++; });
  const merchants = Object.values(by).sort((a, b) => b.value - a.value).slice(0, 15);
  V.innerHTML = `<div class="two"><div class="card"><h2>Top merchants</h2><p class="sub">By total spent.</p>${merchants.length ? hbars(merchants, money, CSS("accent")) : '<p class="empty">Nothing in this period.</p>'}</div>
    <div class="card"><h2>Largest single expenses</h2><p class="sub">The 25 biggest in this period${S.largeAll || !hidden ? "" : ", leaving out regular bills"}.<span class="app-only"> Select one to change it.</span></p>
    <div class="controls"><label class="f"><input type="checkbox" id="largeAll" ${S.largeAll ? "checked" : ""}> Include regular bills</label></div><div class="scroll"><table><thead><tr><th>Merchant</th><th>Date</th><th class="num">Amount</th></tr></thead><tbody>
    ${top.map(t => `<tr title="${esc(t.desc)}" data-tx="${t.i}"${rowFocus()}><td class="clip">${who(t.merchant, t.cat)}</td><td class="dim">${dName(t.date)}</td><td class="num">${cents(-t.amt)}</td></tr>`).join("")}</tbody></table>${top.length ? "" : '<p class="empty">Nothing else in this period.</p>'}</div></div></div>`;
  document.getElementById("largeAll").onchange = e => { S.largeAll = e.target.checked; render(); };
  drillDown(V);
}

