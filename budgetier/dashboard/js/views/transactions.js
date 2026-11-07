const rowFocus = () => document.body.classList.contains("in-app") ? ' tabindex="0"' : "";
function transactions() {
  V.innerHTML = `<div class="card"><div class="controls"><input type="search" id="q" aria-label="Search transactions" placeholder="Search merchant or description" value="${esc(S.txq)}">
      <select id="cat" aria-label="Category"><option value="">All categories</option><option${S.txcat === "Transfer" ? " selected" : ""}>Transfer</option><option${S.txcat === "Savings & Investing" ? " selected" : ""}>Savings &amp; Investing</option><option${S.txcat === "Income" ? " selected" : ""}>Income</option>
      ${D.categories.filter(c => c !== "Income").map(c => `<option${S.txcat === c ? " selected" : ""}>${esc(c)}</option>`).join("")}</select>
      <select id="kind" aria-label="Kind">${[["", "All kinds"], ["expense", "Expenses"], ["refund", "Refunds"], ["estimate", "Estimated"], ["income", "Income"], ["transfer", "Transfers"]].map(([v, n]) => `<option value="${v}"${S.txkind === v ? " selected" : ""}>${n}</option>`).join("")}</select>
      <button class="btn" id="clearTx" type="button">Clear filters</button>
      </div><div class="dim" id="count"></div><p class="sub app-only">Select a row to change it, or everything like it.</p><div class="scroll" id="tx"></div></div>`;
  const q = document.getElementById("q");
  q.oninput = () => { S.txq = q.value; S.txshow = 200; txTable(); };
  document.getElementById("cat").onchange = e => { S.txcat = e.target.value; S.txshow = 200; txTable(); };
  document.getElementById("kind").onchange = e => { S.txkind = e.target.value; S.txshow = 200; txTable(); };
  document.getElementById("clearTx").onclick = () => { Object.assign(S, {txq: "", txcat: "", txkind: "", txshow: 200}); transactions(); };
  txTable();
}
function txTable() {
  const q = S.txq.toLowerCase();
  document.getElementById("clearTx").hidden = !(S.txq || S.txcat || S.txkind);
  const list = selected().filter(t => (!S.txcat || t.cat === S.txcat) && (!S.txkind || t.kind === S.txkind) && (!q || (t.desc + " " + t.merchant).toLowerCase().includes(q)));
  const key = {date: t => t.date, merchant: t => t.merchant.toLowerCase(), cat: t => t.cat, amt: t => t.amt, acct: t => ACCT[t.acct].name}[S.txsort];
  list.sort((a, b) => (key(a) < key(b) ? -1 : key(a) > key(b) ? 1 : 0) * S.txdir);
  document.getElementById("count").textContent = `${list.length.toLocaleString()} transactions, net ${cents(sum(list, t => t.amt))}`;
  const th = (k, n, c = "") => {
    const on = S.txsort === k;
    return `<th class="${c}"${on ? ` aria-sort="${S.txdir > 0 ? "ascending" : "descending"}"` : ""}><button type="button" data-sort="${k}">${n}${on ? `<span aria-hidden="true">${S.txdir > 0 ? " ▲" : " ▼"}</span>` : ""}</button></th>`;
  };
  const box = document.getElementById("tx");
  box.innerHTML = `<table><thead><tr>${th("date", "Date")}${th("merchant", "Merchant")}${th("cat", "Category")}${th("acct", "Account")}${th("amt", "Amount", "num")}</tr></thead><tbody>
    ${list.slice(0, S.txshow).map(t => `<tr title="${esc(t.desc)}" data-tx="${t.i}"${rowFocus()}><td class="dim">${dName(t.date)}</td><td class="clip">${who(t.merchant, t.cat)}</td><td>${chip(t.cat)}${t.edited ? ' <span class="badge">edited</span>' : ""}</td><td class="dim clip">${esc(ACCT[t.acct].name)}</td><td class="num ${gain(t.amt)}">${t.amt > 0 ? "+" : ""}${cents(t.amt)}</td></tr>`).join("")}</tbody></table>
    ${list.length > S.txshow ? '<button class="btn more" id="more">Show more</button>' : ""}${list.length ? "" : '<p class="empty">No transactions match.</p>'}`;
  box.querySelectorAll("[data-sort]").forEach(n => n.onclick = () => {
    if (S.txsort === n.dataset.sort) S.txdir *= -1; else { S.txsort = n.dataset.sort; S.txdir = n.dataset.sort === "date" ? -1 : 1; }
    const again = n.dataset.sort;
    txTable();
    box.querySelector(`[data-sort="${again}"]`).focus(); });
  const more = document.getElementById("more");
  if (more) more.onclick = () => { S.txshow += 500; txTable(); };
}

