/* ---------- charts ---------- */
const tip = document.getElementById("tip");
function showTip(e, title, rows) {
  tip.innerHTML = `<b>${esc(title)}</b>` + rows.map(r => `<div><span>${r.c ? `<i style="background:${r.c}"></i>` : ""}${esc(r.k)}</span><span>${esc(r.v)}</span></div>`).join("");
  tip.style.display = "block";
  const w = tip.offsetWidth, h = tip.offsetHeight;
  tip.style.left = Math.min(e.clientX + 14, innerWidth - w - 8) + "px";
  tip.style.top = Math.min(e.clientY + 14, innerHeight - h - 8) + "px";
}
const hideTip = () => tip.style.display = "none";
function bindTips(el, tips, say) {
  const hits = [...el.querySelectorAll("[data-tip]")], svg = el.querySelector("svg");
  const mark = on => hits.forEach(h => h.classList.toggle("on", h === on));
  let at = -1;
  hits.forEach(n => {
    n.addEventListener("mousemove", e => { const t = tips[n.dataset.tip]; showTip(e, t.title, t.rows); });
    n.addEventListener("mouseleave", hideTip);
  });
  // One stop on the Tab key however many months there are; the arrows walk through them.
  svg.addEventListener("keydown", e => {
    const move = {ArrowRight: 1, ArrowLeft: -1}[e.key];
    if (!move) return;
    e.preventDefault();
    at = at < 0 && move < 0 ? hits.length - 1 : Math.min(Math.max(at + move, 0), hits.length - 1);
    const n = hits[at], t = tips[n.dataset.tip], r = n.getBoundingClientRect();
    mark(n);
    showTip({clientX: r.left + r.width / 2, clientY: r.top + 12}, t.title, t.rows);
    document.getElementById("say").textContent = say(t);
  });
  svg.addEventListener("blur", () => { at = -1; mark(null); hideTip(); });
}
function drawChart(el, f, body, tips, spoken = t => t.rows) {
  const say = t => `${t.title}: ${spoken(t).map(r => `${r.k} ${r.v}`).join(", ")}`;
  const label = `Use the left and right arrow keys to read each month. ${Object.values(tips).map(say).join(". ")}`;
  el.innerHTML = `<svg viewBox="0 0 ${f.W} ${f.H}" height="${f.H}" role="img" tabindex="0" aria-label="${esc(label)}">${f.g}${body}</svg>`;
  bindTips(el, tips, say);
}
function niceMax(v) {
  if (v <= 0) return 1;
  const p = Math.pow(10, Math.floor(Math.log10(v))), n = v / p;
  return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 2.5 ? 2.5 : n <= 5 ? 5 : 10) * p;
}
const scaled = base => Math.round(Math.max(base, Math.min(innerHeight * .44, base * 2.4)));
function frame(el, height, months, lo, hi) {
  const W = Math.max(el.clientWidth, 280), H = scaled(height), L = 40, R = 2, T = 8, B = 22;
  // Below-zero ticks use the same step as above-zero ones, so a tick lands on $0.
  const top = niceMax(Math.max(hi, -lo / 2)), tick = top / 4, bottom = lo < 0 ? -Math.ceil(-lo / tick) * tick : 0;
  const y = v => T + (H - T - B) * (top - v) / (top - bottom);
  const band = (W - L - R) / months.length;
  const x = i => L + band * i;
  let g = "";
  for (let v = bottom; v <= top + tick / 2; v += tick) {
    g += `<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}" stroke="${v === 0 ? CSS("line") : CSS("line-soft")}"/><text x="${L - 8}" y="${y(v) + 4}" text-anchor="end">${short(v)}</text>`;
  }
  const every = Math.ceil(months.length / Math.max(1, Math.floor((W - L - R) / 62)));
  months.forEach((m, i) => { if (i % every === 0) g += `<text x="${x(i) + band / 2}" y="${H - 6}" text-anchor="middle">${mName(m, months.length <= 6 || m.endsWith("-01"))}</text>`; });
  return {W, H, x, y, band, g, T, B};
}
function legend(items) { return `<div class="legend">${items.map(i => `<span><i style="background:${i.color}"></i>${esc(i.name)}</span>`).join("")}</div>`; }

