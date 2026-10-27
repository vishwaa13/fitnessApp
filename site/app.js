/* Morning Check: renders the JSON written by `python -m fitapp`.
   Real data arrives encrypted (data/data.enc.json) and is decrypted here with
   the passphrase; without it the page falls back to data/demo.json. */
(function () {
  const C = window.Charts;
  const app = document.getElementById("app");
  const PASS_KEY = "morningcheck.pass";
  const TABS = [["today", "Today"], ["month", "Month"], ["events", "Events"], ["recovery", "Recovery"], ["tournaments", "Tournaments"], ["strength", "Strength"], ["load", "Load & injury"]];
  let DATA = null;
  let recRange = 90;
  let recMetric = "hrv";
  let monthIdx = null, monthPick = null, weekIdx = null;

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
      : garminBanner(d.sources || {});
    const tabs = h("nav", { class: "tabs", role: "tablist", "aria-label": "Sections" },
      TABS.map(([id, label]) => h("button", {
        class: "tab", role: "tab", "aria-selected": String(currentTab() === id),
        onclick: () => { if (location.hash !== "#" + id) location.hash = id; else renderTab(); },
      }, label)));
    const panel = h("main", { id: "panel", class: "tabpanel", role: "tabpanel" });
    const footer = h("footer", { class: "footer" },
      Object.entries(d.sources || {}).map(([k, v]) => h("span", null, `${SOURCE_NAMES[k] || k[0].toUpperCase() + k.slice(1)}: ${v}`)),
      h("span", null, "Max HR used: " + fmt(d.athlete && d.athlete.max_hr)));
    app.replaceChildren(...[top, banner, verdictCard(d.today), tabs, panel, footer].filter(Boolean));
    renderTab();
  }
  const SOURCE_NAMES = { garmin: "Garmin", garmin_api: "Garmin API", garmin_login: "Garmin login", keep: "Keep",
    calendar: "Calendar", event_lookup: "Event lookup" };
  // Two Garmin connections: the official API (reads) and the login (readiness, drinks, workout uploads).
  function garminBanner(src) {
    const api = src.garmin_api, login = src.garmin_login;
    const loginOk = login === "ok", apiOk = api === "ok";
    const box = (title, text) => h("div", { class: "banner" }, h("strong", null, title + " "), text);
    if (api === "key rejected") {
      return box("Garmin API key rejected.", "It has probably expired or been deleted. Create a new one on Garmin Connect Web (Personal API Key) and update the GARMIN_API_KEY secret. "
        + (loginOk ? "HRV, sleep and activities come from the Garmin login meanwhile." : "No new Garmin data until then."));
    }
    if (login && !loginOk && login !== "not tried") {
      return box("Garmin login failed.", apiOk
        ? "HRV, sleep and activities still come from Garmin's official API, but training readiness, drinks and workout uploads are paused until the GARMIN_TOKENS secret is refreshed (README, step 3)."
        : "No new Garmin data this run. Refresh the GARMIN_TOKENS secret (README, step 3).");
    }
    return null;
  }
  function renderTab() {
    const panel = document.getElementById("panel");
    if (!panel) return;
    const tab = currentTab();
    document.querySelectorAll(".tab").forEach((b, i) => b.setAttribute("aria-selected", String(TABS[i][0] === tab)));
    panel.replaceChildren();
    ({ today: renderToday, month: renderMonth, events: renderEvents, recovery: renderRecovery, tournaments: renderTournaments, strength: renderStrength, load: renderLoad })[tab](panel);
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
    // Each morning is a button: picking one shows why it got its colour and what you did.
    const detail = h("div", { class: "day-detail", "aria-live": "polite" });
    const cells = t.strip.map((s, i) => h("button", {
      type: "button", class: "strip-cell" + (i === t.strip.length - 1 ? " today" : ""),
      "aria-label": `${day(s.date)}: ${STATUS_WORD[s.status]}. Show details`, title: `${day(s.date)}: ${STATUS_WORD[s.status]}`,
      onclick: () => pick(i),
      onkeydown: e => {
        const step = { ArrowLeft: -1, ArrowRight: 1 }[e.key];
        if (step && cells[i + step]) { e.preventDefault(); cells[i + step].focus(); pick(i + step); }
      },
    },
      h("span", { class: "strip-dot " + s.status, "aria-hidden": "true" }, STATUS_MARK[s.status]),
      h("span", { "aria-hidden": "true" }, C.parseDay(s.date).toLocaleDateString(undefined, { weekday: "narrow" }))));
    const strip = h("div", { class: "strip", role: "group", "aria-label": "Last 14 mornings" }, cells);
    function pick(i) {
      cells.forEach((c, j) => c.setAttribute("aria-pressed", j === i ? "true" : "false"));
      detail.replaceChildren(...dayDetail(t.strip[i]));
    }
    pick(t.strip.length - 1);
    const counts = t.strip.reduce((a, s) => ((a[s.status] = (a[s.status] || 0) + 1), a), {});

    panel.append(h("div", { class: "grid2" },
      h("div", { class: "stack" }, calendarCard(t), stripCard()),
      h("div", { class: "stack" }, reviewOnToday(d), injurySummary(d.injury), strengthSummary(d.overload), latestTournament(d.tournaments))));

    function stripCard() {
      return h("section", { class: "card" },
        h("div", { class: "card-head" }, h("h2", null, "Last two weeks"),
          h("span", { class: "small muted" }, `${counts.green || 0} green · ${counts.amber || 0} amber · ${counts.red || 0} red`)),
        strip, h("p", { class: "small muted" }, "Tap a day to see why it got its colour."), detail);
    }
  }
  const SIGNAL_CHIP = { red: "Low", amber: "Watch", green: "Good" };
  function activityLine(a) {
    const bits = [timeOf(a.start), a.duration_min ? `${Math.round(a.duration_min)} min` : null,
      a.distance_km ? `${fmt(a.distance_km, 1)} km` : null, a.avg_hr ? `avg ${Math.round(a.avg_hr)} bpm` : null].filter(Boolean);
    return h("div", { class: "row" },
      h("div", null, h("span", { class: "row-title" }, a.name || a.type), h("div", { class: "small muted" }, bits.join(" · "))),
      a.load != null ? h("span", { class: "num small" }, `load ${Math.round(a.load)}${a.load_estimated ? " (est.)" : ""}`) : null);
  }
  function dayDetail(s) {
    const out = [h("div", { class: "card-head" }, h("h3", null, day(s.date)), chip(s.status, STATUS_WORD[s.status])),
      h("p", { class: "note" }, s.summary || "")];
    if (s.signals && s.signals.length) {
      out.push(h("h4", null, "Why"), h("div", { class: "rows" }, s.signals.map(sg => h("div", { class: "row" },
        h("div", null, h("span", { class: "row-title" }, sg.label), " ", h("span", { class: "num" }, sg.display),
          sg.detail ? h("div", { class: "small muted" }, sg.detail) : null),
        chip(sg.level, SIGNAL_CHIP[sg.level] || sg.level)))));
    }
    const b = s.before || {};
    const before = [b.tags && b.tags.length ? b.tags.join(", ") : null,
      b.activities && b.activities.length ? b.activities.join(", ") + (b.load ? ` (load ${b.load})` : "") : null,
      b.gym && b.gym.length ? "Gym: " + b.gym.join(", ") : null].filter(Boolean);
    out.push(h("h4", null, "The day before"),
      h("p", { class: "note" }, before.length ? before.join(" · ") : "Rest day, nothing tagged."),
      h("p", { class: "small muted" }, "The morning colour comes from that night's sleep and HRV, so the day before is usually the cause."));
    out.push(h("h4", null, "What you did that day"));
    const did = [];
    if (s.activities && s.activities.length) did.push(h("div", { class: "rows" }, s.activities.map(activityLine)));
    if (s.gym && s.gym.length) did.push(h("div", { class: "rows" }, s.gym.map(g => h("div", { class: "row" },
      h("span", { class: "row-title" }, g.name), h("span", { class: "num small muted" }, g.sets)))));
    if (s.notes && s.notes.length) did.push(h("p", { class: "note" }, h("strong", null, "Noted: "), s.notes.join(" · ")));
    out.push(...(did.length ? did : [h("p", { class: "note" }, "Nothing recorded: a rest day, or the watch hasn't synced it yet.")]));
    return out;
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
  const FLAG_WORDS = { acwr: "load spike", rest: "too few rest days", b2b: "back-to-back hard days", monotony: "monotony",
    hrv: "low HRV", volume: "gym volume jump", return: "first session after a break", soreness: "soreness", alcohol: "alcohol", pain: "pain" };
  function injurySummary(inj) {
    const c = inj.current;
    return h("section", { class: "card" },
      h("div", { class: "card-head" }, h("h2", null, "Injury risk"), chip(c.risk, c.risk + " risk")),
      c.flags.length ? h("div", { class: "rows" }, c.flags.map(f => h("div", { class: "row" }, h("span", null, f.text), chip(f.level, f.level))))
        : h("p", { class: "note" }, "No warning patterns this week: enough rest, no load spike, no back-to-back hard days."),
      inj.matches_past && inj.matches_past.length ? h("p", { class: "note" },
        h("strong", null, "Looks like before your " + inj.matches_past[0].label.toLowerCase() + ": "),
        inj.matches_past[0].shared.map(k => FLAG_WORDS[k] || k).join(", ") + (inj.matches_past[0].shared.length > 1 ? " all match." : " matches.")) : null,
      restedNote(inj),
      h("p", { class: "small muted" }, `Load ratio ${fmt(c.acwr, 2)} · ${c.rest_days_7} rest day${c.rest_days_7 === 1 ? "" : "s"} in 7 · `, go("load")));
  }
  function restedNote(inj) {
    const back = inj.coming_back || [];
    if (!back.length) return null;
    return h("p", { class: "note" }, h("strong", null, "Rested 2+ weeks: "),
      back.map(b => `${b.part} (${b.days} days)`).join(", ") + ". Start 10–15% lighter when you go back; the Strength targets already do.");
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
      bedtimeCard(rec),
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
  // ---------- Bedtime consistency ----------
  function hm(minutes) {
    const m = Math.abs(Math.round(minutes));
    return m >= 60 ? `${Math.floor(m / 60)}h` + (m % 60 ? String(m % 60).padStart(2, "0") : "") : `${m} min`;
  }
  function bedtimeCard(rec) {
    const b = rec.bedtime;
    if (!b || !b.nights || b.nights.length < 3) {
      return h("section", { class: "card" }, h("h2", null, "Bedtime consistency"),
        h("p", { class: "note" }, "Waiting for sleep times from Garmin. They fill in over the next few refreshes, going back four months."));
    }
    const chart = h("div", { class: "chart" });
    const late = (rec.effects || []).find(e => e.key === "late_bed");
    let effect = "Not enough late nights yet to say what they do to your HRV.";
    if (late && late.hrv && late.hrv.delta != null && late.hrv.confidence !== "too_few") {
      effect = `Mornings after a late bedtime: HRV ${signed(late.hrv.delta)} ms (${signed(late.hrv.delta_pct, 0)}%) and sleep score ${signed(late.sleep_score.delta)} against your baseline, over ${late.hrv.n} nights. ${confidenceText(late.hrv.confidence)}.`
        + (late.overlaps && late.overlaps.length ? ` These nights mostly come with ${late.overlaps.map(o => (rec.tag_labels[o.key] || o.key).toLowerCase()).join(" and ")}, so that's part of it.` : "");
    }
    const card = h("section", { class: "card" },
      h("div", { class: "card-head" }, h("h2", null, "Bedtime consistency"), h("span", { class: "small muted" }, `Last ${b.n} nights`)),
      h("div", { class: "tiles" },
        tile("Usual bedtime", b.usual_bed || "–", "median"),
        tile("Usual wake time", b.usual_wake || "–", "median"),
        tile("Bedtime spread", b.bed_sd != null ? "±" + hm(b.bed_sd) : "–", "under 30 min is steady"),
        tile("Weekend shift", b.weekend_shift != null ? (b.weekend_shift >= 0 ? "+" : "−") + hm(b.weekend_shift) : "–", "Fri/Sat nights vs the rest"),
        tile("Late nights", `${b.late_nights} / ${b.n}`, `${hm(b.late_by)}+ after your usual time`)),
      h("div", { class: "legend" }, h("span", null, h("i", { class: "box", style: "background:var(--accent);opacity:1" }), "Asleep → awake"),
        h("span", null, h("i", { class: "box", style: "background:var(--seq2);opacity:1" }), `Late bedtime (${hm(b.late_by)}+ after usual)`),
        b.usual_bed ? h("span", null, h("i", { class: "line-key" }), `Usual bedtime ${b.usual_bed}`) : null),
      chart,
      h("p", { class: "note" }, effect));
    const usual = b.nights.map(n => n.bed_m).sort((x, y) => x - y)[Math.floor(b.nights.length / 2)];
    requestAnimationFrame(() => C.ranges(chart, {
      data: b.nights, label: "Sleep times", height: 220,
      refLine: b.usual_bed ? { y: usual, label: "" } : null,
      tip: n => [{ head: true, label: day(n.date) }, { value: `${n.bed} → ${n.wake}`, label: "asleep → awake" },
        { value: hm(n.hours * 60), label: "in bed asleep" }].concat(n.late ? [{ label: "Late bedtime" }] : []),
    }));
    return card;
  }

  // ---------- Month ----------
  const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  const WEEKDAYS_FULL = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
  const isoDay = dt => `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, "0")}-${String(dt.getDate()).padStart(2, "0")}`;
  function renderMonth(panel) {
    const cal = DATA.calendar;
    if (!cal || !cal.days || !cal.days.length) {
      panel.append(h("section", { class: "card" }, h("h2", null, "No mornings yet"), h("p", { class: "note" }, "The month view fills in once Garmin data arrives.")));
      return;
    }
    const days = cal.days;
    const byDate = Object.fromEntries(days.map(x => [x.date, x]));
    const months = [...new Set(days.map(x => x.date.slice(0, 7)))];
    if (monthIdx == null || monthIdx >= months.length) monthIdx = months.length - 1;
    const ym = months[monthIdx];
    const inMonth = days.filter(x => x.date.startsWith(ym));
    if (!monthPick || !monthPick.startsWith(ym) || !byDate[monthPick]) monthPick = inMonth[inMonth.length - 1].date;
    const first = C.parseDay(ym + "-01");
    const lead = (first.getDay() + 6) % 7;
    const count = new Date(first.getFullYear(), first.getMonth() + 1, 0).getDate();
    const detail = h("div", { class: "day-detail", "aria-live": "polite" });
    const cells = [];
    const grid = h("div", { class: "month-grid", role: "group", "aria-label": first.toLocaleDateString(undefined, { month: "long", year: "numeric" }) },
      WEEKDAYS.map(w => h("div", { class: "month-wd", "aria-hidden": "true" }, w)),
      Array.from({ length: lead }, () => h("div", { class: "mcell blank" })),
      Array.from({ length: count }, (_, i) => {
        const iso = `${ym}-${String(i + 1).padStart(2, "0")}`, x = byDate[iso];
        if (!x) return h("div", { class: "mcell blank" }, h("span", { class: "mnum" }, String(i + 1)));
        const drank = DATA.alcohol && DATA.alcohol.evenings[iso];
        const btn = h("button", {
          type: "button", class: "mcell " + x.status + (iso === DATA.today_date ? " today" : ""),
          "aria-pressed": String(iso === monthPick),
          "aria-label": `${day(iso)}: ${STATUS_WORD[x.status]}, training load ${x.load}${drank ? ", alcohol that evening" : ""}. Show details`,
          onclick: () => pick(iso),
        }, drank ? h("span", { class: "mdrink", "aria-hidden": "true", title: "Alcohol that evening" }) : null,
          h("span", { class: "mnum" }, String(i + 1)),
          h("span", { class: "mmark", "aria-hidden": "true" }, STATUS_MARK[x.status]),
          h("span", { class: "mload num", "aria-hidden": "true" }, x.load ? String(x.load) : ""));
        cells.push([iso, btn]);
        return btn;
      }));
    function pick(iso) {
      monthPick = iso;
      cells.forEach(([k, b]) => b.setAttribute("aria-pressed", String(k === iso)));
      detail.replaceChildren(...dayDetail(byDate[iso]));
    }
    pick(monthPick);
    const nav = (step, label) => h("button", { type: "button", class: "nav-btn", "aria-label": label, disabled: !months[monthIdx + step],
      onclick: () => { monthIdx += step; monthPick = null; renderTab(); } }, step < 0 ? "‹" : "›");
    panel.append(h("div", { class: "stack" },
      h("section", { class: "card" },
        h("div", { class: "card-head" }, h("h2", null, first.toLocaleDateString(undefined, { month: "long", year: "numeric" })),
          h("div", { class: "nav-pair" }, nav(-1, "Previous month"), nav(1, "Next month"))),
        grid,
        h("p", { class: "small muted" }, "✓ green, ! amber, ✕ red morning. The number is that day's training load; ",
          h("span", { class: "mdrink inline", "aria-hidden": "true" }), " alcohol that evening. Tap a day for the details."),
        detail),
      alcoholCard(ym),
      weekdayCard(days),
      weekCard(cal.weeks, true)));
  }
  function alcoholCard(ym) {
    const al = DATA.alcohol;
    if (!al || !al.months) return null;
    const i = al.months.findIndex(m => m.month === ym);
    if (i < 0) return null;
    const m = al.months[i], p = al.months[i + 1];
    const name = C.parseDay(ym + "-01").toLocaleDateString(undefined, { month: "long" });
    const vs = (a, b, unit) => (b == null ? "" : a === b ? `same as ${unit}` : `${signed(a - b, 0)} vs ${unit}`);
    const prevName = p ? C.parseDay(p.month + "-01").toLocaleDateString(undefined, { month: "long" }) : null;
    const plural = (k, v) => (v === 1 ? k : ({ beer: "beers", cocktail: "cocktails", cider: "ciders" }[k] || k));
    const types = Object.entries(m.types || {});
    const rec = (DATA.recovery.effects || []).find(e => e.key === "alcohol");
    const effect = rec && rec.hrv && rec.hrv.delta != null && rec.hrv.confidence !== "too_few"
      ? `The morning after drinking, your HRV runs ${signed(rec.hrv.delta)} ms and sleep score ${signed(rec.sleep_score.delta)} against your baseline (${confidenceText(rec.hrv.confidence).toLowerCase()}, ${rec.hrv.n} nights).` : null;
    return h("section", { class: "card" },
      h("div", { class: "card-head" }, h("h2", null, `Alcohol in ${name}`), m.partial ? h("span", { class: "small muted" }, "so far") : null),
      m.evenings ? h("div", { class: "tiles" },
        tile("Evenings", m.evenings, p ? vs(m.evenings, p.evenings, prevName) : ""),
        tile("Drinks", fmt(m.drinks), (p ? vs(m.drinks, p.drinks, prevName) : "") + (m.unknown ? ` · ${m.unknown} evening${m.unknown === 1 ? "" : "s"} without an amount` : "")),
        tile("Per drinking evening", m.per_evening != null ? fmt(m.per_evening, 1) : "–", "where the amount was logged"),
        tile("Biggest evening", m.biggest ? fmt(m.biggest.total) : "–", m.biggest ? day(m.biggest.date) : ""))
        : h("p", { class: "note" }, `No alcohol logged in ${name}` + (p && p.evenings ? ` (${p.evenings} evening${p.evenings === 1 ? "" : "s"} in ${prevName}).` : ".")),
      types.length ? h("p", { class: "note" }, h("strong", null, "By type: "), types.map(([k, v]) => `${fmt(v)} ${plural(k, v)}`).join(", ")) : null,
      effect ? h("p", { class: "note" }, effect) : null,
      h("p", { class: "small muted" }, "From Garmin's lifestyle log, plus lines like \u201c27/10 3 beers\u201d in your recovery tags note. Garmin's amount wins when both have one."));
  }
  function weekdayCard(days) {
    const rows = WEEKDAYS.map((w, i) => {
      const xs = days.filter(x => (C.parseDay(x.date).getDay() + 6) % 7 === i && x.status !== "unknown");
      const n = k => xs.filter(x => x.status === k).length;
      const before = xs.map(x => (x.before || {}).load || 0);
      return { w, full: WEEKDAYS_FULL[i], total: xs.length, green: n("green"), amber: n("amber"), red: n("red"),
        before: before.length ? Math.round(before.reduce((a, b) => a + b, 0) / before.length) : null };
    });
    const worst = rows.filter(r => r.total).sort((a, b) => b.red / b.total - a.red / a.total || b.amber - a.amber)[0];
    const weeks = Math.round(days.length / 7);
    return h("section", { class: "card" },
      h("h2", null, "Mornings by weekday"),
      worst && worst.red ? h("p", { class: "note" }, h("strong", null, `Most red mornings: ${worst.full}s`), ` (${worst.red} of ${worst.total}), after an average load of ${worst.before} the day before.`)
        : h("p", { class: "note" }, "No red mornings in this period."),
      h("div", { class: "tablewrap" }, h("table", { class: "compact" },
        h("thead", null, h("tr", null, h("th", null, h("span", { class: "sr" }, "Weekday")),
          h("th", { class: "num", title: "Green mornings" }, "✓", h("span", { class: "sr" }, " green")),
          h("th", { class: "num", title: "Amber mornings" }, "!", h("span", { class: "sr" }, " amber")),
          h("th", { class: "num", title: "Red mornings" }, "✕", h("span", { class: "sr" }, " red")),
          h("th", { class: "num" }, "Load before"))),
        h("tbody", null, rows.map(r => h("tr", { class: worst && r === worst && r.red ? "hl" : null },
          h("td", null, r.w), h("td", { class: "num" }, r.green), h("td", { class: "num" }, r.amber), h("td", { class: "num" }, r.red),
          h("td", { class: "num" }, r.before == null ? "–" : String(r.before))))))),
      h("p", { class: "small muted" }, `✓ green, ! amber, ✕ red mornings over the last ${weeks} weeks. Load before is the average training load the day before.`));
  }

  // ---------- Week in review ----------
  function latestFullWeek(weeks) { return weeks.length > 1 && weeks[0].partial ? 1 : 0; }
  function reviewOnToday(d) {
    const dow = C.parseDay(d.today_date).getDay();   // 0 Sunday, 1 Monday
    if (!d.calendar || !d.calendar.weeks || (dow !== 0 && dow !== 1)) return null;
    return weekCard(d.calendar.weeks, false);
  }
  function bedMin(t) { if (!t) return null; const [hh, mm] = t.split(":").map(Number); return ((hh * 60 + mm) - 18 * 60 + 1440) % 1440; }
  function weekCard(weeks, withNav) {
    if (!weeks || !weeks.length) return null;
    if (withNav && (weekIdx == null || !weeks[weekIdx])) weekIdx = latestFullWeek(weeks);
    const i = withNav ? weekIdx : latestFullWeek(weeks);
    const w = weeks[i], p = weeks[i + 1];
    const range = `${C.fmtDay(w.start)} – ${C.fmtDay(w.end)}` + (w.partial ? ` (so far, ${w.days} day${w.days === 1 ? "" : "s"})` : "");
    const diff = (a, b, dp = 0, unit = "") => (a == null || b == null) ? "" : (a === b ? "same" : signed(a - b, dp) + unit);
    const cols = c => `${c.green} ✓ · ${c.amber} ! · ${c.red} ✕`;
    const bed = x => x.bedtime && x.bedtime.usual_bed ? x.bedtime.usual_bed + (x.bedtime.bed_sd != null ? ` ±${hm(x.bedtime.bed_sd)}` : "") : "–";
    const bedDiff = (a, b) => {
      const x = bedMin(a.bedtime && a.bedtime.usual_bed), y = b && bedMin(b.bedtime && b.bedtime.usual_bed);
      return x == null || y == null ? "" : x === y ? "same" : (x > y ? "+" : "−") + hm(x - y) + (x > y ? " later" : " earlier");
    };
    const row = (label, a, b, change) => h("tr", null, h("td", null, label),
      h("td", { class: "num" }, String(a), change ? h("div", { class: "small muted" }, change) : null),
      h("td", { class: "num muted" }, String(b)));
    const table = h("table", { class: "week-table" },
      h("thead", null, h("tr", null, h("th", null, h("span", { class: "sr" }, "Measure")), h("th", { class: "num" }, w.partial ? "This week" : "Week"), h("th", { class: "num" }, "Week before"))),
      h("tbody", null,
        row("Training load", fmt(w.load), p ? fmt(p.load) : "–", p && diff(w.load, p.load)),
        row("Activities", `${w.sessions} (${w.gym_sessions} gym)`, p ? `${p.sessions} (${p.gym_sessions} gym)` : "–", p && diff(w.sessions, p.sessions)),
        row("Rest days", w.rest_days, p ? p.rest_days : "–", p && diff(w.rest_days, p.rest_days)),
        row("Mornings", cols(w.colours), p ? cols(p.colours) : "–", ""),
        row("Average HRV", w.hrv != null ? `${fmt(w.hrv)} ms` : "–", p && p.hrv != null ? `${fmt(p.hrv)} ms` : "–", p && diff(w.hrv, p.hrv, 0, " ms")),
        row("Average sleep", w.sleep_score != null ? `${fmt(w.sleep_score)} · ${fmt(w.sleep_hours, 1)} h` : "–", p && p.sleep_score != null ? `${fmt(p.sleep_score)} · ${fmt(p.sleep_hours, 1)} h` : "–", p && diff(w.sleep_score, p.sleep_score)),
        row("Resting HR", w.rhr != null ? `${fmt(w.rhr)} bpm` : "–", p && p.rhr != null ? `${fmt(p.rhr)} bpm` : "–", p && diff(w.rhr, p.rhr, 0, " bpm")),
        row("Bedtime", bed(w), p ? bed(p) : "–", p ? bedDiff(w, p) : ""),
        row("Alcohol evenings", w.alcohol + (w.drinks ? ` · ${fmt(w.drinks)} drinks` : ""),
          p ? p.alcohol + (p.drinks ? ` · ${fmt(p.drinks)} drinks` : "") : "–", p && diff(w.drinks || 0, p.drinks || 0, 0, " drinks"))));
    const parts = [...new Set([...Object.keys(w.sets || {}), ...Object.keys((p && p.sets) || {})])];
    const sets = parts.map(k => {
      const a = (w.sets || {})[k] || 0, b = ((p && p.sets) || {})[k] || 0;
      return `${cap(k)} ${a}` + (p && a !== b ? ` (${signed(a - b, 0)})` : "");
    });
    const nav = (step, label) => h("button", { type: "button", class: "nav-btn", "aria-label": label, disabled: !weeks[weekIdx + step],
      onclick: () => { weekIdx += step; renderTab(); } }, step > 0 ? "‹" : "›");
    return h("section", { class: "card" },
      h("div", { class: "card-head" }, h("div", null, h("h2", null, "Week in review"), h("span", { class: "small muted" }, range)),
        withNav ? h("div", { class: "nav-pair" }, nav(1, "Earlier week"), nav(-1, "Later week")) : null),
      h("div", { class: "tablewrap" }, table),
      sets.length ? h("p", { class: "note" }, h("strong", null, "Hard gym sets: "), sets.join(", ")) : null,
      h("h3", null, "Warnings raised"),
      w.flags && w.flags.length ? h("div", { class: "rows" }, w.flags.map(f => h("div", { class: "row" },
        h("div", null, h("span", { class: "row-title" }, cap(FLAG_WORDS[f.key] || f.key)),
          h("span", { class: "muted small" }, ` · ${f.days} day${f.days === 1 ? "" : "s"}, first ${C.fmtDay(f.date)}`),
          h("div", { class: "small muted" }, f.text)),
        chip(f.level, f.level))))
        : h("p", { class: "note" }, "None this week."),
      withNav ? null : h("p", { class: "small muted" }, "Earlier weeks are on the ", go("month"), " tab."));
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
  const ACTION = { add_weight: ["green", "Add weight"], add_reps: ["plain accent", "Add reps"], hold: ["amber", "Hold"], deload: ["red", "Deload"], add_load: ["green", "Add load"], pain: ["red", "Back off: pain"], return: ["amber", "Back after a break"] };
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
          tile("Monotony", fmt(c.monotony, 1), "above 2 means every day looks the same"),
          tile("Alcohol evenings", `${c.alcohol_7 || 0} / 7`, "Garmin lifestyle log + recovery tags")),
        c.flags.length ? h("div", { class: "rows" }, c.flags.map(f => h("div", { class: "row" }, h("span", null, f.text), chip(f.level, f.level)))) : h("p", { class: "note" }, "No warning patterns right now.")),
      painCard(inj.pain || []),
      bodyPartsCard(inj),
      sorenessCard(inj),
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
  function painCard(pain) {
    if (!pain.length) return null;
    return h("section", { class: "card" },
      h("div", { class: "card-head" }, h("h2", null, "Pain from your gym log")),
      h("div", { class: "rows" }, pain.map(p => h("div", { class: "row" },
        h("div", null, h("span", { class: "row-title" }, p.label), h("span", { class: "muted small" }, " · " + day(p.date) + (p.exercise ? " · " + p.exercise : ""))),
        p.active ? chip("red", "Until " + day(p.until)) : chip("plain", "Past"),
        h("p", { class: "row-sub" }, "\u201c" + p.text + "\u201d" + (p.returning
          ? ` It came on your first ${p.body_part} session in ${p.returning.gap} days (last ${C.fmtDay(p.returning.last)}).` : "")
          + (p.active && p.affects.length
          ? ` Lifts that load the ${p.body_part} are backed off 10% until ${day(p.until)}; see Strength.` : ""))))),
      h("p", { class: "small muted" }, "A pain line in the gym log raises the risk for two weeks. If it doesn't settle, get it looked at."));
  }
  // A heat cell: one sequential hue, light (few) to dark (many); the number is always printed.
  function heatCell(value, max, hue, tipRows, aria, zero = "·") {
    const t = value ? Math.min(1, value / max) : 0;
    const pct = Math.round(14 + 71 * t);
    const style = value ? `background:color-mix(in oklab, var(${hue}) ${pct}%, var(--surface))` : null;
    const deep = hue === "--accent" && pct >= 65;   // white reads better than ink on the darkest blues (APCA)
    const show = e => {
      const r = e.currentTarget.getBoundingClientRect();
      C.showTip(e.clientX != null ? e : { clientX: r.right, clientY: r.bottom }, tipRows);
    };
    return h("td", null, h("span", { class: "hc" + (value ? "" : " zero") + (deep ? " deep" : ""), style, tabindex: "0", role: "img", "aria-label": aria,
      onpointermove: show, onfocus: show, onpointerleave: C.hideTip, onblur: C.hideTip }, value == null ? "" : value ? String(value) : zero));
  }
  function rampLegend(hue, lo, hi) {
    return h("span", { class: "ramp-legend small muted" }, lo,
      h("span", { class: "ramp", "aria-hidden": "true" }, [0.15, 0.4, 0.65, 0.9].map(t =>
        h("i", { style: `background:color-mix(in oklab, var(${hue}) ${Math.round(14 + 71 * t)}%, var(--surface))` }))), hi);
  }
  const cap = s => s.charAt(0).toUpperCase() + s.slice(1);
  function bodyPartsCard(inj) {
    const bp = inj.body_parts;
    if (!bp || !bp.rows.length) return null;
    const max = Math.max(6, ...bp.rows.flatMap(r => r.sets));
    const head = h("tr", null, h("th", { class: "row-h" }, "Body part"),
      bp.week_ends.map((w, i) => h("th", { scope: "col" }, i === bp.week_ends.length - 1 ? "This week" : C.fmtDay(w))),
      h("th", { class: "num", scope: "col" }, "vs 4-wk avg"));
    const rows = bp.rows.map(r => h("tr", null, h("th", { class: "row-h part", scope: "row" }, cap(r.part)),
      r.sets.map((n, i) => heatCell(n, max, "--accent",
        [{ head: true, label: `${cap(r.part)} · 7 days to ${C.fmtDay(bp.week_ends[i])}` }, { value: String(n), label: n === 1 ? "hard set" : "hard sets" }],
        `${r.part}, 7 days to ${C.fmtDay(bp.week_ends[i])}: ${n} hard sets`)),
      h("td", { class: "num" }, r.acute ? `${fmt(r.ratio, 1)}×` : "–")));
    return h("section", { class: "card" },
      h("div", { class: "card-head" }, h("h2", null, "Gym sets per body part"), rampLegend("--accent", "fewer", "more")),
      h("p", { class: "note" }, "Hard sets in each 7-day block, from your gym log: sets at 70% or more of that day's top weight for the lift, so warm-ups don't count. A body part well above its 4-week average is flagged in the risk list. Garmin's load misses most of this."),
      heatWrap(h("table", { class: "heat" }, h("thead", null, head), h("tbody", null, rows))),
      restedNote(inj));
  }
  function sorenessCard(inj) {
    const so = inj.soreness;
    if (!inj.soreness_logged || !so || !so.rows.length) {
      return h("section", { class: "card" }, h("h2", null, "Soreness"),
        h("p", { class: "note" }, "Add a Google Keep note titled \u201crecovery tags\u201d and jot one line each morning: ",
          h("code", null, "24/10 shoulder 2/5, legs sore"), ". Scores are out of 5 (or 10). 3/5 is flagged; 4/5 and up is treated as pain and backs off the lifts for that body part. ",
          h("code", null, "shoulder ok"), " records a good day. Alcohol and travel go on the same lines."));
    }
    const head = h("tr", null, h("th", { class: "row-h" }, "Body part"),
      so.dates.map(x => h("th", { scope: "col", title: day(x) }, C.parseDay(x).toLocaleDateString(undefined, { day: "numeric" }))));
    const rows = so.rows.map(r => h("tr", null, h("th", { class: "row-h part", scope: "row" }, cap(r.part)),
      r.scores.map((v, i) => heatCell(v, 5, "--seq2",
        [{ head: true, label: `${cap(r.part)} · ${day(so.dates[i])}` }, { value: v == null ? "–" : `${v}/5`, label: v == null ? "nothing logged" : "soreness" }],
        `${r.part}, ${day(so.dates[i])}: ${v == null ? "nothing logged" : v + " out of 5"}`, "0"))));
    return h("section", { class: "card" },
      h("div", { class: "card-head" }, h("h2", null, "Soreness, last 14 days"), rampLegend("--seq2", "1", "5")),
      h("p", { class: "note" }, "From your recovery tags note and sore lines in the gym log. 0 means you wrote it felt fine."),
      heatWrap(h("table", { class: "heat" }, h("thead", null, head), h("tbody", null, rows))));
  }
  // Newest data is on the right; on a narrow screen start scrolled there.
  function heatWrap(table) {
    const wrap = h("div", { class: "tablewrap" }, table);
    requestAnimationFrame(() => { wrap.scrollLeft = wrap.scrollWidth; });
    return wrap;
  }
  function pastInjuries(inj) {
    if (!inj.history || !inj.history.length) {
      return h("section", { class: "card" }, h("h2", null, "Past injuries"),
        h("p", { class: "note" }, "Write pain into your gym log (\u201cLeft shoulder pain, stopped\u201d) and it lands here, or add older injuries like your glute strain under injury.history in config.yml. The dashboard then shows what your load looked like the day before each one, and warns when today matches."));
    }
    return h("section", { class: "card" }, h("h2", null, "Before past injuries"),
      h("div", { class: "rows" }, inj.history.map(x => h("div", { class: "row" },
        h("div", null, h("span", { class: "row-title" }, x.label), h("span", { class: "muted small" }, " · " + day(x.date) + (x.source === "gym log" ? " · from gym log" : ""))),
        chip(x.scan.risk, x.scan.risk + " risk"),
        h("p", { class: "row-sub" }, x.scan.flags.length ? "The day before: " + x.scan.flags.map(f => f.text.toLowerCase()).join("; ") + "." : "No warning pattern the day before.")))));
  }

  boot();
})();
