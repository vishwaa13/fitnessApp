/**
 * Morning Check food log: the datastore behind the dashboard's Food tab.
 *
 * Setup (once, about 5 minutes; README → Food log):
 *   1. Create a Google Sheet, then Extensions → Apps Script.
 *   2. Replace the code there with this file and save.
 *   3. Deploy → New deployment → type "Web app".
 *      Execute as: Me. Who has access: Anyone. Deploy, and allow access.
 *   4. Copy the web app URL (ends in /exec) into the FOOD_SHEET_URL repository secret.
 *
 * The site sends what changed and gets the whole log back. Every row has an id
 * and an "updated" time; the newer one wins, so phones logging at the same time
 * don't overwrite each other. Removed items stay as rows with deleted = TRUE so
 * every device learns about the removal.
 */

var TABS = {
  entries: ["id", "date", "slot", "name", "kcal", "protein", "time", "meal", "updated", "deleted"],
  meals: ["id", "name", "kcal", "protein", "slots", "updated", "deleted"],
};
var NUMBERS = { kcal: "0", protein: "0.#" };
var BOOLEANS = { deleted: true };
var MAX_ITEMS = 500;            // per request; the site sends only what changed

function doGet() {
  return reply(readAll());
}

function doPost(e) {
  var body;
  try {
    body = JSON.parse((e && e.postData && e.postData.contents) || "{}");
  } catch (err) {
    return reply({ ok: false, error: "That wasn't JSON." });
  }
  var lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try {
    var changed = 0;
    for (var tab in TABS) {
      var items = Array.isArray(body[tab]) ? body[tab].slice(0, MAX_ITEMS) : [];
      changed += upsert(sheet(tab), TABS[tab], items);
    }
    var out = readAll();
    out.changed = changed;
    return reply(out);
  } finally {
    lock.releaseLock();
  }
}

function reply(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}

// The tab, created with its header row on first use.
function sheet(tab) {
  var book = SpreadsheetApp.getActiveSpreadsheet();
  var sh = book.getSheetByName(tab);
  if (!sh) {
    sh = book.insertSheet(tab);
    sh.getRange(1, 1, 1, TABS[tab].length).setValues([TABS[tab]]).setFontWeight("bold");
    sh.setFrozenRows(1);
  }
  return sh;
}

function readAll() {
  var out = { ok: true, sheet: SpreadsheetApp.getActiveSpreadsheet().getUrl() };
  for (var tab in TABS) out[tab] = read(sheet(tab), TABS[tab]);
  return out;
}

function read(sh, cols) {
  var rows = sh.getDataRange().getValues().slice(1);
  var out = {};
  rows.forEach(function (row) {
    var item = fromRow(row, cols);
    if (item.id) out[item.id] = item;
  });
  return out;
}

function fromRow(row, cols) {
  var item = {};
  cols.forEach(function (c, i) {
    var v = row[i];
    if (v instanceof Date) v = Utilities.formatDate(v, Session.getScriptTimeZone(), c === "time" ? "HH:mm" : "yyyy-MM-dd");
    if (NUMBERS[c]) v = Number(v) || 0;
    else if (BOOLEANS[c]) v = v === true || String(v).toUpperCase() === "TRUE";
    else if (c === "slots") v = String(v || "").split(",").map(function (s) { return s.trim(); }).filter(String);
    else v = v === "" || v == null ? null : String(v);
    item[c] = v;
  });
  return item;
}

function toRow(item, cols) {
  return cols.map(function (c) {
    var v = item[c];
    if (NUMBERS[c]) return Number(v) || 0;
    if (BOOLEANS[c]) return v === true;
    if (c === "slots") return (Array.isArray(v) ? v : []).join(",");
    v = v == null ? "" : String(v).slice(0, 200);
    // A name like "=1+1" or "+protein" would otherwise run as a formula.
    return /^[=+\-@]/.test(v) ? "'" + v : v;
  });
}

// Write new and newer items; returns how many rows changed.
function upsert(sh, cols, items) {
  var values = sh.getDataRange().getValues();
  var at = {};
  for (var r = 1; r < values.length; r++) at[String(values[r][0])] = r;
  var upd = cols.indexOf("updated");
  var fresh = [], freshAt = {}, changed = 0;
  var formats = cols.map(function (c) { return NUMBERS[c] || (BOOLEANS[c] ? "General" : "@"); });
  items.forEach(function (item) {
    if (!item || typeof item.id !== "string" || !item.id) return;
    var row = toRow(item, cols);
    var r = at[item.id], f = freshAt[item.id];
    if (f !== undefined) {
      if (String(item.updated || "") > String(fresh[f][upd] || "")) fresh[f] = row;
    } else if (r === undefined) {
      freshAt[item.id] = fresh.length;
      fresh.push(row);
    } else if (String(item.updated || "") > String(values[r][upd] || "")) {
      var range = sh.getRange(r + 1, 1, 1, cols.length);
      range.setNumberFormats([formats]);
      range.setValues([row]);
      values[r] = row;
      changed++;
    }
  });
  if (fresh.length) {
    var block = sh.getRange(values.length + 1, 1, fresh.length, cols.length);
    // Plain text, so dates and times stay as typed instead of turning into Sheets dates.
    block.setNumberFormats(fresh.map(function () { return formats; }));
    block.setValues(fresh);
    changed += fresh.length;
  }
  return changed;
}
