const VIEWS = {Overview: overview, Spending: spending, Budgets: budgets, Recurring: recurring, Largest: largest, Savings: savings, Accounts: accounts, Transactions: transactions, Rules: rules, Help: help};
const fullHistory = new Set(["Budgets", "Recurring", "Accounts", "Rules", "Help"]);
function render(moved = false) {
  hideTip();
  document.body.classList.toggle("empty-app", !TX.length);
  if (!TX.length) {
    if (S.tab === "Help") return help();
    V.innerHTML = `<div class="welcome"><h2>Welcome to Budgetier</h2><p>See where your money goes. Start by bringing in your accounts.</p>
      ${D.sync && D.sync.connected ? syncCard() : `<div class="starts"><div class="card app-only"><h2>Connect your banks</h2><p>Updates automatically through SimpleFIN, a paid service that handles your transactions. Usually brings in about the last 90 days.</p><button class="btn primary" data-act="bank-connect">Connect SimpleFIN</button></div>
      <div class="card"><h2>Add files</h2><p>Download CSV exports from each bank, for as much history as you like. Everything stays on this computer.</p><button class="btn" data-act="add">${icon(PLUS)}Add files</button></div></div>`}
      <div class="welcome-actions"><button class="btn" data-act="banks">See which banks work</button></div></div>`;
    return;
  }
  try { sessionStorage.setItem("budgetier-tab", S.tab); } catch {}
  document.querySelectorAll("#tabs button").forEach(b => b.setAttribute("aria-selected", b.dataset.tab === S.tab));
  document.body.classList.toggle("no-filters", fullHistory.has(S.tab));
  document.getElementById("title").textContent = S.tab;
  document.getElementById("subtitle").textContent = fullHistory.has(S.tab) ? "All history" : rangeLabel();
  V.classList.toggle("enter", moved);
  VIEWS[S.tab]();
  document.title = `${S.tab} · Budgetier`;
}


