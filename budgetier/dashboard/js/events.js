function initApp() {
  const ready = () => {
    document.body.classList.add("in-app");
    document.getElementById("addFiles").innerHTML = `${icon(PLUS)}Add files`;
    paintBankButton();
    render();
    maybeTour();
    checkUpdate();
  };
  if (window.pywebview && window.pywebview.api) ready(); else addEventListener("pywebviewready", ready);
  document.addEventListener("keydown", e => {
    if ((e.key === "Enter" || e.key === " ") && e.target.matches("tr[data-tx]")) { e.preventDefault(); e.target.click(); }
  });
  document.addEventListener("click", async e => {
    const act = e.target.closest("[data-act]"), m = e.target.closest("[data-modal]"), step = e.target.closest("[data-tour]");
    if (step) return step.dataset.tour === "end" ? endTour() : tour(Number(step.dataset.tour));
    const look = e.target.closest("[data-look-mode], [data-look-palette]");
    if (look) return setLook(look.dataset.lookMode ? {mode: look.dataset.lookMode} : {palette: look.dataset.lookPalette});
    const txRow = e.target.closest("tr[data-tx]");
    if (txRow && window.pywebview) {
      const t = TX[Number(txRow.dataset.tx)];
      return categorize(t.merchant, t.desc, t.cat === "Uncategorized" ? "" : t.cat, t);
    }
    if (e.target.closest("#addFiles") || (act && act.dataset.act === "add")) return addFiles();
    if (e.target.closest("#updateBtn")) return updateForm();
    const bank = e.target.closest("#bankBtn");
    if (bank) return bankAction(bank);
    if (act) {
      const {id, file, rows} = act.dataset;
      if (act.dataset.act === "folder") return api().open_data_folder();
      if (act.dataset.act === "bank-connect") return connectBankForm();
      if (act.dataset.act === "bank-sync") return hold(act, "Syncing...", syncNow);
      if (act.dataset.act === "update-check") return hold(act, "Checking...", () => checkUpdate(true));
      if (act.dataset.act === "update-auto") { const on = !D.updates.automatic, done = await api().set_update_check(on); if (!done.ok) return toast(done.error); D.updates.automatic = on; return render(); }
      if (act.dataset.act === "bank-review") return hold(act, "Checking...", openBankReview);
      if (act.dataset.act === "bank-disconnect") return confirmRemove("Disconnect SimpleFIN?", "Budgetier stops syncing and forgets the connection. Your transactions stay. To cut off access completely, disable it on the SimpleFIN site too.", () => removal(api().disconnect_bank(), "Disconnected."), "Disconnect");
      if (act.dataset.act === "banks") { S.tab = "Help"; return render(); }
      if (act.dataset.act === "home") { S.tab = "Overview"; return render(); }
      if (act.dataset.act === "tour") return tour();
      if (act.dataset.act === "categorize") return startQueue(act.dataset.merchant);
      if (act.dataset.act === "see-month") { S.range = document.getElementById("range").value = act.dataset.month; return render(true); }
      if (act.dataset.act === "rule-new") return ruleForm({text: "", merchant: "", category: ""});
      if (act.dataset.act === "rule-edit") { const r = D.rules[Number(act.dataset.i)]; return ruleForm({...r}); }
      if (act.dataset.act === "rule-delete") {
        const r = D.rules[Number(act.dataset.i)];
        return confirmRemove("Remove this rule?", `Transactions matching "${r.text}" go back to their automatic category. You can add the rule again any time.`, () => removal(api().delete_rule(r.line)));
      }
      if (act.dataset.act === "budget-new") return budgetForm();
      if (act.dataset.act === "budget-edit") return budgetForm(B.targets.find(t => t.category === act.dataset.catName));
      if (act.dataset.act === "budget-delete") {
        const name = act.dataset.catName;
        return confirmRemove(`Remove the ${name} budget?`, "Your transactions aren't affected. You can add the budget again any time.", () => removal(api().delete_budget(name)));
      }
      if (act.dataset.act === "export") { const r = await api().export_workbook(); return toast(r.ok ? (r.saved ? `Saved ${r.saved}` : "") || "Not saved" : r.error); }
      if (act.dataset.act === "edit") return editAccount(id);
      if (act.dataset.act === "drop-import") return confirmRemove(`Remove ${file}?`, `This file added ${rows} transactions. Any that another imported file also covers will stay. To bring the rest back, import the file again.`, () => removal(api().remove_import(id)));
      if (act.dataset.act === "drop-account") {
        const a = D.accounts.find(x => x.id === id);
        return confirmRemove(`Remove ${a.name}?`, `This deletes its ${a.count.toLocaleString()} transactions and saved files from Budgetier. Your original files aren't touched, so you can import them again.`, () => removal(api().remove_account(id)));
      }
    }
    if (m) {
      const what = m.dataset.modal;
      if (what === "cancel") { await api().cancel(); return closeModal(); }
      if (what === "close") return closeModal();
      if (what === "reload") return reload();
      if (what === "import") return hold(m, "Adding...", () => runImport(m));
      if (what === "save") return hold(m, "Saving...", saveAccount);
      if (what === "rule-save" || what === "rule-next") return hold(m, "Saving...", saveRule);
      if (what === "rule-skip") { queue.at++; return hold(m, "Skipping...", nextInQueue); }
      if (what === "queue-done") return endQueue();
      if (what === "edit-clear") return hold(m, "Working...", clearEdit);
      if (what === "update-install") return hold(m, "Downloading...", installUpdate);
      if (what === "budget-save") return hold(m, "Saving...", saveBudget);
      if (what === "bank-connect") return hold(m, "Connecting...", connectBank);
      if (what === "bank-link") return hold(m, "Saving...", linkBank);
      if (what === "confirm") return hold(m, "Working...", modal.onConfirm);
    }
  });
}