function bars(el, {months, series, stacked = false, height = 260}) {
  const vals = months.map((_, i) => series.map(s => s.values[i]));
  const hi = stacked ? Math.max(...vals.map(v => sum(v, x => Math.max(x, 0)))) : Math.max(...vals.flat());
  const lo = stacked ? Math.min(0, ...vals.map(v => sum(v, x => Math.min(x, 0)))) : Math.min(0, ...vals.flat());
  const f = frame(el, height, months, lo, hi);
  const inner = Math.min(f.band * .72, 96), tips = {};
  let marks = "", hits = "";
  months.forEach((m, i) => {
    if (stacked) {
      let up = 0, dn = 0;
      const w = Math.min(inner, Math.max(26, f.band * .42)), bx = f.x(i) + (f.band - w) / 2;
      series.forEach(s => {
        const v = s.values[i]; if (!v) return;
        const a = v > 0 ? up : dn, b = a + v;
        if (v > 0) up = b; else dn = b;
        const y0 = f.y(Math.max(a, b)), h = Math.max(Math.abs(f.y(a) - f.y(b)) - 2, 1);
        marks += `<rect x="${bx}" y="${y0}" width="${w}" height="${h}" rx="2.5" fill="${s.color}"/>`;
      });
    } else {
      const w = Math.min((inner - 3 * (series.length - 1)) / series.length, Math.max(15, f.band * .28));
      const total = w * series.length + 3 * (series.length - 1), start = f.x(i) + (f.band - total) / 2;
      series.forEach((s, k) => {
        const v = s.values[i], y0 = f.y(Math.max(v, 0)), h = Math.abs(f.y(v) - f.y(0));
        if (h > 0) marks += `<rect x="${start + k * (w + 3)}" y="${y0}" width="${w}" height="${Math.max(h, 1)}" rx="${Math.min(4, w / 2)}" fill="${s.colorFor ? s.colorFor(v) : s.color}"/>`;
      });
    }
    tips[i] = {title: mName(m) + (m === D.partialMonth ? " (so far)" : ""), rows: series.filter(s => !stacked || s.values[i]).slice().reverse().map(s => ({k: s.name, v: money(s.values[i]), c: s.colorFor ? s.colorFor(s.values[i]) : s.color}))};
    if (stacked) tips[i].rows.push({k: "Total", v: money(sum(series, s => s.values[i]))});
    hits += `<rect class="hit" data-tip="${i}" x="${f.x(i)}" y="${f.T}" width="${f.band}" height="${f.H - f.T - f.B}"/>`;
  });
  drawChart(el, f, marks + hits, tips, stacked ? t => t.rows.slice(-1) : undefined);
}
function lines(el, {months, series, height = 260}) {
  const all = series.flatMap(s => s.values.filter(v => v !== null));
  if (!all.length) { el.innerHTML = '<p class="empty">No data in this period.</p>'; return; }
  const f = frame(el, height, months, Math.min(0, ...all), Math.max(...all));
  const tips = {}; let marks = "", hits = "";
  series.forEach(s => {
    let d = "", pen = false;
    s.values.forEach((v, i) => { if (v === null) { pen = false; return; } d += `${pen ? "L" : "M"}${f.x(i) + f.band / 2} ${f.y(v)}`; pen = true; });
    if (series.length === 1 && months.length > 1) {  // a soft wash under a lone line
      const base = f.y(Math.max(0, Math.min(...all))), ends = s.values.map((v, i) => v === null ? null : f.x(i) + f.band / 2).filter(x => x !== null);
      const id = `wash${el.id}`;
      marks += `<defs><linearGradient id="${id}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${s.color}" stop-opacity=".2"/><stop offset="1" stop-color="${s.color}" stop-opacity="0"/></linearGradient></defs><path d="${d}L${ends[ends.length - 1]} ${base}L${ends[0]} ${base}Z" fill="url(#${id})"/>`;
    }
    marks += `<path d="${d}" fill="none" stroke="${s.color}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>`;
    s.values.forEach((v, i) => { if (v !== null && (months.length <= 2 || i === s.values.length - 1)) marks += `<circle cx="${f.x(i) + f.band / 2}" cy="${f.y(v)}" r="4" fill="${s.color}" stroke="${CSS("surface")}" stroke-width="2"/>`; });
  });
  months.forEach((m, i) => {
    tips[i] = {title: mName(m), rows: series.filter(s => s.values[i] !== null).map(s => ({k: s.name, v: money(s.values[i]), c: s.color}))};
    hits += `<rect class="hit" data-tip="${i}" x="${f.x(i)}" y="${f.T}" width="${f.band}" height="${f.H - f.T - f.B}"/>`;
  });
  drawChart(el, f, marks + hits, tips);
}
function hbars(items, fmt, barColor) {
  const max = Math.max(...items.map(i => i.value), 1), total = sum(items, i => i.value);
  return items.map(i => `<div class="hbar" role="button" tabindex="0" data-cat="${esc(i.cat || "")}" data-q="${esc(i.q || "")}"><div class="name">${i.color ? `<i style="background:${i.color}"></i>` : ""}<span title="${esc(i.name)}">${esc(i.name)}</span></div>
    <div class="num"><span class="pct">${Math.round(i.value / total * 100)}%</span><span>${fmt(i.value)}</span></div>
    <div class="track"><div class="fill" style="width:${Math.max(i.value / max * 100, .5)}%;background:${i.color || barColor}"></div></div></div>`).join("");
}
const mono = (name, c) => `<span class="mono" style="--m:${c}" aria-hidden="true">${esc(name.split(/\s+/).slice(0, 2).map(w => w[0] || "").join("").toUpperCase())}</span>`;
const who = (name, cat) => `<div class="who">${mono(name, color(cat))}<span>${esc(name)}</span></div>`;
const chip = cat => `<span class="chip"><i style="background:${color(cat)}"></i>${esc(cat)}</span>`;
function drillDown(root) {
  root.querySelectorAll("[data-cat],[data-q]").forEach(n => n.addEventListener("click", () => {
    if (!n.dataset.cat && !n.dataset.q) return;
    Object.assign(S, {txcat: n.dataset.cat || "", txq: n.dataset.q || "", txkind: "", txshow: 200, tab: "Transactions"});
    render(true);
  }));
  root.querySelectorAll(".hbar, .link").forEach(n => {
    n.tabIndex = 0;
    n.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); n.click(); } });
  });
}

