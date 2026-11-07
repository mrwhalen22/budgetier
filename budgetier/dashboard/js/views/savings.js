function savings() {
  const months = rangeMonths(), tx = selected(), rows = monthly(tx, months);
  const done = completed(rows), inc = sum(done, r => r.income), sp = sum(done, r => r.spending);
  const scope = billed(rows), total = sum(scope, r => r.income - r.spending);
  const SAVED = "Savings & Investing";
  const moved = sum(tx.filter(t => t.cat === SAVED || (t.kind === "transfer" && ACCT[t.acct].type === "savings")), t => t.cat === SAVED ? -t.amt : t.amt);
  const savers = D.accounts.filter(a => a.type === "savings" && S.accts.has(a.index));
  const held = savers.filter(a => a.balance !== null);
  const nets = scope.map(r => Math.round((r.income - r.spending) * 100) / 100);
  let run = 0; const cumulative = nets.map(n => run += n);
  const withBal = D.accounts.filter(a => S.accts.has(a.index) && Object.keys(a.balances).length);
  const balSeries = withBal.slice(0, 8).map((a, i) => ({name: a.name, color: CSS("c" + i), values: months.map(m => m in a.balances ? a.balances[m] : null)}));
  V.innerHTML = `<div class="tiles">${tile("Kept this period", money(total), "income minus spending" + (scope.length < rows.length ? ", from " + mName(scope[0].month) : ""), tone(total))}
      ${tile("Savings rate", inc > 0 ? Math.round((inc - sp) / inc * 100) + "%" : "n/a", periodNote(rows) ? "complete months" : "", tone(inc - sp))}
      ${tile("Moved to savings and investing", money(moved), "net of withdrawals", tone(moved))}
      ${held.length ? tile("Savings balance", money(sum(held, a => a.balance)), "latest known balance", tone(sum(held, a => a.balance))) : ""}</div>
    <div class="charts pair"><div class="card"><h2>Kept each month</h2><p class="sub">Income minus spending. Red months spent more than came in.${scope.length < rows.length ? " Months before your checking history are left out." : ""}</p><div class="chart" id="c1"></div></div>
    <div class="card"><h2>Running total kept</h2><div class="chart" id="c2"></div></div></div>
    ${balSeries.length ? `<div class="card"><h2>Account balances</h2><p class="sub">Month-end balances. Exports supply some; the rest are calculated from a balance you entered.</p>${legend(balSeries)}<div class="chart" id="c3"></div></div>` : ""}`;
  bars(document.getElementById("c1"), {months: scope.map(r => r.month), series: [{name: "Kept", colorFor: v => v < 0 ? CSS("bad") : CSS("income"), values: nets}]});
  lines(document.getElementById("c2"), {months: scope.map(r => r.month), series: [{name: "Running total", color: CSS(run < 0 ? "bad" : "income"), values: cumulative}]});
  if (balSeries.length) lines(document.getElementById("c3"), {months, series: balSeries});
}

