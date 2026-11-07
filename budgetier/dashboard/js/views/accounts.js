function accounts() {
  const banked = D.accounts.filter(a => a.type !== "credit" && a.balance !== null), cash = sum(banked, a => a.balance);
  const net = cash + sum(D.accounts.filter(a => a.type === "credit" && a.balance !== null), a => a.balance);
  const notes = D.checks.filter(c => c.level !== "warning");  // warnings are in the bar above
  V.innerHTML = `<div class="tiles">${banked.length ? tile("Cash and savings", money(cash), `${banked.length} of ${D.accounts.filter(a => a.type !== "credit").length} accounts`, tone(cash)) : ""}
      ${owedTile()}${banked.length && owedTile() ? tile("Net of cards", money(net), "cash and savings minus cards", tone(net)) : ""}</div>
    <div class="tools app-only">
      <button class="btn" data-act="export">${icon(SHEET)}Export workbook</button>
      <button class="btn" data-act="folder">${icon(FOLDER)}Open data folder</button>
    </div>
    ${noticeBar(D.checks.filter(c => c.level === "warning"))}
    ${syncCard()}
    <div class="accounts-grid"><div class="card"><h2>Accounts</h2><div class="scroll"><table><thead><tr><th>Account</th><th>Type</th><th>History</th><th class="num">Rows</th><th class="num">Latest balance</th><th class="app-only"></th></tr></thead><tbody>
    ${D.accounts.map(a => `<tr><td><div class="who">${mono(a.bank, CSS(a.type === "credit" ? "c1" : a.type === "savings" ? "c2" : "c0"))}<span>${esc(a.name)}</span></div></td><td class="dim">${a.type === "credit" ? "Credit card" : a.type[0].toUpperCase() + a.type.slice(1)}</td><td class="dim">${a.first ? spanName(a.first, a.last) : "No recent activity"}</td><td class="num">${a.count.toLocaleString()}</td><td class="num ${a.balance === null ? "" : a.type === "credit" ? gain(a.balance) : tone(a.balance)}">${a.balance === null ? '<span class="dim">not set</span>' : cents(a.balance)}${a.calculated ? `<div class="dim">${a.live ? "from your bank" : "calculated"}, ${dName(a.balanceAsOf)}</div>` : ""}</td><td class="app-only"><div class="row-actions"><button class="btn small" data-act="edit" data-id="${esc(a.id)}">Edit</button><button class="btn small danger-text" data-act="drop-account" data-id="${esc(a.id)}">Remove</button></div></td></tr>`).join("")}</tbody></table></div></div>
    <div class="card"><h2>Recent imports</h2><div class="scroll"><table><thead><tr><th>File</th><th>Account</th><th>Covers</th><th class="num">New</th><th class="num">Had</th><th class="app-only"></th></tr></thead><tbody>
    ${D.imports.map(i => `<tr><td class="clip" title="${esc(i.file)}">${esc(i.file)}</td><td class="dim clip">${esc(i.account)}</td><td class="dim">${spanName(i.first, i.last)}</td><td class="num">${i.added}</td><td class="num">${i.duplicates}</td><td class="app-only"><div class="row-actions"><button class="btn small danger-text" data-act="drop-import" data-id="${esc(i.key)}" data-file="${esc(i.file)}" data-rows="${esc(i.added)}">Remove</button></div></td></tr>`).join("")}</tbody></table></div></div></div>
    ${notes.length ? `<div class="card"><h2>Worth checking</h2><p class="sub">Things that could make the numbers wrong.</p>${checksHtml(notes)}</div>` : ""}`;
}

