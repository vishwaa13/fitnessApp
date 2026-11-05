// Lift search ranking: node tests/js/lift-search.test.js
const assert = require("assert");
require("../../site/lift-search.js");
const { rank, tier } = globalThis.LiftSearch;
const tests = [];
const test = (name, fn) => tests.push([name, fn]);
const lift = (name, date, names) => ({ name, date, names: names || [name] });
const order = (items, q) => rank(items, q).map(x => x.name);

const LIFTS = [
  lift("Bench", "2026-10-29", ["Bench press", "Bench"]),
  lift("Incline dumbbell bench press", "2026-11-03"),
  lift("Close-grip bench", "2026-09-10"),
  lift("Leg press", "2026-11-02"),
  lift("Pull-ups", "2026-10-29"),
  lift("Lat pulldown", "2026-11-04"),
  lift("Leg curl", "2026-10-01"),
  lift("Bicep curl", "2026-11-04"),
  lift("Seated cable row", "2026-10-20"),
];

test("better matches first, then the most recently done", () => {
  // Bench: exact (via its alias too); Close-grip and Incline have "bench" as a word, newest first.
  assert.deepStrictEqual(order(LIFTS, "bench"), ["Bench", "Incline dumbbell bench press", "Close-grip bench"]);
  assert.deepStrictEqual(order(LIFTS, "curl"), ["Bicep curl", "Leg curl"]);       // same tier: newest first
  assert.deepStrictEqual(order(LIFTS, "leg"), ["Leg press", "Leg curl"]);         // both start with it: newest first
});

test("the name starting with it beats a later word starting with it", () => {
  assert.deepStrictEqual(order(LIFTS, "pul"), ["Pull-ups", "Lat pulldown"]);
});

test("aliases count: 'bench press' finds Bench first", () => {
  assert.deepStrictEqual(order(LIFTS, "bench press").slice(0, 2), ["Bench", "Incline dumbbell bench press"]);
});

test("capitals, hyphens, spaces and plurals don't matter", () => {
  assert.strictEqual(tier("Pull-ups", "pullup"), 0);
  assert.strictEqual(tier("Pull-ups", "PULL UPS"), 0);
  assert.strictEqual(tier("Squat", "squats"), 0);
  assert.strictEqual(tier("Press", "press"), 0);
});

test("several words in any order, and dropped letters", () => {
  assert.deepStrictEqual(order(LIFTS, "db incline"), ["Incline dumbbell bench press"]);
  assert.deepStrictEqual(order(LIFTS, "cable row"), ["Seated cable row"]);
  // A typo is an equally loose match for both bench lifts, so the one done most recently comes first.
  assert.deepStrictEqual(order(LIFTS, "bnch"), ["Incline dumbbell bench press", "Bench", "Close-grip bench"]);
});

test("nothing typed, or nothing matching, gives nothing", () => {
  assert.deepStrictEqual(order(LIFTS, ""), []);
  assert.deepStrictEqual(order(LIFTS, "   "), []);
  assert.deepStrictEqual(order(LIFTS, "zzz"), []);
});

let failed = 0;
for (const [name, fn] of tests) {
  try { fn(); console.log("ok   " + name); } catch (e) { failed++; console.log("FAIL " + name + "\n     " + e.message); }
}
if (failed) process.exit(1);
