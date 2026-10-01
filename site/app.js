/* Morning Check: renders the JSON written by `python -m fitapp`.
   Real data arrives encrypted (data/data.enc.json) and is decrypted here with
   the passphrase; without it the page falls back to data/demo.json. */
(function () {
  const C = window.Charts;
  const app = document.getElementById("app");
  const PASS_KEY = "morningcheck.pass";
  const TABS = [["today", "Today"], ["events", "Events"], ["recovery", "Recovery"], ["tournaments", "Tournaments"], ["strength", "Strength"], ["load", "Load & injury"]];
  let DATA = null;
  let recRange = 90;
  let recMetric = "hrv";

  // ---------- tiny DOM helper (strings always go in as text) ----------
  function h(tag, attrs, ...kids) {
    const el = document.createElement(tag);
    for (const k in attrs || {}) {
      const v = attrs[k];
      if (v == null || v === false) continue;
      if (k === "class") el.className = v;
      else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, v === true ? "" : v);
    }
    kids.flat(Infinity).forEach(c => {
      if (c == null || c === false) return;
      el.appendChild(typeof c === "string" || typeof c === "number" ? document.createTextNode(String(c)) : c);
    });
    return el;
  }
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* private mode */ } },
    del(k) { try { localStorage.removeItem(k); } catch (e) { /* ignore */ } },
  };
  const fmt = (v, d = 0) => (v == null || Number.isNaN(v) ? "–" : Number(v).toFixed(d));
  const signed = (v, d = 1) => (v == null ? "–" : (v > 0 ? "+" : "") + Number(v).toFixed(d));
  const day = s => C.fmtDayLong(String(s).slice(0, 10));
  const STATUS_WORD = { red: "Red day", amber: "Amber day", green: "Green day", unknown: "No reading yet" };
  const STATUS_CHIP = { red: "Take it easy", amber: "Train with a cap", green: "Go hard", unknown: "Waiting for sync" };
  const STATUS_MARK = { red: "✕", amber: "!", green: "✓", unknown: "·" };
  const chip = (cls, label) => h("span", { class: "chip " + cls }, label);

  // ---------- loading + decryption ----------
  function b64(str) { return Uint8Array.from(atob(str), c => c.charCodeAt(0)); }
  async function decrypt(env, pass) {
    const enc = new TextEncoder();
    const base = await crypto.subtle.importKey("raw", enc.encode(pass), "PBKDF2", false, ["deriveKey"]);
    const key = await crypto.subtle.deriveKey(
      { name: "PBKDF2", salt: b64(env.salt), iterations: env.iter, hash: "SHA-256" },
      base, { name: "AES-GCM", length: 256 }, false, ["decrypt"]);
    const plain = await crypto.subtle.decrypt({ name: "AES-GCM", iv: b64(env.iv) }, key, b64(env.ct));
    return JSON.parse(new TextDecoder().decode(plain));
  }
  async function fetchJson(path) {
    try {
      const r = await fetch(path, { cache: "no-store" });
      return r.ok ? await r.json() : null;
    } catch (e) { return null; }
  }
  async function boot() {
    if (window.__MORNING_CHECK_DATA__) return start(window.__MORNING_CHECK_DATA__);
    const forceDemo = location.hash === "#demo";
    const env = forceDemo ? null : await fetchJson("data/data.enc.json");
    if (env && env.ct) {
      const saved = store.get(PASS_KEY);
      if (saved) {
        try { return start(await decrypt(env, saved)); } catch (e) { store.del(PASS_KEY); }
      }
      return lockScreen(env);
    }
    const demo = await fetchJson("data/demo.json");
    if (demo) return start(demo);
    app.replaceChildren(h("div", { class: "lock" }, h("h2", null, "No data yet"),
      h("p", { class: "note" }, "The daily GitHub Action hasn't published anything. Run the \"Refresh dashboard\" workflow once from the Actions tab.")));
  }
  function lockScreen(env) {
    const input = h("input", { type: "password", id: "pass", autocomplete: "current-password", placeholder: "Passphrase", "aria-label": "Passphrase" });
    const remember = h("input", { type: "checkbox", id: "remember", checked: true });
    const err = h("p", { class: "err", role: "alert" });
    const btn = h("button", { class: "btn", type: "submit" }, "Unlock");
    const form = h("form", { class: "lock" },
      h("p", { class: "eyebrow" }, "Morning Check"),
      h("h2", null, "Your recovery data is locked"),
      h("p", { class: "note" }, "It is encrypted before it leaves GitHub. Enter the DASHBOARD_PASSPHRASE you saved as a repository secret."),
      input, h("label", { class: "check", for: "remember" }, remember, "Remember on this device"), btn, err,
      h("a", { href: "#demo", onclick: () => setTimeout(() => location.reload(), 0) }, "Look at the demo instead"));
    form.addEventListener("submit", async e => {
      e.preventDefault();
      btn.disabled = true; err.textContent = "";
      try {
        const data = await decrypt(env, input.value);
        if (remember.checked) store.set(PASS_KEY, input.value);
        start(data);
      } catch (x) {
        err.textContent = "That passphrase didn't unlock the data. Check it matches the DASHBOARD_PASSPHRASE secret exactly.";
        btn.disabled = false;
      }
    });
    app.replaceChildren(form);
    input.focus();
  }

  // ---------- shell ----------
  function start(data) {
    DATA = data;
    render();
    window.addEventListener("hashchange", render);
    let t;
    window.addEventListener("resize", () => { clearTimeout(t); t = setTimeout(renderTab, 150); });
  }
  function currentTab() {
    const id = location.hash.replace("#", "");
    return TABS.some(([k]) => k === id) ? id : "today";
  }
  function render() {
    const d = DATA;
    const gen = new Date(d.generated_at);
    const ageH = (Date.now() - gen.getTime()) / 36e5;
    const top = h("header", { class: "top" },
      h("div", { class: "brand" }, "Morning Check ", h("span", null, "· " + day(d.today_date))),
      h("div", { class: "top-meta" },
        h("span", null, "Updated " + gen.toLocaleString(undefined, { weekday: "short", hour: "2-digit", minute: "2-digit" })),
        ageH > 26 && !d.demo ? chip("amber", "Stale") : null,
        !d.demo && store.get(PASS_KEY) ? h("button", { class: "linkbtn", onclick: () => { store.del(PASS_KEY); location.reload(); } }, "Lock") : null));
    const banner = d.demo
      ? h("div", { class: "banner" }, h("strong", null, "Demo data. "), "Nothing here is yours yet. Add your Garmin, Keep and Calendar secrets (see the README) and the next run publishes your real numbers.")
      : null;
    const tabs = h("nav", { class: "tabs", role: "tablist", "aria-label": "Sections" },
      TABS.map(([id, label]) => h("button", {
        class: "tab", role: "tab", "aria-selected": String(currentTab() === id),
        onclick: () => { if (location.hash !== "#" + id) location.hash = id; else renderTab(); },
      }, label)));
    const panel = h("main", { id: "panel", class: "tabpanel", role: "tabpanel" });
    const footer = h("footer", { class: "footer" },
      Object.entries(d.sources || {}).map(([k, v]) => h("span", null, `${k[0].toUpperCase() + k.slice(1)}: ${v}`)),
      h("span", null, "Max HR used: " + fmt(d.athlete && d.athlete.max_hr)));
    app.replaceChildren(...[top, banner, verdictCard(d.today), tabs, panel, footer].filter(Boolean));
    renderTab();
  }
  function renderTab() {
    const panel = document.getElementById("panel");
    if (!panel) return;
    const tab = currentTab();
    document.querySelectorAll(".tab").forEach((b, i) => b.setAttribute("aria-selected", String(TABS[i][0] === tab)));
    panel.replaceChildren();
    ({ today: renderToday, events: renderEvents, recovery: renderRecovery, tournaments: renderTournaments, strength: renderStrength, load: renderLoad })[tab](panel);
  }
  const go = id => h("a", { href: "#" + id }, "Open");

  // ---------- verdict ----------
  function verdictCard(t) {
    const st = t.status || "unknown";
    return h("section", { class: "verdict " + st, "aria-label": "This morning's verdict" },
      h("div", { class: "verdict-head" },
        h("h1", { class: "verdict-word" }, STATUS_WORD[st]),
        chip(st, STATUS_CHIP[st])),
      h("p", { class: "verdict-sum" }, t.summary),
      t.signals && t.signals.length ? h("div", { class: "tiles" }, t.signals.map(sg =>
        h("div", { class: "tile" },
          h("span", { class: "tile-label" }, sg.label),
          h("span", { class: "tile-value" }, sg.display),
          chip(sg.level, { red: "Low", amber: "Watch", green: "Good" }[sg.level] || sg.level),
          sg.detail ? h("span", { class: "tile-detail" }, sg.detail) : null))) : null);
  }

  // ---------- Today ----------
  function renderToday(panel) {
    const d = DATA, t = d.today;
    const strip = h("div", { class: "strip", role: "list", "aria-label": "Last 14 mornings" },
      t.strip.map((s, i) => h("div", { class: "strip-cell" + (i === t.strip.length - 1 ? " today" : ""), role: "listitem", title: `${day(s.date)}: ${s.status}` },
        h("span", { class: "strip-dot " + s.status, "aria-label": s.status }, STATUS_MARK[s.status]),
        h("span", null, C.parseDay(s.date).toLocaleDateString(undefined, { weekday: "narrow" })))));
    const counts = t.strip.reduce((a, s) => ((a[s.status] = (a[s.status] || 0) + 1), a), {});

    panel.append(h("div", { class: "grid2" },
      h("div", { class: "stack" }, calendarCard(t), stripCard()),
      h("div", { class: "stack" }, injurySummary(d.injury), strengthSummary(d.overload), latestTournament(d.tournaments))));

    function stripCard() {
      return h("section", { class: "card" },
        h("div", { class: "card-head" }, h("h2", null, "Last two weeks"),
          h("span", { class: "small muted" }, `${counts.green || 0} green · ${counts.amber || 0} amber · ${counts.red || 0} red`)),
        strip);
    }
  }
  function timeOf(v, allDay) {
    if (allDay || String(v).length <= 10) return "All day";
    return new Date(v).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  }
  function calendarCard(t) {
    const card = h("section", { class: "card" }, h("div", { class: "card-head" }, h("h2", null, "Today's plan"),
      t.calendar ? chip("plain accent", { apply: "Auto-swap on", suggest: "Suggest only", off: "Swapper off" }[t.mode] || t.mode) : null));
    if (!t.calendar) {
      card.append(h("p", { class: "note" }, t.status === "red"
        ? "Today is red. Swap any intervals, tempo or heavy lifting for an easy Z2 session or mobility. Connect Google Calendar (README, step 4) and this happens automatically."
        : "Connect Google Calendar (README, step 4) to let the readiness swapper move hard sessions off red days."));
      return card;
    }
    if (t.actions.length) {
      card.append(h("div", { class: "rows" }, t.actions.map(a => h("div", { class: "row" },
        h("div", null,
          h("span", { class: "strike" }, a.title), h("span", { class: "arrow" }, "→"),
          h("span", { class: "row-title" }, a.light.title)),
        chip(String(a.status).startsWith("applied") ? "green" : String(a.status).startsWith("failed") ? "red" : "plain", a.status),
        h("p", { class: "row-sub" }, (a.moved_to ? `Hard session moved to ${day(a.moved_to)} at ${timeOf(a.start, a.all_day)}. ` : "No free day this week, so it was replaced, not moved. ") + (a.light.description || ""))))));
    } else {
      card.append(h("p", { class: "note" }, t.status === "red" ? "Red day, but there's no hard session left on today's calendar." : "Nothing to change today."));
    }
    if (t.week && t.week.length) {
      card.append(h("h3", null, "Coming up"), h("div", { class: "rows" }, t.week.slice(0, 8).map(ev => h("div", { class: "row" },
        h("div", null, h("span", { class: "row-title" }, ev.title), h("span", { class: "muted small" }, " · " + day(ev.start) + ", " + timeOf(ev.start, ev.all_day))),
        chip(ev.kind === "protected" ? "plain accent" : ev.kind === "hard" ? "amber" : "green",
          ev.kind === "protected" ? "Event" : ev.kind === "hard" ? "Hard" : ev.role === "light" ? "Swapped in" : "Easy")))));
    }
    return card;
  }
  function injurySummary(inj) {
    const c = inj.current;
    return h("section", { class: "card" },
      h("div", { class: "card-head" }, h("h2", null, "Injury risk"), chip(c.risk, c.risk + " risk")),
      c.flags.length ? h("div", { class: "rows" }, c.flags.map(f => h("div", { class: "row" }, h("span", null, f.text), chip(f.level, f.level))))
        : h("p", { class: "note" }, "No warning patterns this week: enough rest, no load spike, no back-to-back hard days."),
      inj.matches_past && inj.matches_past.length ? h("p", { class: "note" },
        h("strong", null, "Looks like before your " + inj.matches_past[0].label.toLowerCase() + ": "),
        inj.matches_past[0].shared.join(", ") + " pattern" + (inj.matches_past[0].shared.length > 1 ? "s" : "") + " match.") : null,
      h("p", { class: "small muted" }, `Load ratio ${fmt(c.acwr, 2)} · ${c.rest_days_7} rest day${c.rest_days_7 === 1 ? "" : "s"} in 7 · `, go("load")));
  }
  function strengthSummary(ov) {
    const t = (ov.templates || []).find(x => x.up_next);
    const card = h("section", { class: "card" }, h("div", { class: "card-head" }, h("h2", null, "Next gym session"), t ? chip("plain accent", t.name) : null));
    if (!t) {
      card.append(h("p", { class: "note" }, ov.sessions_logged ? "No session in the last six weeks to build from." : "No gym log found yet. Check the Keep note title in config.yml."));
      return card;
    }
    card.append(h("div", { class: "rows" }, t.exercises.slice(0, 5).map(e => h("div", { class: "row" },
      h("span", { class: "row-title" }, e.name), h("span", { class: "num" }, targetText(e.next))))),
      h("p", { class: "small muted" }, garminLine(t) + " · ", go("strength")));
    return card;
  }
  function latestTournament(ts) {
    if (!ts || !ts.length) return null;
    const t = ts[0];
    return h("section", { class: "card" },
      h("div", { class: "card-head" }, h("h2", null, t.name), h("span", { class: "small muted" }, `${day(t.start)}${t.days > 1 ? " – " + day(t.end) : ""}`)),
      h("p", { class: "note" }, `${t.games.length} games, load ${fmt(t.total_load)}. ` + reboundText(t)),
      h("p", { class: "small muted" }, go("tournaments")));
  }
  function reboundText(t) {
    if (t.rebound_status === "rebounded") return `HRV back to baseline after ${t.rebound_days} day${t.rebound_days === 1 ? "" : "s"}.`;
    if (t.rebound_status === "pending") return "HRV hasn't rebounded yet.";
    if (t.rebound_status === "not_within_14d") return "HRV stayed below baseline for two weeks.";
    return "No HRV data around this event.";
  }

  // ---------- Events ----------
  const SURFACE = { beach: "Beach", grass: "Grass", turf: "Turf", indoor: "Indoor" };
  function countdown(n) {
    if (n <= 0) return "Now";
    if (n === 1) return "Tomorrow";
    return n < 21 ? `In ${n} days` : `In ${Math.round(n / 7)} weeks`;
  }
  function flightRows(list) {
    return h("div", { class: "rows flights" }, list.map(f => {
      const dep = new Date(f.depart), arr = new Date(f.arrive);
      const t = x => x.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
      const overnight = arr.toDateString() !== dep.toDateString();
      return h("div", { class: "row" },
        h("div", null,
          h("span", { class: "row-title" }, "✈ " + (f.to ? "To " + f.to : f.title)),
          h("span", { class: "muted small" }, " · " + day(f.depart.slice(0, 10)))),
        h("span", { class: "num" }, `${t(dep)} → ${t(arr)}${overnight ? " +1" : ""}`),
        h("p", { class: "row-sub" }, [f.code, f.from ? "from " + f.from : null].filter(Boolean).join(" · ")));
    }));
  }
  function renderEvents(panel) {
    const evs = DATA.events || [];
    const travel = DATA.travel || [];
    const travelCard = travel.length ? h("section", { class: "card" }, h("h2", null, "Other flights"), flightRows(travel),
      h("p", { class: "small muted" }, "Times are shown in your phone's time zone.")) : null;
    if (!evs.length) {
      const cal = (DATA.sources || {}).calendar || "";
      panel.append(h("section", { class: "card" }, h("h2", null, "No upcoming events"),
        h("p", { class: "note" }, cal.startsWith("ok")
          ? "Nothing in the next year matches your event words (tryouts, Pesca, Disco, EBUCC, hat…). Add more words under events.keywords in config.yml."
          : "Events come from your Google Calendar, which isn't connected yet. Fix the calendar connection (see the footer for the error), then the next run fills this tab.")), travelCard);
      return;
    }
    panel.append(h("div", { class: "stack" },
      h("p", { class: "note" }, "Future frisbee events from your calendar. Put the venue or town in a calendar entry's location field and it shows here. Hard sessions are never moved onto these days or the day before."),
      h("div", { class: "grid2" }, evs.map(eventCard)), travelCard));
  }
  function eventCard(e) {
    const i = e.info;
    const dates = day(e.start) + (e.days > 1 ? " – " + day(e.end) : "");
    const place = i ? [i.venue, [i.city, i.country].filter(Boolean).join(", ")].filter(Boolean).join(" · ") : null;
    const facts = i ? [i.surface && i.surface !== "unknown" ? SURFACE[i.surface] : null, i.division,
      e.distance_km != null ? `${e.distance_km.toLocaleString()} km from home` : null].filter(Boolean) : [];
    return h("section", { class: "card event" },
      h("div", { class: "card-head" },
        h("div", null, h("h2", null, e.title), h("span", { class: "small muted" }, dates)),
        chip(e.days_until <= 7 ? "amber" : "plain accent", countdown(e.days_until))),
      i ? h("div", { class: "event-body" },
        i.full_name && i.full_name.toLowerCase() !== e.title.toLowerCase() ? h("p", { class: "row-title" }, i.full_name) : null,
        place ? h("p", { class: "event-place" }, place) : h("p", { class: "muted" }, "Location not confirmed"),
        facts.length ? h("p", { class: "small muted" }, facts.join(" · ")) : null,
        i.summary ? h("p", { class: "note" }, i.summary) : null,
        h("p", { class: "small" },
          i.website && /^https?:\/\//.test(i.website) ? h("a", { href: i.website, target: "_blank", rel: "noopener noreferrer" }, "Event page") : null,
          i.website ? " · " : null,
          h("span", { class: "muted" }, `Found with web search · ${i.confidence} confidence`)))
        : e.calendar_location ? h("p", { class: "event-place" }, e.calendar_location)
        : h("p", { class: "note muted" }, e.source === "config"
          ? "From config.yml. Add it to your calendar with a location to show where it is."
          : "No location yet. Add the venue or town to this calendar entry's location field."),
      e.flights && e.flights.length ? [h("h3", null, "Flights"), flightRows(e.flights),
        h("p", { class: "small muted" }, "Times are shown in your phone's time zone.")] : null);
  }

  // ---------- Recovery ----------
  function renderRecovery(panel) {
    const rec = DATA.recovery;
    const rows = rec.timeline.slice(-recRange);
    const tags = Object.keys(rec.tag_labels || {}).filter(k => rows.some(r => r.tags.includes(k)));
    const rangeSeg = h("div", { class: "seg", role: "group", "aria-label": "Date range" },
      [30, 90, 180].map(n => h("button", { "aria-pressed": String(recRange === n), onclick: () => { recRange = n; renderTab(); } }, `${n} days`)));
    const hrvChart = h("div", { class: "chart" });
    const sleepChart = h("div", { class: "chart" });
    panel.append(h("div", { class: "filters" }, rangeSeg), h("div", { class: "stack", style: "margin-top:14px" },
      h("section", { class: "card" },
        h("div", { class: "card-head" }, h("h2", null, "Overnight HRV"), h("span", { class: "small muted" }, "Ticks mark the evening before")),
        h("div", { class: "legend" }, h("span", null, h("i", { style: "background:var(--accent)" }), "HRV (ms)"), h("span", null, h("i", { class: "box", style: "background:var(--accent)" }), "Garmin baseline band")),
        hrvChart),
      h("section", { class: "card" }, h("h2", null, "Sleep score"), sleepChart),
      effectsCard(rec)));
    const extraTip = r => r.tags.length ? [{ label: "After: " + r.tags.map(k => rec.tag_labels[k] || k).join(", ") }] : [];
    C.line(hrvChart, {
      data: rows, label: "Overnight HRV", height: 230, fmt: v => Math.round(v),
      series: [{ key: "hrv", label: "HRV", color: "var(--accent)", unit: "ms" }],
      band: { low: "hrv_low", high: "hrv_high", label: "Baseline band" },
      rugs: tags.map(k => ({ label: rec.tag_labels[k], test: r => r.tags.includes(k) })),
      extraTip,
    });
    C.line(sleepChart, {
      data: rows, label: "Sleep score", height: 180, fmt: v => Math.round(v), yMax: 100,
      series: [{ key: "sleep_score", label: "Sleep score", color: "var(--sleep)" }], extraTip,
    });
  }
  function effectsCard(rec) {
    const metricInfo = { hrv: ["HRV", "ms", false], sleep_score: ["Sleep score", "pts", false], rhr: ["Resting HR", "bpm", true] };
    const [mLabel, unit, higherIsWorse] = metricInfo[recMetric];
    const seg = h("div", { class: "seg", role: "group", "aria-label": "Metric" },
      Object.entries(metricInfo).map(([k, v]) => h("button", { "aria-pressed": String(recMetric === k), onclick: () => { recMetric = k; renderTab(); } }, v[0])));
    const chart = h("div", { class: "chart" });
    const effects = rec.effects.slice().sort((a, b) => ((a[recMetric] || {}).delta ?? 99) - ((b[recMetric] || {}).delta ?? 99));
    const table = h("table", null,
      h("thead", null, h("tr", null, h("th", null, "Evening before"), h("th", { class: "num" }, "Nights"), h("th", { class: "num" }, "HRV"), h("th", { class: "num" }, "Sleep"), h("th", { class: "num" }, "RHR"), h("th", null, "Read"))),
      h("tbody", null, rec.effects.map(e => h("tr", null,
        h("td", null, e.label, e.overlaps && e.overlaps.length ? h("div", { class: "small muted" }, "Mostly with " + e.overlaps.map(o => (rec.tag_labels[o.key] || o.key).toLowerCase()).join(", ")) : null),
        h("td", { class: "num" }, e.hrv.n),
        h("td", { class: "num" }, e.hrv.delta != null ? signed(e.hrv.delta) + " ms" : "–"),
        h("td", { class: "num" }, e.sleep_score.delta != null ? signed(e.sleep_score.delta) : "–"),
        h("td", { class: "num" }, e.rhr.delta != null ? signed(e.rhr.delta) : "–"),
        h("td", null, confidenceText(e.hrv.confidence))))));
    const card = h("section", { class: "card" },
      h("div", { class: "card-head" }, h("h2", null, "What hits your recovery"), seg),
      h("p", { class: "note" }, `Next-morning ${mLabel === "HRV" ? mLabel : mLabel.toLowerCase()} after each kind of evening, compared with your own 21-day baseline. Whiskers show the 90% range; bars that cross zero aren't a reliable effect yet.`),
      chart, h("div", { class: "tablewrap" }, table),
      h("p", { class: "small muted" }, "Alcohol comes from Garmin lifestyle logging or your \"recovery tags\" Keep note (lines like \"27/09 alcohol\"). Late training, travel and tournament days are detected from your activities."));
    requestAnimationFrame(() => C.diverging(chart, {
      label: "Effect on " + mLabel, unit, higherIsWorse,
      rows: effects.map(e => {
        const m = e[recMetric] || {};
        return {
          label: e.label, value: m.confidence === "too_few" ? null : m.delta,
          lo: m.ci ? m.ci[0] : null, hi: m.ci ? m.ci[1] : null, muted: m.confidence !== "clear",
          tip: [{ head: true, label: e.label }, { value: signed(m.delta) + " " + unit, label: mLabel + " vs baseline" },
            { value: m.ci ? `${signed(m.ci[0])} to ${signed(m.ci[1])}` : "–", label: "90% range" }, { value: String(m.n), label: "tagged nights" }],
        };
      }),
    }));
    return card;
  }
  function confidenceText(c) {
    return { clear: "Clear effect", possible: "Possible", none: "No effect seen", too_few: "Too few nights" }[c] || c;
  }

  // ---------- Tournaments ----------
  function renderTournaments(panel) {
    const ts = DATA.tournaments || [];
    if (!ts.length) {
      panel.append(h("section", { class: "card" }, h("h2", null, "No tournaments found yet"),
        h("p", { class: "note" }, "A tournament is two or more games on consecutive days away from home (or three games, or two in one day). Games are activities of a team-sport type or with words like \"game\" or \"Burla\" in the name. Add missed ones under tournaments.manual in config.yml.")));
      return;
    }
    const maxReb = Math.max(1, ...ts.map(t => t.rebound_days || 0));
    const season = h("section", { class: "card" },
      h("div", { class: "card-head" }, h("h2", null, "Season so far"), h("span", { class: "small muted" }, `${ts.length} tournament${ts.length > 1 ? "s" : ""}`)),
      h("div", { class: "tablewrap" }, h("table", null,
        h("thead", null, h("tr", null, h("th", null, "Tournament"), h("th", { class: "num" }, "Games"), h("th", { class: "num" }, "Load"), h("th", { class: "num" }, "Fade"), h("th", { class: "num" }, "HRV drop"), h("th", null, "Rebound"))),
        h("tbody", null, ts.map(t => h("tr", { class: "clickable", onclick: () => { const el = document.getElementById("t-" + t.id); if (el) { el.open = true; el.scrollIntoView({ behavior: "smooth", block: "start" }); } } },
          h("td", null, h("strong", null, t.name), h("div", { class: "small muted" }, day(t.start) + (t.days > 1 ? " – " + day(t.end) : ""))),
          h("td", { class: "num" }, t.games.length), h("td", { class: "num" }, fmt(t.total_load)),
          h("td", { class: "num" }, t.fade_pct != null ? signed(t.fade_pct) + "%" : "–"),
          h("td", { class: "num" }, t.hrv_drop_pct != null ? signed(t.hrv_drop_pct) + "%" : "–"),
          h("td", { class: "num", style: "text-align:left" }, t.rebound_days != null
            ? [h("span", { class: "databar", style: `width:${Math.round((t.rebound_days / maxReb) * 60)}px` }), `${t.rebound_days} d`]
            : h("span", { class: "muted" }, { pending: "not yet", not_within_14d: "> 14 d", no_hrv: "no HRV" }[t.rebound_status]))))))),
      h("p", { class: "small muted" }, "Fade compares the last day with the first (heart rate as % of max). Rebound counts mornings until HRV is back within 5% of the week before."));
    panel.append(h("div", { class: "stack" }, season, ts.map((t, i) => tournamentDetail(t, i === 0))));
  }
  function tournamentDetail(t, open) {
    const chart = h("div", { class: "chart" });
    const det = h("details", { class: "t", id: "t-" + t.id, open },
      h("summary", null, h("div", null, h("h2", null, t.name), h("span", { class: "small muted" }, `${t.location || ""} · ${day(t.start)}${t.days > 1 ? " – " + day(t.end) : ""}`))),
      h("div", { class: "t-body" },
        h("div", { class: "tiles" },
          tile("Games", t.games.length, `${fmt(t.total_minutes)} min played`),
          tile("Total load", fmt(t.total_load), `${t.days} day${t.days > 1 ? "s" : ""}`),
          tile("Peak HR", t.peak_hr ? fmt(t.peak_hr) + " bpm" : "–", ""),
          tile("Intensity fade", t.fade_pct != null ? signed(t.fade_pct) + "%" : "–", t.fade_basis),
          tile("HRV low point", t.hrv_nadir ? fmt(t.hrv_nadir) + " ms" : "–", t.hrv_drop_pct != null ? `${signed(t.hrv_drop_pct)}% vs ${fmt(t.hrv_baseline)} ms before` : ""),
          tile("Rebound", t.rebound_days != null ? `${t.rebound_days} day${t.rebound_days > 1 ? "s" : ""}` : "–", reboundText(t))),
        h("h3", null, "HRV around the event"), chart,
        h("h3", null, "Day by day"),
        h("div", { class: "tablewrap" }, h("table", { class: "compact" },
          h("thead", null, h("tr", null, h("th", null, "Day"), h("th", { class: "num" }, "Games"), h("th", { class: "num" }, "Minutes"), h("th", { class: "num" }, "Load"), h("th", { class: "num" }, "HR % max"), h("th", { class: "num" }, "Peak HR"))),
          h("tbody", null, t.per_day.map(p => h("tr", null, h("td", null, `Day ${p.day}`, h("div", { class: "small muted" }, day(p.date))), h("td", { class: "num" }, p.games), h("td", { class: "num" }, fmt(p.minutes)),
            h("td", { class: "num" }, fmt(p.load)), h("td", { class: "num" }, fmt(p.avg_intensity_pct, 1)), h("td", { class: "num" }, fmt(p.peak_hr))))))),
        h("h3", null, "Per game"),
        h("div", { class: "tablewrap" }, h("table", { class: "compact" },
          h("thead", null, h("tr", null, h("th", null, "Game"), h("th", { class: "num" }, "Min"), h("th", { class: "num" }, "Avg HR"), h("th", { class: "num" }, "Peak HR"), h("th", { class: "num" }, "Load"), h("th", { class: "num" }, "Load/min"), h("th", { class: "num" }, "Anaerobic TE"))),
          h("tbody", null, t.games.map(g => h("tr", null, h("td", null, g.name || `Game ${g.n}`, h("div", { class: "small muted" }, `Day ${g.day} · ${new Date(g.start).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}`)),
            h("td", { class: "num" }, fmt(g.duration_min)), h("td", { class: "num" }, fmt(g.avg_hr)), h("td", { class: "num" }, fmt(g.max_hr)), h("td", { class: "num" }, fmt(g.load)),
            h("td", { class: "num" }, fmt(g.load_per_min, 2)), h("td", { class: "num" }, fmt(g.anaerobic_te, 1)))))))));
    const draw = () => C.line(chart, {
      data: t.hrv_series, label: "HRV around " + t.name, height: 170, fmt: v => Math.round(v),
      series: [{ key: "hrv", label: "HRV", color: "var(--accent)", unit: "ms" }],
      refLines: t.hrv_baseline ? [{ y: t.hrv_baseline, label: "Pre-event " + fmt(t.hrv_baseline) }] : [],
      rugs: [{ label: "Event", test: r => r.phase === "during" }],
    });
    if (open) requestAnimationFrame(draw);
    det.addEventListener("toggle", () => { if (det.open) draw(); });
    return det;
  }
  function tile(label, value, detail) {
    return h("div", { class: "tile" }, h("span", { class: "tile-label" }, label), h("span", { class: "tile-value" }, String(value)), detail ? h("span", { class: "tile-detail" }, detail) : null);
  }

  // ---------- Strength ----------
  function targetText(n) {
    const w = n.weight ? `${n.weight % 1 ? n.weight : n.weight.toFixed(0)} kg` : "BW";
    const reps = n.reps.every(r => r === n.reps[0]) ? `${n.reps.length}×${n.reps[0]}` : n.reps.join("/");
    return `${w} · ${reps}`;
  }
  function lastText(sets) {
    return sets.map(s => (s.w ? `${s.w}×${s.r}` : `BW×${s.r}`)).join(", ");
  }
  function garminLine(t) {
    const st = t.garmin_status || "not uploaded";
    if (st === "uploaded") return t.scheduled_for ? `On your watch, scheduled ${day(t.scheduled_for)}` : "On your watch (Garmin workouts)";
    return "Garmin: " + st;
  }
  const ACTION = { add_weight: ["green", "Add weight"], add_reps: ["plain accent", "Add reps"], hold: ["amber", "Hold"], deload: ["red", "Deload"], add_load: ["green", "Add load"] };
  function renderStrength(panel) {
    const ov = DATA.overload;
    if (!ov.templates || !ov.templates.length) {
      panel.append(h("section", { class: "card" }, h("h2", null, "No gym sessions yet"),
        h("p", { class: "note" }, "The builder reads your Google Keep note titled \"gym logs\". Start each session with a date line (\"29/09 Lower A\") and one line per lift (\"Squat 3x5 100kg\", \"Bench 80: 8,8,7\")."),
        ov.unparsed && ov.unparsed.length ? unparsedCard(ov) : null));
      return;
    }
    const cards = ov.templates.map(t => h("section", { class: "card" },
      h("div", { class: "card-head" },
        h("div", null, h("h2", null, t.name), h("span", { class: "small muted" }, `Last done ${day(t.last_date)} · ${t.times_done} time${t.times_done > 1 ? "s" : ""}`)),
        t.up_next ? chip("plain accent", "Up next") : null),
      h("div", { class: "lifts" }, t.exercises.map(e => {
        const [cls, label] = ACTION[e.next.action] || ["plain", e.next.action];
        return h("div", { class: "lift" },
          h("div", null, h("div", { class: "lift-name" }, e.name), h("div", { class: "small muted" }, `Range ${e.rep_range[0]}–${e.rep_range[1]}`)),
          h("div", { class: "lift-last small" }, h("div", { class: "muted" }, "Last " + C.fmtDay(e.last.date)), h("div", { class: "num" }, lastText(e.last.sets))),
          h("div", null, h("div", { class: "lift-target num" }, targetText(e.next)), chip(cls, label), h("div", { class: "lift-note" }, e.next.note)));
      })),
      h("p", { class: "small muted" }, garminLine(t))));
    const multiples = h("div", { class: "multiples" }, (ov.lifts || []).filter(l => l.history.length >= 2).map(l => {
      const useE1 = l.history.some(x => x.best_e1rm);
      const vals = l.history.map(x => (useE1 ? x.best_e1rm : x.total_reps));
      const cell = h("div", { class: "spark-cell" });
      C.spark(cell, vals, { width: 170, height: 34 });
      const last = vals[vals.length - 1], first = vals[0];
      return h("div", { class: "mult" }, h("span", { class: "mult-name" }, l.name),
        h("span", { class: "mult-val num" }, useE1 ? `${fmt(last)} kg` : `${last} reps`),
        h("span", { class: "small muted" }, (useE1 ? "Est. 1RM " : "Total reps ") + `${signed(last - first, useE1 ? 1 : 0)} over ${l.history.length} sessions`), cell);
    }));
    panel.append(h("div", { class: "stack" },
      h("p", { class: "note" }, "Double progression: keep the weight until every set reaches the top of the rep range, then add weight and drop to the bottom. Targets are uploaded to Garmin as strength workouts, so your watch shows the weight and reps for each set."),
      h("div", { class: "grid2" }, cards),
      ov.stalled && ov.stalled.length ? h("section", { class: "card" }, h("h3", null, "Not moving lately"),
        h("p", { class: "note" }, ov.stalled.join(", ") + ": the last session didn't beat any of the three before it. Check sleep and load around those days, or change the rep range in config.yml.")) : null,
      h("section", { class: "card" }, h("h2", null, "Progress by lift"), multiples),
      ov.unparsed && ov.unparsed.length ? unparsedCard(ov) : null));
  }
  function unparsedCard(ov) {
    return h("section", { class: "card" }, h("h3", null, "Lines the parser couldn't read"),
      h("p", { class: "note" }, "These were skipped. Rewrite them like \"Squat 3x5 100kg\" if they were lifts."),
      h("div", { class: "rows" }, ov.unparsed.map(u => h("div", { class: "row" }, h("span", null, u.lines.join(" · ")), h("span", { class: "small muted" }, C.fmtDay(u.date))))));
  }

  // ---------- Load & injury ----------
  function renderLoad(panel) {
    const inj = DATA.injury, c = inj.current, th = inj.thresholds;
    const loadChart = h("div", { class: "chart" }), acwrChart = h("div", { class: "chart" });
    panel.append(h("div", { class: "stack" },
      h("section", { class: "card" },
        h("div", { class: "card-head" }, h("h2", null, "Risk this week"), chip(c.risk, c.risk + " risk")),
        h("div", { class: "tiles" },
          tile("Load ratio (7d ÷ 28d)", fmt(c.acwr, 2), `caution ≥ ${th.acwr_caution}, high ≥ ${th.acwr_high}`),
          tile("Last 7 days load", fmt(c.acute), `4-week weekly avg ${fmt(c.chronic)}`),
          tile("Rest days", `${c.rest_days_7} / 7`, `${c.rest_days_14} in the last 14`),
          tile("Back-to-back hard days", c.back_to_back, `hard = load ≥ ${th.high_day_load}`),
          tile("Monotony", fmt(c.monotony, 1), "above 2 means every day looks the same")),
        c.flags.length ? h("div", { class: "rows" }, c.flags.map(f => h("div", { class: "row" }, h("span", null, f.text), chip(f.level, f.level)))) : h("p", { class: "note" }, "No warning patterns right now.")),
      h("section", { class: "card" }, h("h2", null, "Daily training load"),
        h("div", { class: "legend" }, h("span", null, h("i", { class: "box", style: "background:var(--accent);opacity:1" }), "Normal day"), h("span", null, h("i", { class: "box", style: "background:var(--div-bad);opacity:1" }), `High-intensity day (≥ ${th.high_day_load})`)),
        loadChart),
      h("section", { class: "card" }, h("h2", null, "Load ratio"), h("p", { class: "note" }, "Last 7 days of load divided by your 4-week weekly average. Sharp climbs above 1.3 are when strains tend to happen."), acwrChart),
      h("section", { class: "card" }, h("h2", null, "Weekly scan"), h("div", { class: "tablewrap" }, h("table", null,
        h("thead", null, h("tr", null, h("th", null, "Week ending"), h("th", { class: "num" }, "Load"), h("th", { class: "num" }, "Ratio"), h("th", { class: "num" }, "Rest days"), h("th", { class: "num" }, "Back-to-back"), h("th", null, "Risk"))),
        h("tbody", null, inj.weeks.slice().reverse().map(w => h("tr", null, h("td", null, day(w.week_ending)), h("td", { class: "num" }, fmt(w.load)), h("td", { class: "num" }, fmt(w.acwr, 2)),
          h("td", { class: "num" }, w.rest_days), h("td", { class: "num" }, w.back_to_back), h("td", null, chip(w.risk, w.risk)))))))),
      pastInjuries(inj)));
    requestAnimationFrame(() => {
      C.columns(loadChart, {
        data: inj.daily_load, key: "load", label: "Daily load", unitLabel: "training load", height: 190,
        classify: r => (r.load >= th.high_day_load ? "high" : ""),
        refLines: [{ y: th.high_day_load, label: "High-intensity", cls: "bad" }],
      });
      const acwr = inj.acwr_series.filter(r => r.acwr != null);
      C.line(acwrChart, {
        data: acwr, label: "Load ratio", height: 180, fmt: v => v.toFixed(1), yMin: 0,
        series: [{ key: "acwr", label: "Load ratio", color: "var(--accent)" }],
        refLines: [{ y: th.acwr_caution, label: "Caution " + th.acwr_caution, cls: "warn" }, { y: th.acwr_high, label: "High " + th.acwr_high, cls: "bad" }],
      });
    });
  }
  function pastInjuries(inj) {
    if (!inj.history || !inj.history.length) {
      return h("section", { class: "card" }, h("h2", null, "Past injuries"),
        h("p", { class: "note" }, "Add your glute strain (and any other injury) under injury.history in config.yml. The dashboard then shows what your load looked like in the week before it, and warns when today matches."));
    }
    return h("section", { class: "card" }, h("h2", null, "Before past injuries"),
      h("div", { class: "rows" }, inj.history.map(x => h("div", { class: "row" },
        h("div", null, h("span", { class: "row-title" }, x.label), h("span", { class: "muted small" }, " · " + day(x.date))),
        chip(x.scan.risk, x.scan.risk + " risk"),
        h("p", { class: "row-sub" }, x.scan.flags.length ? "The day before: " + x.scan.flags.map(f => f.text.toLowerCase()).join("; ") + "." : "No warning pattern the day before.")))));
  }

  boot();
})();
