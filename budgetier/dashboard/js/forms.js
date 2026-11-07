function confirmRemove(title, body, run, action = "Remove") {
  showModal(title, "", `<p>${esc(body)}</p>`, `<button class="btn" data-modal="close">Cancel</button><button class="btn danger" data-modal="confirm">${action}</button>`);
  modal.onConfirm = run;
}
async function removal(call, note = "Removed.") {
  const done = await call;
  if (!done.ok) return modalError(done.error);
  reload(note);
}
function editAccount(id) {
  const a = D.accounts.find(x => x.id === id), owed = a.type === "credit";
  const current = a.calculated ? Math.abs(a.balance).toFixed(2) : "";
  showModal(`Edit ${a.name}`, "", `<div class="fields">
      <label class="field">Name<input id="eName" value="${esc(a.name)}" autocomplete="off"></label>
      <label class="field">Type<select id="eType">${TYPE_NAMES.map(([v, n]) => `<option value="${v}"${v === a.type ? " selected" : ""}>${n}</option>`).join("")}</select></label>
      ${a.calculated || a.balance === null ? `<label class="field">${owed ? "Amount owed" : "Balance"}<input id="eBalance" value="${current}" placeholder="From the bank's website" autocomplete="off"></label>
      <label class="field">As of<input id="eDate" type="date" value="${new Date().toLocaleDateString("en-CA")}"></label>` : ""}
    </div>`, '<button class="btn" data-modal="close">Cancel</button><button class="btn primary" data-modal="save">Save</button>');
  modal.dataset.account = id;
}
async function saveAccount() {
  const v = id => { const f = document.getElementById(id); return f ? f.value : ""; };
  const done = await api().update_account(modal.dataset.account, v("eName"), v("eType"), v("eBalance"), v("eDate"));
  if (!done.ok) return modalError(done.error);
  reload("Account saved.");
}
