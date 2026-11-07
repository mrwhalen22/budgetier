/* ---------- desktop app ---------- */
// Everything here needs the app's bridge; opened in a browser, the page stays read-only.
const modal = document.getElementById("modal");
const api = () => window.pywebview.api;
// Lives outside the app's bridge: the look works in a plain browser too.
function appearance() {
  const pressed = on => `aria-pressed="${on}"`, mode = Look.mode;
  showModal("Appearance", "This computer remembers your choice.", `<div class="choice-label">Mode</div>
    <div class="segments">${[["system", "Match system"], ["light", "Light"], ["dark", "Dark"]].map(([v, n]) => `<button type="button" data-look-mode="${v}" ${pressed(v === mode)}>${n}</button>`).join("")}</div>
    <div class="choice-label">Theme</div>
    <div class="swatches">${PALETTES.map(([v, n]) => `<button type="button" class="swatch" data-look-palette="${v}" data-palette="${v}" data-mode="${document.documentElement.dataset.mode}" ${pressed(v === Look.palette)}><i></i>${n}</button>`).join("")}</div>`,
    '<button class="btn primary" data-modal="close">Done</button>');
}
function setLook(change) {
  Object.assign(Look, change);
  try { localStorage.setItem(LOOK_KEY, JSON.stringify(Look)); localStorage.removeItem("budgetier-theme"); } catch {}
  applyLook();
  appearance();
}
function toast(text) {
  const t = document.getElementById("toast");
  t.textContent = text; t.style.display = "block";
  clearTimeout(toast.timer); toast.timer = setTimeout(() => t.style.display = "none", 5000);
}
function showModal(title, sub, body, foot) {
  if (document.getElementById("coach")) endTour();
  modal.innerHTML = `<div class="modal"><div class="modal-head"><h2 id="modalTitle">${esc(title)}</h2>${sub ? `<p>${esc(sub)}</p>` : ""}</div><div class="modal-body">${body}</div><div class="modal-foot"><span class="msg" id="modalMsg" role="alert"></span>${foot}</div></div>`;
  if (!modal.open) modal.showModal();
}
const modalError = text => { document.getElementById("modalMsg").textContent = text; };
const closeModal = () => modal.close();
// Esc does what the dialog's first button does, because closing can have a job to finish:
// a page to refresh, or files to let go of. While something is saving, it waits.
function dismissModal() {
  const buttons = [...modal.querySelectorAll(".modal-foot .btn")];
  if (buttons.length && !buttons.some(b => b.disabled)) buttons[0].click();
}
const ENTER_SAVES = ["rule-next", "rule-save", "budget-save", "save", "bank-connect"];
modal.addEventListener("cancel", e => { e.preventDefault(); dismissModal(); });
modal.addEventListener("keydown", e => {
  if (e.key === "Escape") { e.preventDefault(); return dismissModal(); }
  if (e.key !== "Enter" || e.isComposing || !e.target.matches("input")) return;
  const save = ENTER_SAVES.map(name => modal.querySelector(`[data-modal="${name}"]`)).find(Boolean);
  if (save) { e.preventDefault(); save.click(); }
});

// A note that stays up until the work is done, for steps that can take a while.
function progress(text) {
  const t = document.getElementById("toast");
  clearTimeout(toast.timer);
  t.textContent = text; t.style.display = text ? "block" : "none";
}
// The button can't be pressed twice, and says what's happening if the work is slow.
async function hold(button, label, work) {
  const text = button.textContent;
  button.disabled = true; button.textContent = label;
  try { await work(); } finally { button.disabled = false; button.textContent = text; }
}

