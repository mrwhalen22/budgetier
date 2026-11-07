function spending() {
  const months = rangeMonths(), rows = monthly(selected(), months);
  const cats = catTotals(rows), keep = cats.map(c => c[0]).filter(c => CAT_COLOR[c]);
  const series = keep.map(c => ({name: c, color: color(c), values: rows.map(r => Math.max(r.cats[c] || 0, 0))}));
  const rest = rows.map(r => sum(Object.entries(r.cats).filter(([k]) => !CAT_COLOR[k]), e => Math.max(e[1], 0)));
  if (rest.some(v => v)) series.push({name: "Other", color: CSS("other"), values: rest});
  const shown = months.slice(-12), rowsShown = rows.slice(-12);
  const peak = Math.max(...rowsShown.flatMap(r => Object.values(r.cats)), 1);
  const body = cats.map(([c, total]) => `<tr><td class="link" data-cat="${esc(c)}">${chip(c)}</td>${rowsShown.map(r => {
      const v = r.cats[c] || 0, a = Math.sqrt(Math.max(v, 0) / peak) * 30;
      return `<td class="num cell ${gain(-v)}" data-cat="${esc(c)}" style="background:color-mix(in srgb, var(--accent) ${a.toFixed(0)}%, transparent)">${v ? short(v) : ""}</td>`; }).join("")}
    <td class="num ${gain(-total)}"><b>${money(total)}</b></td></tr>`).join("");
  V.innerHTML = `<div class="card"><h2>Spending by category</h2>${legend(series)}<div class="chart" id="c1"></div></div>
    <div class="card"><h2>Category by month</h2><p class="sub">Darker means more spent${months.length > 12 ? "; showing the latest 12 months, totals cover the full period" : ""}. Refunds are netted out.</p>
    <div class="scroll"><table class="heat"><thead><tr><th>Category</th>${shown.map(m => `<th class="num">${mName(m, false)}</th>`).join("")}<th class="num">Total</th></tr></thead><tbody>${body}</tbody></table></div></div>`;
  bars(document.getElementById("c1"), {months, series: series.slice().reverse(), stacked: true, height: 300});
  drillDown(V);
}

