// A stand-in for the parts of Google Apps Script that apps-script/food-log.gs uses,
// with Sheets' habit of turning text into dates and formulas unless a cell is formatted as text.
const vm = require("vm");
const fs = require("fs");
const path = require("path");

function makeSheet(name) {
  const cells = [], formats = [];
  const sh = {
    name, cells, formats, frozen: 0,
    getDataRange: () => ({ getValues: () => (cells.length ? cells.map(r => r.map(c => (c && c.formula ? c.formula : c))) : [[""]]) }),
    getRange(row, col, nr = 1, nc = 1) {
      return {
        setValues(vals) {
          vals.forEach((rv, i) => rv.forEach((v, j) => {
            const r = row - 1 + i, c = col - 1 + j;
            while (cells.length <= r) cells.push([]);
            const fmt = (formats[r] || [])[c];
            cells[r][c] = store(v, fmt);
          }));
          return this;
        },
        setNumberFormats(f) { f.forEach((rf, i) => { formats[row - 1 + i] = formats[row - 1 + i] || []; rf.forEach((x, j) => { formats[row - 1 + i][col - 1 + j] = x; }); }); return this; },
        setFontWeight() { return this; },
      };
    },
    setFrozenRows(n) { sh.frozen = n; },
  };
  return sh;
}
// What Sheets does with a written value.
function store(v, fmt) {
  if (typeof v !== "string") return v;
  if (v.startsWith("'")) return v.slice(1);                                   // forced text
  if (/^[=+\-@]/.test(v) && v.length > 1) return { formula: "#ERROR!" };     // would run as a formula
  if (fmt === "@") return v;
  if (/^\d{4}-\d{2}-\d{2}$/.test(v)) return new Date(v + "T00:00:00Z");
  if (/^\d{1,2}:\d{2}$/.test(v)) return new Date(`1899-12-30T${v.padStart(5, "0")}:00Z`);
  if (/^-?\d+(\.\d+)?$/.test(v)) return Number(v);
  return v;
}
function load() {
  const sheets = {};
  const book = {
    getSheetByName: n => sheets[n] || null,
    insertSheet: n => (sheets[n] = makeSheet(n)),
    getUrl: () => "https://docs.google.com/spreadsheets/d/TEST/edit",
  };
  const pad = n => String(n).padStart(2, "0");
  const ctx = {
    SpreadsheetApp: { getActiveSpreadsheet: () => book },
    LockService: { getScriptLock: () => ({ waitLock() {}, releaseLock() {} }) },
    ContentService: { MimeType: { JSON: "json" }, createTextOutput: text => ({ text, setMimeType() { return this; } }) },
    Session: { getScriptTimeZone: () => "UTC" },
    Utilities: { formatDate: (d, tz, f) => f === "HH:mm" ? `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`
      : `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}` },
    JSON, Array, String, Number, Object, Date,
  };
  vm.createContext(ctx);
  vm.runInContext(fs.readFileSync(path.join(__dirname, "../../apps-script/food-log.gs"), "utf8"), ctx);
  const call = (fn, body) => JSON.parse(ctx[fn](body === undefined ? undefined : { postData: { contents: typeof body === "string" ? body : JSON.stringify(body) } }).text);
  return { get: () => call("doGet"), post: body => call("doPost", body), sheets };
}
module.exports = { load };
