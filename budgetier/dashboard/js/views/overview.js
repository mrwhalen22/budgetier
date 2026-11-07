// What the charts' averages can't say: how the newest month is going so far.
function thisMonth() {
  if (rangeMonths().length === 1) return "";
  const month = MONTHS[MONTHS.length - 1], last = MONTHS[MONTHS.length - 2], open = month === D.partialMonth;
  const mine = TX.filter(t => S.accts.has(t.acct)), day = D.end.slice(8), [now] = monthly(mine, [month]);
  const stats = [stat(open ? "Spent so far" : "Spent", money(now.spending), ""), stat(open ? "Income so far" : "Income", money(now.income), "", gain(now.income))];
  if (open && last && hasBills(last)) {
    const [then] = monthly(mine.filter(t => t.date.slice(8) <= day), [last]), gap = now.spending - then.spending;
    stats.push(stat(`Compared with ${mName(last, false)}`, `${money(Math.abs(gap))} ${gap > 0 ? "more" : "less"}`, `by day ${Number(day)} of the month`));
  }
  const due = open ? activeRecurring().filter(r => r.next > D.end && r.next.startsWith(month)) : [];
  if (due.length) stats.push(stat("Bills still to come", money(sum(due, r => r.amount)), `${due.length} expected this month`));
  const plan = B.months.find(m => m.month === month);
  if (plan && B.targets.length && S.accts.size === D.accounts.length) {
    const left = sum(B.targets, t => (plan.targets[t.category] || 0) - (plan.spent[t.category] || 0));
    stats.push(stat(left < 0 ? "Over budget" : "Left in budgets", money(Math.abs(left)), `${B.targets.length} budget${B.targets.length === 1 ? "" : "s"}`, left < 0 ? "neg" : "pos"));
  }
  return `<section class="card now"><div class="now-head"><div><h2>${esc(mName(month))}${open ? " so far" : ""}</h2><p class="dim">Data through ${esc(dName(D.end))}.</p></div><button class="btn small" data-act="see-month" data-month="${month}">See this month</button></div><div class="now-stats">${stats.map(s => `<div>${s}</div>`).join("")}</div></section>`;
}

function overview() {
  const months = rangeMonths(), rows = monthly(selected(), months), done = completed(rows), one = rows.length === 1;
  const inc = sum(done, r => r.income) / done.length, sp = sum(done, r => r.spending) / done.length;
  const rate = inc > 0 ? (inc - sp) / inc : null, rec = sum(activeRecurring(), r => r.per_month);
  const note = periodNote(rows), avg = one ? "" : "Avg. monthly ";
  const months_ = new Set(done.map(r => r.month));
  const est = -sum(selected().filter(t => t.kind === "estimate" && months_.has(t.month)), t => t.amt) / done.length;
  const warns = D.checks.filter(c => c.level === "warning");
  const peak = Math.max(...rows.map(r => r.spending), 1), spent = inc > 0 ? Math.min(sp / inc, 1) : 1, kept = inc - sp;
  const spark = rows.slice(-18).map(r => `<i class="${months_.has(r.month) ? "" : "off"}" style="height:${Math.max(r.spending / peak * 100, 2).toFixed(1)}%"></i>`).join("");
  V.innerHTML = `${noticeBar(warns)}${thisMonth()}
    <div class="lead"><section class="hero">
      <div><div class="k">${avg ? avg + "spending" : "Spending"}</div><div class="big">${money(sp)}</div>
        <div class="s">${esc((est > 0 ? `Includes ${money(est)} estimated from card payments. ` : "") + (note ? note[0].toUpperCase() + note.slice(1) + "." : ""))}</div></div>
      <div class="spark" aria-hidden="true">${one ? "" : spark}</div>
      <div class="flow">
        <div class="flow-bar"><span class="spent" style="flex:${spent.toFixed(3)}"></span>${kept > 0 ? `<span class="kept" style="flex:${(1 - spent).toFixed(3)}"></span>` : ""}</div>
        <div class="flow-key"><span>Of every dollar earned</span><span><b class="${kept < 0 ? "neg" : ""}">${Math.round(spent * 100)}% spent</b>${kept > 0 ? ` &nbsp;·&nbsp; <b class="b">${100 - Math.round(spent * 100)}% kept</b>` : ""}</span></div>
      </div>
    </section>
    <div class="tiles">
      ${tile(avg ? avg + "income" : "Income", money(inc), one ? "" : "same months as spending", "pos")}
      ${tile("Savings rate", rate === null ? "n/a" : Math.round(rate * 100) + "%", money(inc - sp) + (one ? " kept" : " kept per month"), tone(inc - sp))}
      ${tile("Recurring bills", money(rec) + "/mo", activeRecurring().length + " active")}
      ${owedTile()}
    </div></div>
    <div class="split">
      <div class="card"><h2>Income and spending</h2>${legend([{name: "Income", color: CSS("income")}, {name: "Spending", color: CSS("spending")}])}<div class="chart" id="c1"></div></div>
      <div class="card"><h2>Where it went</h2><p class="sub">Select a category to see its transactions.</p><div id="cats"></div></div>
    </div>`;
  bars(document.getElementById("c1"), {months, series: [
    {name: "Income", color: CSS("income"), values: rows.map(r => r.income)},
    {name: "Spending", color: CSS("spending"), values: rows.map(r => r.spending)}]});
  const cats = catTotals(rows).filter(c => c[1] > 0);
  document.getElementById("cats").innerHTML = cats.length ? hbars(cats.slice(0, 8).map(([name, value]) => ({name, value, cat: name, color: color(name)})), money, CSS("accent")) : '<p class="empty">No spending in this period.</p>';
  drillDown(V);
}

