/* ---------- rules ---------- */
const ruleChoices = () => [...new Set([...(D.allCategories || []), ...D.categories])].filter(c => c !== "Uncategorized" && c !== "Card Payments (no detail)").sort();
const ruleSuggestion = (merchant, desc) => api().suggest_rule(merchant, [...new Set([desc, ...TX.filter(t => t.merchant === merchant).map(t => t.desc)])]);
async function categorize(merchant, desc, category, tx) {
  const found = await ruleSuggestion(merchant, desc);
  const asEdited = tx && tx.edited ? {merchant, category} : {};
  if (found.ok && found.rule) return ruleForm({...found.rule, desc, tx, ...asEdited});
  ruleForm({text: found.ok ? found.text : "", merchant, category, desc, tx});
}
function uncategorized() {
  const by = {};
  TX.filter(t => t.cat === "Uncategorized").forEach(t => { const m = by[t.merchant] = by[t.merchant] || {merchant: t.merchant, desc: t.desc, n: 0, total: 0}; m.n++; m.total += t.amt; });
  return Object.values(by).sort((a, b) => a.total - b.total);
}
// Working through a list shouldn't mean a full reload per merchant, so the page keeps its
// data until the end, and asks before each one whether a rule just saved has covered it.
let queue = null;
function startQueue(merchant) {
  const items = uncategorized();
  queue = {items, at: items.findIndex(m => m.merchant === merchant), saved: 0, note: ""};
  return nextInQueue();
}
async function nextInQueue() {
  for (; queue.at < queue.items.length; queue.at++) {
    const {merchant, desc} = queue.items[queue.at], found = await ruleSuggestion(merchant, desc);
    if (found.ok && found.rule && queue.saved) continue;
    if (found.ok && found.rule) return ruleForm({...found.rule, desc, queued: true});
    return ruleForm({text: found.ok ? found.text : "", merchant, category: "", desc, queued: true});
  }
  endQueue();
}
function endQueue() {
  const saved = queue.saved;
  queue = null;
  if (saved) reload(`Saved ${saved} rule${saved === 1 ? "" : "s"}.`); else closeModal();
}
function ruleFoot(o) {
  if (!o.queued) return `<button class="btn" data-modal="close">Cancel</button>${o.tx && o.tx.edited ? '<button class="btn" data-modal="edit-clear">Undo change</button>' : ""}<button class="btn primary" data-modal="rule-save">Save</button>`;
  const more = queue.at + 1 < queue.items.length;
  return `<button class="btn" data-modal="queue-done">${queue.saved ? "Done" : "Cancel"}</button>${more ? '<button class="btn" data-modal="rule-skip">Skip</button>' : ""}<button class="btn primary" data-modal="rule-next">${more ? "Save and next" : "Save"}</button>`;
}
function ruleForm(o) {
  const cats = ruleChoices(), known = cats.includes(o.category), one = o.tx && o.tx.edited;
  const every = o.line ? (o.desc ? "A rule already covers this transaction. Changes apply to everything it matches." : "") : "Applies to every matching transaction, past and future.";
  const place = o.queued ? `${queue.at + 1} of ${queue.items.length}` : "";
  const lead = !o.queued ? every : queue.note ? `${queue.note} ${place}.` : `${place}. ${every}`;
  showModal(o.line ? "Edit rule" : "Categorize", one ? JUST_THIS : lead, `${o.tx ? `<div class="ask" role="radiogroup" aria-label="What to change"><label><input type="radio" name="rScope" value="all"${one ? "" : " checked"}> Everything that matches</label><label><input type="radio" name="rScope" value="one"${one ? " checked" : ""}> Just this transaction</label></div>` : ""}<div class="fields">
      ${o.desc ? `<div class="field full">The bank's description<span class="dim code">${esc(o.desc)}</span></div>` : ""}
      <label class="field full" id="rMatchBox"${one ? " hidden" : ""}>When the bank's description contains<input id="rMatch" value="${esc(o.text)}" autocomplete="off"${o.advanced ? ' class="code"' : ""}></label>
      <label class="field">Show as<input id="rName" value="${esc(o.merchant)}" placeholder="Name to display" autocomplete="off"></label>
      <label class="field">Category<select id="rCat"><option value="">Choose...</option>${cats.map(c => `<option${c === o.category ? " selected" : ""}>${esc(c)}</option>`).join("")}<option value="__new"${o.category && !known ? " selected" : ""}>New category...</option></select></label>
      <label class="field full" id="rNewBox"${o.category && !known ? "" : " hidden"}>New category name<input id="rNew" value="${o.category && !known ? esc(o.category) : ""}" autocomplete="off"></label>
    </div><div class="panel" id="rPreview" aria-live="polite"${one ? " hidden" : ""}></div>`, ruleFoot(o));
  modal.tx = o.tx || null;
  modal.dataset.rule = o.line || "";
  modal.dataset.advanced = o.advanced ? "1" : "";
  const run = () => { clearTimeout(ruleForm.t); ruleForm.t = setTimeout(previewRule, 180); };
  document.getElementById("rMatch").oninput = run;
  document.getElementById("rCat").onchange = e => { document.getElementById("rNewBox").hidden = e.target.value !== "__new"; previewRule(); };
  modal.querySelectorAll("[name=rScope]").forEach(r => r.onchange = () => {
    const alone = justThisOne();
    document.getElementById("rMatchBox").hidden = alone;
    document.getElementById("rPreview").hidden = alone;
    modal.querySelector(".modal-head p").textContent = alone ? JUST_THIS : every;
  });
  previewRule();
  if (o.queued) document.getElementById("rCat").focus();
}
const JUST_THIS = "Changes only this transaction. Rules won't change it again.";
const justThisOne = () => !!modal.querySelector("[name=rScope][value=one]:checked");
function txId(t) {
  const words = s => s.toUpperCase().split(/\s+/).filter(Boolean).join(" ");
  const n = TX.slice(0, t.i).filter(x => x.date === t.date && x.acct === t.acct && x.amt === t.amt && words(x.desc) === words(t.desc)).length;
  return {date: t.date, account: ACCT[t.acct].id, cents: Math.round(t.amt * 100), description: t.desc, n};
}
async function clearEdit() {
  const done = await api().clear_edit(txId(modal.tx));
  if (!done.ok) return modalError(done.error);
  reload("Change undone.");
}
async function previewRule() {
  const box = document.getElementById("rPreview"), text = document.getElementById("rMatch").value;
  if (!text.trim()) { box.textContent = ""; return; }
  const r = await api().preview_rule(text, !!modal.dataset.advanced);
  if (!r.ok) { box.textContent = r.error; return; }
  if (!r.count) { box.innerHTML = `<b>No transactions match yet.</b><p class="sub">Rules look for this exact text in the bank's description, which can differ from the name shown. Select a row on the Transactions tab to start from the bank's wording.</p>`; return; }
  const cat = document.getElementById("rCat").value;
  box.innerHTML = `<b>${r.count.toLocaleString()} transaction${r.count === 1 ? "" : "s"}</b> ${r.count === 1 ? "matches" : "match"}, totalling ${cents(r.total)}.${r.share > .25 ? '<span class="warn">That is a lot of your history. Try more specific text.</span>' : ""}${cat === "Transfer" ? '<span class="warn">Transfers don\'t count as spending or income.</span>' : ""}${r.examples.length ? `<ul>${r.examples.map(e => `<li>${esc(e)}</li>`).join("")}</ul>` : ""}`;
}
async function saveRule() {
  const v = id => document.getElementById(id).value, choice = v("rCat"), category = choice === "__new" ? v("rNew") : choice;
  if (justThisOne()) {
    const changed = await api().save_edit(txId(modal.tx), category, v("rName"));
    if (!changed.ok) return modalError(changed.error);
    return reload("Saved. Nothing else changed.");
  }
  const done = await api().save_rule(modal.dataset.rule || null, v("rMatch"), category, v("rName"), !!modal.dataset.advanced);
  if (!done.ok) return modalError(done.error);
  const matched = `${done.count.toLocaleString()} transaction${done.count === 1 ? "" : "s"}`;
  if (!queue) return reload(`Rule saved. It matches ${matched}.`);
  queue.saved++; queue.at++; queue.note = `Saved. That rule matches ${matched}.`;
  await nextInQueue();
}
function rules() {
  const open = uncategorized(), list = D.rules || [];
  V.innerHTML = `<div class="tiles"><div class="tile"><div class="k">Needs a category</div><div class="v">${open.length}</div><div class="s">${open.length === 1 ? "merchant" : "merchants"}, ${cents(Math.abs(sum(open, m => m.total)))} in total</div></div>
      <div class="tile"><div class="k">Your rules</div><div class="v">${list.length}</div><div class="s">applied across all history</div></div></div>
    <div class="card"><h2>Needs a category</h2><p class="sub">Categorize one and you'll move through the rest. To change a single transaction, select its row on the Transactions tab.</p>
      ${open.length ? `<div class="scroll"><table><thead><tr><th>Merchant</th><th class="num">Transactions</th><th class="num">Total</th><th></th></tr></thead><tbody>${open.map(m => `<tr><td>${who(m.merchant, "Uncategorized")}<div class="dim clip">${esc(m.desc)}</div></td><td class="num">${m.n}</td><td class="num ${gain(m.total)}">${cents(m.total)}</td><td><div class="row-actions"><button class="btn small" data-act="categorize" data-merchant="${esc(m.merchant)}">Categorize</button></div></td></tr>`).join("")}</tbody></table></div>` : '<p class="empty">Everything has a category.</p>'}</div>
    <div class="card"><h2>Your rules</h2><p class="sub">Rules run before anything built in. If two match, the higher one wins.</p>
      <div class="tools app-only"><button class="btn primary" data-act="rule-new">${icon(PLUS)}Add rule</button></div>
      ${list.length ? `<div class="scroll"><table><thead><tr><th>Description contains</th><th>Shows as</th><th>Category</th><th class="num">Matches</th><th></th></tr></thead><tbody>${list.map((r, i) => `<tr><td class="clip ${r.advanced ? "rule-text" : ""}" title="${esc(r.text)}">${esc(r.text)}${r.broken ? ' <span class="badge">not valid</span>' : ""}</td><td>${esc(r.merchant) || '<span class="dim">unchanged</span>'}</td><td>${chip(r.category)}</td><td class="num">${r.count.toLocaleString()}</td><td><div class="row-actions"><button class="btn small" data-act="rule-edit" data-i="${i}">Edit</button><button class="btn small danger-text" data-act="rule-delete" data-i="${i}">Remove</button></div></td></tr>`).join("")}</tbody></table></div>` : '<p class="empty">No rules yet.</p>'}</div>`;
}

