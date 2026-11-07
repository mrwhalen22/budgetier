/* ---------- budgets ---------- */
const UNBUDGETED = ["Income", "Transfer", "Savings & Investing", "Card Payments (no detail)", "Uncategorized"];
const B = D.budgets || {targets: [], months: []};
const budgetChoices = () => [...new Set([...(D.allCategories || []), ...D.categories])].filter(c => !UNBUDGETED.includes(c) && !B.targets.some(t => t.category === c)).sort();
const completeMonths = () => { const c = B.months.filter(m => !m.partial).slice(-6); return c.length ? c : B.months; };
const budgetGoal = t => t.mode === "percent" ? `${t.value}% of income` : `${money(t.value)} a month`;
function budgetRow(t, m) {
  const goal = m.targets[t.category] || 0, spent = m.spent[t.category] || 0, left = goal - spent;
  const used = goal > 0 ? spent / goal : spent > 0 ? 2 : 0, state = used > 1 ? "over" : used >= .9 ? "near" : "";
  return `<div class="budget"><div>${chip(t.category)}<div class="goal">${esc(budgetGoal(t))}</div></div>
    <div><div class="left ${left < 0 ? "neg" : "pos"}">${money(Math.abs(left))} ${left < 0 ? "over" : "left"}</div><div class="used">${money(spent)} of ${money(goal)}</div></div>
    <div class="meter" role="img" aria-label="${Math.round(used * 100)}% used"><i class="${state}" style="width:${Math.min(Math.max(used, 0), 1) * 100}%"></i></div>
    <div class="row-actions"><button class="btn small" data-act="budget-edit" data-cat-name="${esc(t.category)}">Edit</button><button class="btn small danger-text" data-act="budget-delete" data-cat-name="${esc(t.category)}">Remove</button></div></div>`;
}
function budgetHistory(months) {
  return `<div class="card"><h2>Recent months</h2><p class="sub">What you spent in each category. Amounts in red went over that month's target.</p>
    <div class="scroll"><table><thead><tr><th>Category</th>${months.map(m => `<th class="num">${mName(m.month, false)}</th>`).join("")}</tr></thead><tbody>
    ${B.targets.map(t => `<tr><td>${chip(t.category)}</td>${months.map(m => { const v = m.spent[t.category] || 0; return `<td class="num ${v > (m.targets[t.category] || 0) ? "missed" : ""}">${v ? short(v) : ""}</td>`; }).join("")}</tr>`).join("")}
    </tbody></table></div></div>`;
}
function budgets() {
  const add = `<button class="btn primary" data-act="budget-new">${icon(PLUS)}Add budget</button>`;
  if (!B.targets.length) {
    V.innerHTML = `<div class="card"><h2>Set your first budget</h2><p class="sub">Choose a category and give it a monthly target: a dollar amount, or a percent of your income. Budgetier shows what's left each month.</p>${add}</div>`;
    return;
  }
  const m = B.months.find(x => x.month === S.budgetMonth) || B.months[B.months.length - 1];
  const goal = sum(B.targets, t => m.targets[t.category] || 0), spent = sum(B.targets, t => m.spent[t.category] || 0), left = goal - spent;
  const budgeted = new Set(B.targets.map(t => t.category));
  const other = sum(Object.entries(m.spent).filter(([c]) => !budgeted.has(c)), e => e[1]);
  const share = t => (m.spent[t.category] || 0) / (m.targets[t.category] || 1);
  const rows = B.targets.slice().sort((a, b) => share(b) - share(a));
  const uses = B.targets.some(t => t.mode === "percent");
  const note = m.partial ? `Month in progress, data through ${dName(D.end)}.${uses ? ` Percent targets use your recent income, ${money(m.base)} a month, until the month is complete.` : ""}`
    : uses ? `Percent targets use this month's income of ${money(m.base)}.` : "";
  V.innerHTML = `<div class="budget-head"><select id="budgetMonth" aria-label="Month">${B.months.slice().reverse().map(x => `<option value="${x.month}"${x === m ? " selected" : ""}>${mName(x.month)}</option>`).join("")}</select>${add}</div>
    <div class="tiles">
      ${tile("Budgeted", money(goal), m.base > 0 ? `${Math.round(goal / m.base * 100)}% of income` : "")}
      ${tile("Spent on budgets", money(spent), "")}
      ${tile(left < 0 ? "Over budget" : "Left to spend", money(Math.abs(left)), m.partial ? "so far this month" : "", left < 0 ? "neg" : "pos")}
      ${tile("Not budgeted", money(other), "other spending this month")}
    </div>
    <div class="card"><h2>${esc(mName(m.month))}</h2>${note ? `<p class="sub">${esc(note)}</p>` : ""}${rows.map(t => budgetRow(t, m)).join("")}</div>
    ${budgetHistory(B.months.slice(-6))}`;
  document.getElementById("budgetMonth").onchange = e => { S.budgetMonth = e.target.value; render(); };
}
function budgetForm(t) {
  const cats = t ? [t.category] : budgetChoices();
  if (!cats.length) return toast("Every category already has a budget.");
  showModal(t ? "Edit budget" : "Add budget", "Targets apply to every month, including past ones.", `<div class="fields">
      <label class="field full">Category<select id="bCat"${t ? " disabled" : ""}>${cats.map(c => `<option>${esc(c)}</option>`).join("")}</select></label>
      <label class="field">Target type<select id="bMode"><option value="amount"${t && t.mode === "amount" ? " selected" : ""}>Dollar amount</option><option value="percent"${t && t.mode === "percent" ? " selected" : ""}>Percent of income</option></select></label>
      <label class="field" id="bLabel"><span></span><input id="bValue" value="${t ? t.value : ""}" inputmode="decimal" autocomplete="off"></label>
    </div><div class="panel" id="bPreview" aria-live="polite"></div>`,
    `<button class="btn" data-modal="close">Cancel</button><button class="btn primary" data-modal="budget-save">Save</button>`);
  ["bCat", "bMode"].forEach(id => document.getElementById(id).onchange = budgetPreview);
  document.getElementById("bValue").oninput = budgetPreview;
  budgetPreview();
}
function budgetPreview() {
  const v = id => document.getElementById(id).value, mode = v("bMode"), months = completeMonths();
  document.querySelector("#bLabel span").textContent = mode === "percent" ? "Percent of income" : "Dollars a month";
  const n = months.length || 1, income = sum(months, m => m.income) / n, avg = sum(months, m => m.spent[v("bCat")] || 0) / n;
  const amount = parseFloat(v("bValue").replace(/[$,]/g, "")), lines = [`You've averaged <b>${money(avg)}</b> a month here, and earned ${money(income)} a month.`];
  if (mode === "percent" && amount > 0) lines.push(`${amount}% of that income is about <b>${money(income * amount / 100)}</b> a month.`);
  if (mode === "amount" && amount > 0 && income > 0) lines.push(`That's about <b>${Math.round(amount / income * 100)}%</b> of your income.`);
  document.getElementById("bPreview").innerHTML = lines.join(" ");
}
async function saveBudget() {
  const v = id => document.getElementById(id).value;
  const done = await api().save_budget(v("bCat"), v("bMode"), v("bValue"));
  if (!done.ok) return modalError(done.error);
  reload("Budget saved.");
}

