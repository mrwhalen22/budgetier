const BANKS = [
  ["Fifth Third", "Checking CSV", true], ["Chase", "Credit card CSV", true], ["USAA", "Credit card CSV", true], ["Synchrony", "Savings PDF", true],
  ["Chase", "Checking CSV", false], ["American Express", "Card CSV", false], ["Apple Card", "CSV", false], ["Bank of America", "Checking and card CSV", false],
  ["Capital One", "Checking and card CSV", false], ["Citi", "Card CSV", false], ["Discover", "Card CSV", false], ["Ally", "CSV", false],
  ["U.S. Bank", "CSV", false], ["USAA", "Checking CSV", false], ["Wells Fargo", "Checking CSV", false],
];
function bankTable() {
  return `<div class="scroll"><table><thead><tr><th>Bank</th><th>File</th><th>Status</th></tr></thead><tbody>${BANKS.map(([b, f, tested]) => `<tr><td><span class="strong">${b}</span></td><td class="dim">${f}</td><td><span class="badge${tested ? " good" : ""}">${tested ? "Tested with real files" : "Recognized, not yet tested"}</span></td></tr>`).join("")}
    <tr><td><span class="strong">Any other bank</span></td><td class="dim">CSV with date, description and amount columns</td><td><span class="badge">Usually works; you confirm on review</span></td></tr></tbody></table></div>`;
}
function help() {
  V.innerHTML = `<div class="help">${TX.length ? "" : '<div class="controls"><button class="btn" data-act="home">Back</button></div>'}
    <div class="card"><h2>Getting started</h2><p class="sub">Four steps. With files, repeat the first two whenever you want fresh numbers.</p>
      <ol><li><b>Connect or download.</b> Connect SimpleFIN to update accounts automatically, or download transaction history from each bank's website. Look for Download, Export or Statements, choose CSV, and ask for as much history as it offers.</li>
      <li><b>Add files</b> if you downloaded any, and check the review screen. Date ranges can overlap, because repeats are skipped automatically.</li>
      <li><b>Tidy up</b> on the Rules tab by giving unknown purchases a name and category.</li>
      <li><b>Set budgets</b> on the Budgets tab, as a dollar amount or a percent of income.</li></ol>
      <div class="tools app-only"><button class="btn primary" data-act="tour">Take the tour</button></div></div>
    <div class="card"><h2>Which banks work</h2><p class="sub">Budgetier reads columns by name, so it isn't limited to this list. If a bank is new to it, the review screen asks what it can't tell.</p>${bankTable()}</div>
    <div class="card"><h2>Bank sync</h2><p>Connect SimpleFIN to update accounts automatically instead of downloading files. It usually brings in about the last 90 days, and pending transactions wait until they post. Add CSV exports for older history. Overlapping days aren't counted twice, and accounts it can't reach can still use files.</p></div>
    <div class="card"><h2>Tips for good numbers</h2>
      <h3>Import every account you pay from</h3><p>Paying a card from checking is a transfer, so the purchases only appear once that card is imported. Until then, the payment counts as estimated spending.</p>
      <h3>Export as far back as you can</h3><p>Averages skip months before your checking history starts, because those months have no rent or income in them.</p>
      <h3>Enter card balances</h3><p>Card exports don't include a balance. Use Edit on the Accounts tab to enter what you owe, and Budgetier keeps it updated from each import.</p>
      <h3>Fix one transaction</h3><p>Select a row on the Transactions tab and choose Just this transaction. Rules won't change that row again, and you can undo it the same way.</p>
      <h3>How money is counted</h3><p>Expenses and estimates add to spending. Refunds reduce it. Income counts as income. Transfers between your own accounts count as neither.</p></div>
    <div class="card"><h2>Your data</h2><p>${D.sync && D.sync.connected ? "Your data is stored on this computer. Bank sync connects to SimpleFIN to fetch transactions, and nothing is sent to it except that request." : "Everything stays on this computer."} ${networkNote()} Removing a file keeps any transactions another file also covers. Your data is kept apart from the program, so updating doesn't change it.</p>
      <p class="dim">Budgetier${D.version ? " version " + esc(D.version) : ""}</p>
      ${D.updates && D.updates.supported ? `<div class="tools inset app-only"><button class="btn" data-act="update-check">Check for updates</button><button class="btn" data-act="update-auto">${D.updates.automatic ? "Stop checking automatically" : "Check automatically"}</button></div>` : ""}</div></div>`;
}
function networkNote() {
  if (D.updates && D.updates.supported && D.updates.automatic) return "When it opens, Budgetier asks GitHub whether a new version is out, and no financial data goes with that request.";
  return D.sync && D.sync.connected ? "" : "Budgetier makes no network requests.";
}

