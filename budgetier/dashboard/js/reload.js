// Saving redraws the page from new data, so what you were looking at is carried across.
const VIEW_KEY = "budgetier-view", VIEW_FIELDS = ["range", "txq", "txcat", "txkind", "txsort", "txdir", "txshow", "recAll", "largeAll"];
function reload(note = "") {
  const view = Object.fromEntries(VIEW_FIELDS.map(k => [k, S[k]]));
  view.y = scrollY;
  view.note = note;
  if (S.accts.size < D.accounts.length) view.accts = D.accounts.filter(a => S.accts.has(a.index)).map(a => a.id);
  try { sessionStorage.setItem(VIEW_KEY, JSON.stringify(view)); } catch {}
  location.reload();
}
function restoreView() {
  let view;
  try { view = JSON.parse(sessionStorage.getItem(VIEW_KEY)); sessionStorage.removeItem(VIEW_KEY); } catch {}
  if (!view) return null;
  VIEW_FIELDS.forEach(k => { S[k] = view[k]; });
  if (view.accts) S.accts = new Set(D.accounts.filter(a => view.accts.includes(a.id)).map(a => a.index));
  return view;
}

