/* ---------- controls ---------- */
(function init() {
  const tabs = document.getElementById("tabs");
  TABS.forEach(t => { const b = document.createElement("button"); b.innerHTML = `${icon(ICONS[t])}<span>${t}</span>`; b.dataset.tab = t; if (t === "Rules" || t === "Budgets") b.className = "app-only"; b.setAttribute("role", "tab"); b.onclick = () => { S.tab = t; render(true); scrollTo(0, 0); }; tabs.append(b); });

  document.getElementById("skip").onclick = () => document.getElementById("view").focus();
  document.getElementById("theme").innerHTML = `${icon(SUN)}Appearance`;
  document.getElementById("theme").onclick = appearance;

  const sel = document.getElementById("range"), years = [...new Set(MONTHS.map(m => m.slice(0, 4)))].reverse();
  const group = (label, opts) => `<optgroup label="${label}">${opts.map(([v, n]) => `<option value="${v}">${n}</option>`).join("")}</optgroup>`;
  sel.innerHTML = group("Recent", [["12", "Last 12 months"], ["6", "Last 6 months"], ["3", "Last 3 months"], ["all", "All time"]])
    + group("Year", years.map(y => [y, y])) + group("Month", MONTHS.slice().reverse().map(m => [m, mName(m)]));
  sel.onchange = () => { S.range = sel.value; render(); };

  const list = document.getElementById("acctList"), label = document.getElementById("acctLabel");
  list.innerHTML = D.accounts.map(a => `<label><input type="checkbox" value="${a.index}" checked> ${esc(a.name)}</label>`).join("");
  list.addEventListener("change", e => {
    const i = Number(e.target.value);
    e.target.checked ? S.accts.add(i) : S.accts.delete(i);
    label.textContent = S.accts.size === D.accounts.length ? "All accounts" : `${S.accts.size} of ${D.accounts.length} accounts`;
    render();
  });
  document.addEventListener("click", e => { const box = document.getElementById("acctBox"); if (box.open && !box.contains(e.target)) box.open = false; });

  document.getElementById("foot").textContent = (TX.length ? `Data through ${dName(D.end)}. ` : "") + `${D.sync && D.sync.connected ? "Stored on this computer." : "Stays on this computer."}${D.version ? ` Version ${D.version}.` : ""}`;
  try { const tab = sessionStorage.getItem("budgetier-tab"); if (TABS.includes(tab)) S.tab = tab; } catch {}
  const restored = restoreView();
  if ([...sel.options].some(o => o.value === S.range)) sel.value = S.range; else S.range = sel.value;
  list.querySelectorAll("input").forEach(box => { box.checked = S.accts.has(Number(box.value)); });
  if (S.accts.size < D.accounts.length) label.textContent = `${S.accts.size} of ${D.accounts.length} accounts`;
  // Charts are drawn to the measured width, which can be unknown at first paint.
  let t, width = 0;
  render();
  initApp();
  if (restored) setTimeout(() => { scrollTo(0, restored.y); if (restored.note) toast(restored.note); }, 50);  // after the first measured redraw
  new ResizeObserver(([e]) => {
    if (Math.abs(e.contentRect.width - width) < 1) return;
    const first = !width; width = e.contentRect.width;
    if (S.tab === "Transactions") return;  // no charts, and redrawing would drop search focus
    clearTimeout(t); t = setTimeout(render, first ? 0 : 150);
  }).observe(document.getElementById("view"));
})();
