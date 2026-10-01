/* Small SVG chart kit: line (with band, rugs, crosshair), columns, diverging
   bars with intervals, sparklines. Colors come from CSS custom properties so
   both themes work; all labels are set with textContent. */
(function () {
  const NS = "http://www.w3.org/2000/svg";
  const tip = document.createElement("div");
  tip.className = "tt";
  tip.hidden = true;
  document.addEventListener("DOMContentLoaded", () => document.body.appendChild(tip));

  function s(tag, attrs, parent) {
    const el = document.createElementNS(NS, tag);
    for (const k in attrs || {}) if (attrs[k] !== undefined && attrs[k] !== null) el.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(el);
    return el;
  }
  function text(parent, x, y, str, cls, anchor) {
    const t = s("text", { x, y, class: cls || "ax", "text-anchor": anchor || "start" }, parent);
    t.textContent = str;
    return t;
  }
  function niceTicks(lo, hi, count) {
    if (lo === hi) { lo -= 1; hi += 1; }
    const span = hi - lo;
    const step0 = span / Math.max(1, count);
    const mag = Math.pow(10, Math.floor(Math.log10(step0)));
    const step = [1, 2, 2.5, 5, 10].map(m => m * mag).find(st => span / st <= count) || 10 * mag;
    const start = Math.floor(lo / step) * step;
    const ticks = [];
    for (let v = start; v <= hi + step * 0.5; v += step) ticks.push(+v.toFixed(6));
    return ticks;
  }
  const parseDay = str => new Date(str + "T12:00:00");
  const fmtDay = str => parseDay(str).toLocaleDateString(undefined, { day: "numeric", month: "short" });
  const fmtDayLong = str => parseDay(str).toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });

  function showTip(evt, rows) {
    tip.replaceChildren();
    rows.forEach(r => {
      const row = document.createElement("div");
      row.className = "tt-row" + (r.head ? " tt-head" : "");
      if (r.color) {
        const key = document.createElement("span");
        key.className = "tt-key";
        key.style.background = r.color;
        row.appendChild(key);
      }
      if (r.value !== undefined) {
        const v = document.createElement("strong");
        v.textContent = r.value;
        row.appendChild(v);
      }
      const l = document.createElement("span");
      l.textContent = r.label;
      row.appendChild(l);
      tip.appendChild(row);
    });
    tip.hidden = false;
    const pad = 14;
    const w = tip.offsetWidth, h = tip.offsetHeight;
    let x = evt.clientX + pad, y = evt.clientY + pad;
    if (x + w > window.innerWidth - 8) x = evt.clientX - w - pad;
    if (y + h > window.innerHeight - 8) y = evt.clientY - h - pad;
    tip.style.left = Math.max(8, x) + "px";
    tip.style.top = Math.max(8, y) + "px";
  }
  function hideTip() { tip.hidden = true; }

  function xTicks(n, plotW) {
    const want = Math.max(2, Math.min(7, Math.floor(plotW / 80)));
    const step = Math.max(1, Math.round((n - 1) / (want - 1)));
    const out = [];
    for (let i = 0; i < n; i += step) out.push(i);
    if (n - 1 - out[out.length - 1] > step / 2) out.push(n - 1);
    return out;
  }

  /* Line chart over daily rows. */
  function line(el, o) {
    const data = o.data;
    el.replaceChildren();
    if (!data.length) { el.textContent = "No data yet."; return; }
    const W = Math.max(280, el.clientWidth || 600);
    const rugs = o.rugs || [];
    const rugH = 14;
    const left = rugs.length ? 96 : 40, right = 14, top = 12, bottom = 24;
    const H = o.height || 220;
    const plotH = H - top - bottom;
    const totalH = H + (rugs.length ? rugs.length * rugH + 10 : 0);
    const svg = s("svg", { viewBox: `0 0 ${W} ${totalH}`, width: "100%", height: totalH, role: "img", "aria-label": o.label || "chart" }, el);
    const plotW = W - left - right;
    const n = data.length;
    const x = i => left + (n === 1 ? plotW / 2 : (i / (n - 1)) * plotW);
    const vals = [];
    data.forEach(r => {
      o.series.forEach(se => { if (r[se.key] != null) vals.push(+r[se.key]); });
      if (o.band && r[o.band.low] != null) vals.push(+r[o.band.low], +r[o.band.high]);
    });
    (o.refLines || []).forEach(rl => vals.push(rl.y));
    let lo = o.yMin != null ? o.yMin : Math.min(...vals), hi = o.yMax != null ? o.yMax : Math.max(...vals);
    if (o.yMin == null) lo -= (hi - lo) * 0.08;
    if (o.yMax == null) hi += (hi - lo) * 0.08;
    const ticks = niceTicks(lo, hi, 4);
    lo = Math.min(lo, ticks[0]); hi = Math.max(hi, ticks[ticks.length - 1]);
    const y = v => top + plotH - ((v - lo) / (hi - lo)) * plotH;
    ticks.forEach(t => {
      s("line", { x1: left, x2: W - right, y1: y(t), y2: y(t), class: "grid" }, svg);
      text(svg, left - 6, y(t) + 4, (o.fmt || (v => v))(t), "ax", "end");
    });
    xTicks(n, plotW).forEach(i => text(svg, x(i), H - 6, fmtDay(data[i].date), "ax", "middle"));
    if (o.band) {
      let d = "", back = [];
      let started = false;
      data.forEach((r, i) => {
        if (r[o.band.low] == null || r[o.band.high] == null) return;
        d += (started ? "L" : "M") + x(i).toFixed(1) + "," + y(r[o.band.high]).toFixed(1);
        back.unshift("L" + x(i).toFixed(1) + "," + y(r[o.band.low]).toFixed(1));
        started = true;
      });
      if (started) s("path", { d: d + back.join("") + "Z", class: "band" }, svg);
    }
    (o.refLines || []).forEach(rl => {
      s("line", { x1: left, x2: W - right, y1: y(rl.y), y2: y(rl.y), class: "ref " + (rl.cls || "") }, svg);
      text(svg, W - right - 2, y(rl.y) - 4, rl.label, "ax ref-label", "end");
    });
    o.series.forEach(se => {
      let d = "", pen = false;
      data.forEach((r, i) => {
        const v = r[se.key];
        if (v == null) { pen = false; return; }
        d += (pen ? "L" : "M") + x(i).toFixed(1) + "," + y(v).toFixed(1);
        pen = true;
      });
      s("path", { d, class: "ln", style: `stroke:${se.color}` }, svg);
      for (let i = n - 1; i >= 0; i--) {
        if (data[i][se.key] != null) {
          s("circle", { cx: x(i), cy: y(data[i][se.key]), r: 4, class: "dot", style: `fill:${se.color}` }, svg);
          break;
        }
      }
    });
    rugs.forEach((rg, k) => {
      const ry = H + 6 + k * rugH;
      text(svg, left - 8, ry + 10, rg.label, "ax rug-label", "end");
      s("line", { x1: left, x2: W - right, y1: ry + rugH / 2, y2: ry + rugH / 2, class: "grid" }, svg);
      data.forEach((r, i) => {
        if (rg.test(r)) s("rect", { x: x(i) - 1.5, y: ry + 2, width: 3, height: rugH - 4, rx: 1.5, class: "rug" }, svg);
      });
    });
    // Crosshair + tooltip
    const cross = s("line", { y1: top, y2: totalH - 2, class: "cross", visibility: "hidden" }, svg);
    const hit = s("rect", { x: left, y: 0, width: plotW, height: totalH, fill: "transparent", tabindex: 0 }, svg);
    const at = i => {
      const r = data[i];
      cross.setAttribute("x1", x(i)); cross.setAttribute("x2", x(i)); cross.setAttribute("visibility", "visible");
      const rows = [{ head: true, label: fmtDayLong(r.date) }];
      o.series.forEach(se => rows.push({ color: se.color, value: r[se.key] != null ? (o.fmt || (v => v))(r[se.key]) + (se.unit ? " " + se.unit : "") : "–", label: se.label }));
      if (o.band && r[o.band.low] != null) rows.push({ value: `${r[o.band.low]}–${r[o.band.high]}`, label: o.band.label });
      if (o.extraTip) o.extraTip(r).forEach(t => rows.push(t));
      return rows;
    };
    const move = evt => {
      const pt = svg.getBoundingClientRect();
      const px = (evt.clientX - pt.left) * (W / pt.width);
      const i = Math.max(0, Math.min(n - 1, Math.round(((px - left) / plotW) * (n - 1))));
      showTip(evt, at(i));
    };
    hit.addEventListener("pointermove", move);
    hit.addEventListener("pointerleave", () => { hideTip(); cross.setAttribute("visibility", "hidden"); });
    hit.addEventListener("focus", () => {
      const b = svg.getBoundingClientRect();
      showTip({ clientX: b.right - 40, clientY: b.top + 20 }, at(n - 1));
    });
    hit.addEventListener("blur", hideTip);
  }

  /* Daily columns with an optional threshold line. */
  function columns(el, o) {
    const data = o.data;
    el.replaceChildren();
    if (!data.length) { el.textContent = "No data yet."; return; }
    const W = Math.max(280, el.clientWidth || 600), H = o.height || 180;
    const left = 40, right = 14, top = 12, bottom = 24;
    const plotW = W - left - right, plotH = H - top - bottom;
    const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, width: "100%", height: H, role: "img", "aria-label": o.label || "chart" }, el);
    const n = data.length;
    const band = plotW / n;
    const bw = Math.max(1, Math.min(24, band - 2));
    const vals = data.map(r => r[o.key] || 0);
    const hi0 = Math.max(...vals, ...(o.refLines || []).map(r => r.y), 1);
    const ticks = niceTicks(0, hi0, 4);
    const hi = ticks[ticks.length - 1];
    const y = v => top + plotH - (v / hi) * plotH;
    ticks.forEach(t => {
      s("line", { x1: left, x2: W - right, y1: y(t), y2: y(t), class: "grid" }, svg);
      text(svg, left - 6, y(t) + 4, t, "ax", "end");
    });
    xTicks(n, plotW).forEach(i => text(svg, left + band * (i + 0.5), H - 6, fmtDay(data[i].date), "ax", "middle"));
    data.forEach((r, i) => {
      const v = r[o.key] || 0;
      if (v <= 0) return;
      const x0 = left + band * i + (band - bw) / 2, y0 = y(v), h = top + plotH - y0;
      const rad = Math.min(4, bw / 2, h);
      const d = `M${x0},${y0 + h}V${y0 + rad}Q${x0},${y0} ${x0 + rad},${y0}H${x0 + bw - rad}Q${x0 + bw},${y0} ${x0 + bw},${y0 + rad}V${y0 + h}Z`;
      const cls = o.classify ? o.classify(r) : "";
      const bar = s("path", { d, class: "col " + cls, tabindex: -1 }, svg);
      const hitbox = s("rect", { x: left + band * i, y: top, width: band, height: plotH, fill: "transparent" }, svg);
      const show = evt => showTip(evt, [{ head: true, label: fmtDayLong(r.date) }, { value: Math.round(v), label: o.unitLabel || "" }]
        .concat(o.extraTip ? o.extraTip(r) : []));
      hitbox.addEventListener("pointermove", e => { bar.classList.add("hover"); show(e); });
      hitbox.addEventListener("pointerleave", () => { bar.classList.remove("hover"); hideTip(); });
    });
    (o.refLines || []).forEach(rl => {
      s("line", { x1: left, x2: W - right, y1: y(rl.y), y2: y(rl.y), class: "ref " + (rl.cls || "") }, svg);
      text(svg, W - right - 2, y(rl.y) - 4, rl.label, "ax ref-label", "end");
    });
  }

  /* Horizontal diverging bars with an interval whisker per row. */
  function diverging(el, o) {
    const rows = o.rows;
    el.replaceChildren();
    if (!rows.length) { el.textContent = "Not enough tagged nights yet."; return; }
    const W = Math.max(280, el.clientWidth || 600);
    const rowH = 34, top = 8, bottom = 24;
    const labelW = Math.min(130, W * 0.34);
    const left = labelW + 8, right = 46;
    const H = top + rows.length * rowH + bottom;
    const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, width: "100%", height: H, role: "img", "aria-label": o.label || "chart" }, el);
    const ext = Math.max(1, ...rows.flatMap(r => [Math.abs(r.value || 0), Math.abs(r.lo || 0), Math.abs(r.hi || 0)]));
    const ticks = niceTicks(-ext, ext, 4);
    const lo = ticks[0], hi = ticks[ticks.length - 1];
    const plotW = W - left - right;
    const x = v => left + ((v - lo) / (hi - lo)) * plotW;
    ticks.forEach(t => {
      s("line", { x1: x(t), x2: x(t), y1: top, y2: H - bottom, class: t === 0 ? "base" : "grid" }, svg);
      text(svg, x(t), H - 6, (t > 0 ? "+" : "") + t, "ax", "middle");
    });
    rows.forEach((r, i) => {
      const cy = top + i * rowH + rowH / 2;
      text(svg, labelW, cy + 4, r.label, "lbl", "end");
      if (r.value == null) {
        text(svg, x(0) + 6, cy + 4, "not enough data", "ax");
        return;
      }
      const bh = 14;
      const x0 = Math.min(x(0), x(r.value)), w = Math.abs(x(r.value) - x(0));
      const neg = r.value < 0;
      const rad = Math.min(4, w);
      const yy = cy - bh / 2;
      const d = neg
        ? `M${x(0)},${yy}H${x0 + rad}Q${x0},${yy} ${x0},${yy + rad}V${yy + bh - rad}Q${x0},${yy + bh} ${x0 + rad},${yy + bh}H${x(0)}Z`
        : `M${x(0)},${yy}H${x0 + w - rad}Q${x0 + w},${yy} ${x0 + w},${yy + rad}V${yy + bh - rad}Q${x0 + w},${yy + bh} ${x0 + w - rad},${yy + bh}H${x(0)}Z`;
      const bar = s("path", { d, class: "dv " + (neg !== !!o.higherIsWorse ? "dv-bad" : "dv-good") + (r.muted ? " dv-muted" : "") }, svg);
      if (r.lo != null && r.hi != null) {
        s("line", { x1: x(r.lo), x2: x(r.hi), y1: cy, y2: cy, class: "whisker" }, svg);
        s("line", { x1: x(r.lo), x2: x(r.lo), y1: cy - 4, y2: cy + 4, class: "whisker" }, svg);
        s("line", { x1: x(r.hi), x2: x(r.hi), y1: cy - 4, y2: cy + 4, class: "whisker" }, svg);
      }
      const vx = neg ? Math.min(x(r.value), r.lo != null ? x(r.lo) : x(r.value)) - 4 : Math.max(x(r.value), r.hi != null ? x(r.hi) : x(r.value)) + 4;
      text(svg, vx, cy + 4, (r.value > 0 ? "+" : "") + r.value + (o.unit ? " " + o.unit : ""), "val", neg ? "end" : "start");
      const hitbox = s("rect", { x: 0, y: cy - rowH / 2, width: W, height: rowH, fill: "transparent" }, svg);
      hitbox.addEventListener("pointermove", e => { bar.classList.add("hover"); showTip(e, r.tip); });
      hitbox.addEventListener("pointerleave", () => { bar.classList.remove("hover"); hideTip(); });
    });
  }

  /* Tiny trend line with an emphasised endpoint. */
  function spark(el, values, o) {
    o = o || {};
    el.replaceChildren();
    const pts = values.map((v, i) => [i, v]).filter(p => p[1] != null);
    if (pts.length < 2) return;
    const W = o.width || 120, H = o.height || 32, pad = 5;
    const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, "aria-hidden": "true" }, el);
    const vs = pts.map(p => p[1]);
    const lo = Math.min(...vs), hi = Math.max(...vs);
    const x = i => pad + (i / (values.length - 1)) * (W - 2 * pad);
    const y = v => H - pad - (hi === lo ? 0.5 : (v - lo) / (hi - lo)) * (H - 2 * pad);
    const d = pts.map((p, k) => (k ? "L" : "M") + x(p[0]).toFixed(1) + "," + y(p[1]).toFixed(1)).join("");
    s("path", { d: d + `L${x(pts[pts.length - 1][0])},${H}L${x(pts[0][0])},${H}Z`, class: "spark-area" }, svg);
    s("path", { d, class: "ln spark" }, svg);
    const last = pts[pts.length - 1];
    s("circle", { cx: x(last[0]), cy: y(last[1]), r: 3.5, class: "dot spark-dot" }, svg);
  }

  window.Charts = { line, columns, diverging, spark, showTip, hideTip, fmtDay, fmtDayLong, parseDay };
})();
