function recurring() {
  const list = D.recurring.filter(r => S.recAll || r.active);
  const bills = list.filter(r => r.kind === "expense" && r.active), income = list.filter(r => r.kind === "income" && r.active);
  const subs = bills.filter(r => r.category === "Subscriptions");
  const row = r => {
    const change = r.price_change ? `<span class="${(r.price_change > 0) === (r.kind === "expense") ? "up" : "down"}">${r.price_change > 0 ? "▲ up" : "▼ down"} ${cents(Math.abs(r.price_change))}</span>` : "";
    return `<tr class="link" data-q="${esc(r.merchant)}"><td><div class="who">${mono(r.merchant, color(r.category))}<span>${esc(r.merchant)}</span>${r.active ? "" : '<span class="badge">stopped</span>'}</div></td><td>${chip(r.category)}</td><td class="dim">${r.cadence}</td>
      <td class="num ${r.kind === "income" ? "pos" : ""}">${r.variable ? "~" : ""}${cents(r.amount)}</td><td class="num ${r.kind === "income" ? "pos" : ""}">${cents(r.per_month)}</td><td>${change}</td><td class="dim">${dName(r.last)}</td><td class="dim">${r.active ? dName(r.next) : ""}</td><td class="dim clip">${esc(r.account)}</td></tr>`; };
  const table = rows => rows.length ? `<div class="scroll"><table><thead><tr><th>Name</th><th>Category</th><th>Every</th><th class="num">Amount</th><th class="num">Monthly</th><th>Change</th><th>Last</th><th>Next</th><th>Account</th></tr></thead><tbody>${rows.map(row).join("")}</tbody></table></div>` : '<p class="empty">None found.</p>';
  V.innerHTML = `<div class="tiles">${tile("Recurring bills", money(sum(bills, r => r.per_month)) + "/mo", money(sum(bills, r => r.per_month) * 12) + " a year")}
      ${tile("Subscriptions", money(sum(subs, r => r.per_month)) + "/mo", subs.length + " active")}
      ${tile("Regular income", money(sum(income, r => r.per_month)) + "/mo", income.length + " source" + (income.length === 1 ? "" : "s"), "pos")}</div>
    <div class="controls"><label class="f"><input type="checkbox" id="recAll" ${S.recAll ? "checked" : ""}> Include stopped payments</label></div>
    <div class="card"><h2>Bills and subscriptions</h2><p class="sub">~ means the amount varies. Found from the full history, so the period filter doesn't apply here.</p>${table(list.filter(r => r.kind === "expense"))}</div>
    <div class="card"><h2>Regular income</h2>${table(list.filter(r => r.kind === "income"))}</div>`;
  document.getElementById("recAll").onchange = e => { S.recAll = e.target.checked; render(); };
  drillDown(V);
}

