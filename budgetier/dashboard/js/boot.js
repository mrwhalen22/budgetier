// Before anything draws, so the page never flashes the wrong theme.
const LOOK_KEY = "budgetier-look", PALETTES = [["pine", "Pine"], ["ocean", "Ocean"], ["plum", "Plum"]];
const Look = {mode: "system", palette: "pine"};
try {
  const saved = JSON.parse(localStorage.getItem(LOOK_KEY)) || {}, older = localStorage.getItem("budgetier-theme");
  Object.assign(Look, older ? {mode: older} : {}, saved);
} catch {}
function applyLook() {
  const system = matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light", root = document.documentElement;
  root.dataset.mode = Look.mode === "system" ? system : Look.mode;
  root.dataset.palette = PALETTES.some(([p]) => p === Look.palette) ? Look.palette : "pine";
}
applyLook();
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", applyLook);
