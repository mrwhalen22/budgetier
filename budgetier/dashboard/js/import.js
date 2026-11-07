async function addFiles() {
  const picked = await api().pick_files();
  if (!picked.ok) return toast(picked.error);
  if (!picked.paths.length) return;
  progress(`Reading ${picked.paths.length === 1 ? "your file" : `${picked.paths.length} files`}...`);
  const plan = await api().inspect(picked.paths);
  progress("");
  if (!plan.ok) return toast(plan.error);
  reviewImport(plan);
}
const TYPE_NAMES = [["checking", "Checking"], ["savings", "Savings"], ["credit", "Credit card"]];
function reviewImport(plan) {
  const card = i => `<section class="panel" data-item="${esc(i.id)}"><h3>${esc(i.file)}</h3>
    <div class="sub">${i.count.toLocaleString()} transactions, ${dName(i.first)} to ${dName(i.last)}${i.known ? ` · adds to ${esc(i.accountName)}: ${i.new.toLocaleString()} new, ${(i.count - i.new).toLocaleString()} already here` : " · new account"}</div>
    ${i.notes.map(n => `<div class="sub">${esc(n)}</div>`).join("")}
    <div class="fields">
      <label class="field">Bank<input name="bank" value="${esc(i.bank)}" placeholder="Bank name" autocomplete="off"></label>
      <label class="field">Last 4 digits<input name="number" value="${esc(i.number)}" maxlength="4" inputmode="numeric" autocomplete="off"></label>
      <label class="field">Type<select name="type"${i.known ? " disabled" : ""}>${TYPE_NAMES.map(([v, n]) => `<option value="${v}"${v === i.type ? " selected" : ""}>${n}</option>`).join("")}</select></label>
      ${i.known || i.hasBalance ? "" : `<label class="field">Current balance, optional<input name="balance" placeholder="For a card, what you owe" autocomplete="off"></label>`}
    </div>
    ${i.askSign ? `<div class="ask">This file shows <b>${esc(i.sample.description)}</b> on ${dName(i.sample.date)} as <b>${cents(i.sample.amount)}</b>. Was that money you spent?<br>
      <label><input type="radio" name="spent-${esc(i.id)}" value="yes"${i.spent ? " checked" : ""}> Yes</label><label><input type="radio" name="spent-${esc(i.id)}" value="no"${i.spent ? "" : " checked"}> No</label></div>` : ""}
  </section>`;
  const bad = plan.errors.map(e => `<div class="banner warn"><b>${esc(e.file)}</b> couldn't be added: ${esc(e.error)}</div>`).join("");
  const n = plan.items.length;
  showModal("Review files", n ? "Check the details. Nothing is saved until you choose Add files." : "", bad + plan.items.map(card).join(""),
    `<button class="btn" data-modal="cancel">${n ? "Cancel" : "Close"}</button>${n ? '<button class="btn primary" data-modal="import">Add files</button>' : ""}`);
  modal.dataset.items = JSON.stringify(plan.items.map(i => i.id));
}
async function runImport(button) {
  const answers = JSON.parse(modal.dataset.items).map(id => {
    const box = modal.querySelector(`[data-item="${id}"]`), val = n => { const f = box.querySelector(`[name=${n}]`); return f ? f.value : ""; };
    const spent = box.querySelector(`[name="spent-${id}"]:checked`);
    return {id, bank: val("bank"), number: val("number"), type: val("type"), balance: val("balance"), spent: spent ? spent.value === "yes" : null};
  });
  const done = await api().commit(answers);
  if (!done.ok) return modalError(done.error);
  showModal("Files added", "", done.results.map(r => `<div class="done-row"><span>${esc(r.account)}</span><span class="dim">${r.added.toLocaleString()} new, ${r.duplicates.toLocaleString()} already here</span></div>`).join(""),
    '<button class="btn primary" data-modal="reload">Done</button>');
}
