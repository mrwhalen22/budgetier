/* ---------- bank sync ---------- */
function syncCard() {
  const s = D.sync;
  if (!s) return "";
  if (!s.connected) return `<div class="card app-only"><h2>Bank sync</h2><p class="sub">Update accounts automatically through SimpleFIN instead of downloading files. SimpleFIN and the services behind it handle your transactions, so they no longer stay only on this computer.</p><div class="tools inset app-only"><button class="btn" data-act="bank-connect">Connect SimpleFIN</button></div></div>`;
  const when = syncedAt() || "not yet";
  const noAccounts = !s.linked.length;
  return `<div class="card app-only"><h2>Bank sync</h2><p class="sub">Connected through SimpleFIN. Last synced ${esc(when)}.${s.linked.length ? ` Updating ${esc(s.linked.join(", "))}.` : " No accounts chosen yet."}</p>
    ${s.problems.map(p => `<div class="banner warn">${esc(p)}</div>`).join("")}
    ${s.unlinked ? `<div class="banner warn">SimpleFIN has ${s.unlinked} account${s.unlinked === 1 ? "" : "s"} you haven't chosen yet.</div>` : ""}
    <div class="tools inset app-only">${noAccounts ? "" : '<button class="btn primary" data-act="bank-sync">Sync now</button>'}<button class="btn${noAccounts ? " primary" : ""}" data-act="bank-review">Choose accounts</button><button class="btn" data-act="bank-disconnect">Disconnect</button></div></div>`;
}
const syncedAt = () => D.sync && D.sync.lastSync ? new Date(D.sync.lastSync).toLocaleString("en-US", {month: "short", day: "numeric", hour: "numeric", minute: "2-digit"}) : "";
function paintBankButton() {
  const b = document.getElementById("bankBtn"), s = D.sync;
  if (!s) return b.remove();
  b.textContent = !s.connected ? "Connect SimpleFIN" : s.linked.length ? "Sync now" : "Choose accounts";
  b.title = s.connected && s.lastSync ? `Last synced ${syncedAt()}` : "";
}
function bankAction(button) {
  if (!D.sync.connected) return connectBankForm();
  return D.sync.linked.length ? hold(button, "Syncing...", syncNow) : hold(button, "Checking...", openBankReview);
}
function connectBankForm() {
  showModal("Connect SimpleFIN", "Paste the setup token from your SimpleFIN account. It only works once.", `<label class="field">Setup token<input id="sToken" type="password" autocomplete="off" spellcheck="false" autofocus></label>
    <p class="dim">Budgetier keeps this connection in this computer's secure storage. It can read your transactions and balances, but can't move money. SimpleFIN and the services behind it will handle your transactions.</p>`,
    '<button class="btn" data-modal="close">Cancel</button><button class="btn primary" data-modal="bank-connect">Connect</button>');
}
async function connectBank() {
  const done = await api().connect_bank(document.getElementById("sToken").value);
  if (!done.ok) return modalError(done.error);
  reviewBank(done, true);
}
async function openBankReview() {
  const plan = await api().review_bank();
  if (!plan.ok) return toast(plan.error);
  reviewBank(plan);
}
function reviewBank(plan, justConnected = false) {
  const choices = a => [...plan.existing.map(x => [x.id, x.name]), ["", "New account"], ["skip", "Don't sync"]]
    .map(([v, n]) => `<option value="${esc(v)}"${v === (a.skipped ? "skip" : a.account) ? " selected" : ""}>${esc(n)}</option>`).join("");
  const card = a => `<section class="panel" data-key="${esc(a.key)}"><h3>${esc(a.bank)}: ${esc(a.name)}</h3>
    <div class="sub">Balance ${cents(a.balance)}${a.currency === "USD" ? "" : " " + esc(a.currency)}, ${a.count.toLocaleString()} recent transactions</div>
    ${a.currency === "USD" ? `<div class="fields"><label class="field">Add to<select name="link">${choices(a)}</select></label></div>
    <div class="fields" data-new${a.account || a.skipped ? " hidden" : ""}>
      <label class="field">Bank<input name="bank" value="${esc(a.bank)}" autocomplete="off"></label>
      <label class="field">Last 4 digits, optional<input name="number" value="${esc(a.number)}" maxlength="4" inputmode="numeric" autocomplete="off"></label>
      <label class="field">Type<select name="type">${TYPE_NAMES.map(([v, n]) => `<option value="${v}"${v === a.type ? " selected" : ""}>${n}</option>`).join("")}</select></label>
    </div>` : `<div class="sub">Only US dollar accounts can sync, so this one is skipped.</div>`}</section>`;
  const bad = plan.problems.map(p => `<div class="banner warn">${esc(p)}</div>`).join("");
  const empty = plan.problems.length ? "" : "<p>SimpleFIN didn't send any accounts yet. Check the banks connected on your SimpleFIN account.</p>";
  showModal("Choose accounts", plan.accounts.length ? (plan.existing.length ? "Match each bank account to one here, or add it as new. History you've already imported stays, and syncing adds what's newer." : "Check each account, then save. You can change this later.") : "", bad + (plan.accounts.map(card).join("") || empty),
    `<button class="btn" data-modal="${justConnected ? "reload" : "close"}">${plan.accounts.length ? "Cancel" : "Close"}</button>${plan.accounts.length ? '<button class="btn primary" data-modal="bank-link">Save</button>' : ""}`);
  modal.querySelectorAll("[name=link]").forEach(pick => { pick.onchange = () => { pick.closest(".panel").querySelector("[data-new]").hidden = pick.value !== ""; }; });
}
async function linkBank() {
  const value = (box, n) => { const f = box.querySelector(`[name=${n}]`); return f ? f.value : ""; };
  const choices = [...modal.querySelectorAll("[data-key]")].map(box => ({key: box.dataset.key, name: box.querySelector("h3").textContent, account: box.querySelector("[name=link]") ? value(box, "link") : "skip", bank: value(box, "bank"), number: value(box, "number"), type: value(box, "type")}));
  const done = await api().link_bank(choices);
  if (!done.ok) return modalError(done.error);
  showModal("Accounts saved", done.results.length ? "SimpleFIN usually brings in about the last 90 days. To go further back, add CSV exports. Overlapping days aren't counted twice." : "", (done.results.map(r => `<div class="done-row"><span>${esc(r.account)}</span><span class="dim">${r.added.toLocaleString()} new</span></div>`).join("") || "<p>No accounts are syncing.</p>"),
    '<button class="btn primary" data-modal="reload">Done</button>');
}
async function syncNow() {
  const done = await api().sync_bank(false);
  if (!done.ok) return toast(done.error);
  if (done.skipped) return toast("Synced a moment ago, so there's nothing new yet.");
  if (done.added) return reload(syncNote(done.added));
  reload(done.problems.length || done.unlinked ? "Synced. See Bank sync on the Accounts tab." : "Everything's up to date.");
}
const syncNote = n => `Synced: ${n.toLocaleString()} new transaction${n === 1 ? "" : "s"}.`;
async function autoSync() {
  if (!D.sync || !D.sync.connected) return;
  if (!D.sync.linked.length) return;
  const button = document.getElementById("bankBtn");
  await hold(button, "Syncing...", async () => {
    const done = await api().sync_bank(true);
    if (!done.ok) return toast(done.error);
    if (done.added) { if (modal.open) toast(syncNote(done.added)); else reload(syncNote(done.added)); }
  });
}

