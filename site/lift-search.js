/* Lift search for the Last time card: rank lifts by how well a name matches what
   you typed, then by the one you did most recently. Each lift may have several
   names (aliases you've logged it under); its best-matching name counts. */
(function (root) {
  // Gym shorthand, spelled out on both sides: "db incline" finds "Incline dumbbell bench press".
  const SHORT = { db: "dumbbell", bb: "barbell", kb: "kettlebell", ohp: "overhead press", rdl: "romanian deadlift",
    sldl: "stiff leg deadlift", dl: "deadlift", bss: "bulgarian split squat" };
  const unplural = w => (w.length > 3 && w.endsWith("s") && !w.endsWith("ss") ? w.slice(0, -1) : w);
  // "Pull-Ups" and "pullup" read alike: lower case, no accents or punctuation, no plural s.
  function norm(s) {
    return String(s || "").toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "")
      .replace(/[^a-z0-9æø]+/g, " ").trim().split(" ").filter(Boolean)
      .flatMap(w => (SHORT[w] || w).split(" ")).map(unplural);
  }
  // Letters in order, starting at the start of a word: "bnch" is Bench, "leg" isn't Close-grip bench.
  function loosely(q, words) {
    return words.some((w, i) => {
      if (w[0] !== q[0]) return false;
      let k = 0;
      for (const ch of words.slice(i).join("")) if (ch === q[k]) k++;
      return k === q.length;
    });
  }
  // 0 is the best match; null means no match.
  function tier(name, query) {
    const words = norm(name), q = norm(query);
    if (!q.length || !words.length) return null;
    const n = words.join(" "), nq = q.join(" "), cn = words.join(""), cq = q.join("");
    if (n === nq || unplural(cn) === unplural(cq)) return 0;                   // exact
    if (n.startsWith(nq) || cn.startsWith(cq)) return 1;                       // the name starts with it
    if (q.length === 1 && words.some(w => w.startsWith(nq))) return 2;          // a word starts with it
    if (n.includes(nq) || cn.includes(cq)) return 3;                           // anywhere in the name
    if (q.every(t => words.some(w => w.startsWith(t)))) return 4;              // every word you typed starts a word
    if (q.every(t => cn.includes(t))) return 5;                                // every word appears somewhere
    if (cq.length >= 4 && loosely(cq, words)) return 6;                        // letters in order: "bnch"
    return null;
  }
  // items: [{name, names?, date: "YYYY-MM-DD"}]; returns the matches, best first.
  function rank(items, query) {
    return items
      .map(item => {
        const tiers = [item.name].concat(item.names || []).map(n => tier(n, query)).filter(t => t !== null);
        return { item, t: tiers.length ? Math.min(...tiers) : null };
      })
      .filter(x => x.t !== null)
      .sort((a, b) => a.t - b.t || String(b.item.date).localeCompare(String(a.item.date)) || a.item.name.localeCompare(b.item.name))
      .map(x => x.item);
  }
  root.LiftSearch = { rank, tier, norm };
})(typeof window !== "undefined" ? window : globalThis);
