/* ---------- tour ---------- */
const TOUR = [
  ["#addFiles", "Add more history", "Choose CSV exports or a Synchrony PDF any time. You check everything on a review screen before it's saved."],
  ["#bankBtn", "Keep accounts up to date", "Connect your banks through SimpleFIN, or sync the ones you've connected. Budgetier also syncs when it opens."],
  ['[data-tab="Overview"]', "See the big picture", "Spending, income and how much of each dollar you keep, by month."],
  ['[data-tab="Budgets"]', "Set monthly budgets", "Give a category a target, in dollars or as a percent of income, and see what's left each month."],
  ['[data-tab="Recurring"]', "Spot regular bills", "Subscriptions and repeat payments are found automatically."],
  ['[data-tab="Rules"]', "Teach it your merchants", "Give unknown purchases a name and category. It applies to all your history and future imports."],
  ['[data-tab="Accounts"]', "Manage your accounts", "Manage bank sync, set card balances, remove files or accounts, and export to Excel."],
  ['[data-tab="Help"]', "Find help any time", "See which banks work and how to get the most accurate numbers."],
];
function endTour() {
  document.getElementById("spot")?.remove(); document.getElementById("coach")?.remove();
  try { localStorage.setItem("budgetier-toured", "1"); } catch {}
}
function tour(n = 0) {
  const step = TOUR[n]; if (!step) return endTour();
  const el = document.querySelector(step[0]);
  if (!el || !el.offsetParent) return tour(n + 1);
  let spot = document.getElementById("spot"), coach = document.getElementById("coach");
  if (!spot) { spot = document.createElement("div"); spot.id = "spot"; document.body.append(spot); coach = document.createElement("div"); coach.id = "coach"; coach.setAttribute("role", "dialog"); coach.setAttribute("aria-label", "Tour"); document.body.append(coach); }
  const r = el.getBoundingClientRect(), pad = 5;
  Object.assign(spot.style, {left: r.left - pad + "px", top: r.top - pad + "px", width: r.width + pad * 2 + "px", height: r.height + pad * 2 + "px"});
  coach.innerHTML = `<h3>${step[1]}</h3><p>${step[2]}</p><div class="row"><span class="count">${n + 1} of ${TOUR.length}</span><button class="btn small" data-tour="end">Skip</button><button class="btn small primary" data-tour="${n + 1}">${n + 1 === TOUR.length ? "Done" : "Next"}</button></div>`;
  coach.querySelector(".primary").focus({preventScroll: true});
  const narrow = innerWidth < 880;
  coach.style.left = (narrow ? 16 : Math.min(r.right + 16, innerWidth - 356)) + "px";
  coach.style.top = (narrow ? Math.min(r.bottom + 14, innerHeight - 190) : Math.min(r.top, innerHeight - 190)) + "px";
}
function maybeTour() {
  if (!TX.length || !document.body.classList.contains("in-app")) return;
  try { if (localStorage.getItem("budgetier-toured")) return; } catch { return; }
  setTimeout(() => tour(), 500);
}

