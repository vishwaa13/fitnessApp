// The Apps Script food log against a fake spreadsheet: node tests/js/food-sheet.test.js
const assert = require("assert");
const { load } = require("./sheet-mock");
const tests = [];
const test = (name, fn) => tests.push([name, fn]);
const entry = (id, over = {}) => ({ id, date: "2026-11-03", slot: "lunch", name: "Potato meal", kcal: 1040, protein: 58,
  time: "12:30", meal: "d-potato", updated: "2026-11-03T12:30:00.000Z", deleted: false, ...over });

test("empty sheet: tabs with headers, nothing logged", () => {
  const s = load(), out = s.get();
  assert.deepStrictEqual([out.ok, out.entries, out.meals], [true, {}, {}]);
  assert.deepStrictEqual(s.sheets.entries.cells[0], ["id", "date", "slot", "name", "kcal", "protein", "time", "meal", "updated", "deleted"]);
  assert.match(out.sheet, /docs\.google\.com/);
});

test("entries come back exactly as sent: dates and times stay text, numbers stay numbers", () => {
  const s = load();
  const out = s.post({ entries: [entry("a"), entry("b", { time: null, meal: null, protein: 0 })] });
  assert.strictEqual(out.changed, 2);
  assert.deepStrictEqual(out.entries.a, entry("a"));
  assert.deepStrictEqual(out.entries.b, entry("b", { time: null, meal: null, protein: 0 }));
  assert.strictEqual(typeof s.sheets.entries.cells[1][4], "number");       // kcal sums in Sheets
});

test("newer edit wins, older is ignored, same id twice in one request keeps the newer", () => {
  const s = load();
  s.post({ entries: [entry("a")] });
  s.post({ entries: [entry("a", { deleted: true, updated: "2026-11-03T13:00:00.000Z" })] });
  let out = s.post({ entries: [entry("a", { kcal: 1, updated: "2026-11-03T12:45:00.000Z" })] });
  assert.strictEqual(out.changed, 0);
  assert.deepStrictEqual([out.entries.a.deleted, out.entries.a.kcal], [true, 1040]);
  out = s.post({ entries: [entry("n", { kcal: 1, updated: "2026-11-03T14:00:00.000Z" }), entry("n", { kcal: 2, updated: "2026-11-03T15:00:00.000Z" }),
    entry("n", { kcal: 3, updated: "2026-11-03T14:30:00.000Z" })] });
  assert.strictEqual(out.entries.n.kcal, 2);
  assert.strictEqual(s.sheets.entries.cells.filter(r => r[0] === "n").length, 1);
});

test("meal options keep their slots", () => {
  const s = load();
  const out = s.post({ meals: [{ id: "m-1", name: "Banana", kcal: 105, protein: 1.3, slots: ["snacks", "misc"], updated: "2026-11-03T10:00:00Z", deleted: false }] });
  assert.deepStrictEqual(out.meals["m-1"].slots, ["snacks", "misc"]);
  assert.strictEqual(out.meals["m-1"].protein, 1.3);
});

test("names that look like formulas are stored as text", () => {
  const s = load();
  const out = s.post({ entries: [entry("f", { name: "=IMPORTXML(\"x\")" }), entry("g", { name: "+protein shake" })] });
  assert.strictEqual(out.entries.f.name, "=IMPORTXML(\"x\")");
  assert.strictEqual(out.entries.g.name, "+protein shake");
});

test("junk is refused or skipped", () => {
  const s = load();
  assert.strictEqual(s.post("not json").ok, false);
  const out = s.post({ entries: [null, { name: "no id" }, { id: 5 }, entry("ok")] });
  assert.deepStrictEqual(Object.keys(out.entries), ["ok"]);
});

let failed = 0;
for (const [name, fn] of tests) {
  try { fn(); console.log("ok   " + name); } catch (e) { failed++; console.log("FAIL " + name + "\n     " + e.message); }
}
if (failed) process.exit(1);
