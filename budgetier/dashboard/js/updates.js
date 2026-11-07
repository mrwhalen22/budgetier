/* ---------- updates ---------- */
let update = null;
async function checkUpdate(byHand = false) {
  const found = await api().check_update(byHand);
  if (!found.ok) { if (byHand) toast(found.error); return; }
  update = found.available ? found : null;
  const button = document.getElementById("updateBtn");
  button.hidden = !update;
  if (update) button.textContent = `Update to ${update.version}`;
  if (byHand) { if (update) updateForm(); else toast("You have the latest version."); }
}
function updateForm() {
  const steps = update.reopens ? "Budgetier closes, Windows asks for your permission, and it opens again when the update is done."
    : D.updates.system === "linux" ? "When the download opens, unpack it over your Budgetier folder." : "When the download opens, drag Budgetier to Applications and replace the old copy.";
  showModal(`Update to ${update.version}`, `You have version ${D.version}.`, `<p>${esc(steps)} Your data isn't touched.</p>`,
    '<button class="btn" data-modal="close">Cancel</button><button class="btn primary" data-modal="update-install">Update</button>');
}
async function installUpdate() {
  const done = await api().install_update();
  if (!done.ok) return modalError(done.error);
  if (done.closing) showModal("Updating", "Budgetier is closing to finish the update.", "", "");
  else showModal("Almost done", "", `<p>${D.updates.system === "linux" ? "Quit Budgetier, then unpack the download over your Budgetier folder." : "Quit Budgetier, then drag it to Applications and replace the old copy."}</p>`, '<button class="btn primary" data-modal="close">Done</button>');
}

