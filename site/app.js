// Spiti trip dashboard. Everything shown is computed by scripts/build.py; this file only renders it.
// Manual files are untrusted input, so every value goes in through textContent, never innerHTML.
const IST = "Asia/Kolkata";
const $ = (sel) => document.querySelector(sel);
const state = { data: {}, hourly: new Map(), fromCache: false, scrollNext: false, mode: null, doc: null };

function el(tag, cls, text, attrs = {}) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  for (const [k, v] of Object.entries(attrs)) if (v != null) e.setAttribute(k, v);
  return e;
}
const asDate = (s) => new Date(s.length === 10 ? `${s}T00:00:00+05:30` : s);
const fmt = (s, opts) => new Intl.DateTimeFormat("en-GB", { timeZone: IST, ...opts }).format(asDate(s)).replace(",", "");
const dayMonth = (s) => fmt(s, { day: "numeric", month: "short" });
const weekDay = (s) => fmt(s, { weekday: "short", day: "numeric", month: "short" });
const clock = (s) => fmt(s, { hour: "2-digit", minute: "2-digit", hour12: false });
const daysBetween = (a, b) => Math.round((asDate(b) - asDate(a)) / 864e5);
const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
const deg = (v) => (v == null ? "—" : `${Math.round(v) || 0}°`.replace("-", "−"));
const num = (v, d = 0) => (v == null ? "—" : v.toFixed(d).replace("-", "−"));
const metres = (v) => `${Math.round(v).toLocaleString("en-GB")} m`;
function todayIST() {
  const parts = new Intl.DateTimeFormat("en-GB", { timeZone: IST, year: "numeric", month: "2-digit", day: "2-digit" })
    .formatToParts(new Date());
  const p = Object.fromEntries(parts.map((x) => [x.type, x.value]));
  return `${p.year}-${p.month}-${p.day}`;
}
function dateRange(a, b) {
  if (!b || a === b) return dayMonth(a);
  return a.slice(0, 7) === b.slice(0, 7) ? `${fmt(a, { day: "numeric" })}–${dayMonth(b)}` : `${dayMonth(a)} – ${dayMonth(b)}`;
}
function median(vals) {
  const v = vals.filter((x) => x != null).sort((a, b) => a - b);
  if (!v.length) return null;
  const m = Math.floor(v.length / 2);
  return v.length % 2 ? v[m] : (v[m - 1] + v[m]) / 2;
}
const pill = (ice, title) => el("span", `pill ${ice.toLowerCase()}`, ice, { title });
const fill = (node, ...kids) => { node.textContent = ""; node.append(...kids); return node; };

async function getJSON(path) {
  const res = await fetch(path, { cache: "no-cache" });
  if (!res.ok) throw new Error(`${path}: ${res.status}`);
  if (res.headers.get("x-from-cache")) state.fromCache = true;
  return res.json();
}

// ---------- header and summary ----------

function renderHeader() {
  const { meta, outlook } = state.data;
  if (outlook.title) $("#title").textContent = outlook.title;
  const fed = meta.feeds && meta.feeds.om_ecmwf && meta.feeds.om_ecmwf.fetched_at;
  const age = fed ? (Date.now() - new Date(fed)) / 36e5 : Infinity;
  const feedText = fed ? `Automatic feeds updated ${dayMonth(fed)}, ${clock(fed)} IST` : "Automatic feeds not fetched yet";
  const line = fill($("#status"), el("span", age > 12 ? "danger" : age > 6 ? "warn" : "",
    feedText + (age > 12 ? ", data may be out of date" : "")));
  let manual = "your five sources not imported yet";
  if (meta.manual_read_at) {
    const d = Math.floor((Date.now() - new Date(meta.manual_read_at)) / 864e5);
    manual = `your five sources imported ${d >= 1 ? `${plural(d, "day")} ago` : dayMonth(meta.manual_read_at)}`;
  }
  line.append(` · ${manual}`);
  const failing = Object.values(meta.feeds || {}).filter((f) => !f.ok).length;
  if (failing) line.append(" · ", el("span", "warn", `${plural(failing, "feed")} failing, last good data kept`));
  const off = $("#offline");
  off.hidden = !state.fromCache;
  off.textContent = `Offline, showing data from ${dayMonth(meta.built_at)}, ${clock(meta.built_at)} IST`;
}

function renderSummary() {
  const { outlook } = state.data;
  $("#summary").textContent = outlook.summary.parts.join(" ");
  const today = todayIST();
  const toGo = daysBetween(today, outlook.trip_start);
  const facts = [];
  if (toGo > 0) facts.push([String(toGo), toGo === 1 ? "day to go" : "days to go"]);
  else if (today <= outlook.trip_end) facts.push([`Day ${-toGo}`, "Trip under way"]);
  else facts.push(["Done", "Trip finished"]);
  const f = outlook.facts;
  facts.push([f.last_snow ? dayMonth(f.last_snow) : "—", "last snow"]);
  facts.push([f.coldest ? deg(f.coldest.tmin) : "—", f.coldest ? `coldest night, ${f.coldest.place}` : "coldest night"]);
  fill($("#facts"), ...facts.map(([big, label]) => {
    const box = el("div", "fact");
    box.append(el("b", null, big), el("span", null, label));
    return box;
  }));
}

// ---------- day by day ----------

function sinceText(n) {
  if (n == null) return "—";
  return n === 0 ? "That day" : `${plural(n, "day")} ago`;
}

function renderDays() {
  const days = state.data.outlook.days;
  const rows = [
    ["Day", (d) => [el("div", "strong", `Day ${d.day}`), el("div", "sub", weekDay(d.date))]],
    ["Route", (d) => [el("span", "route", d.route, { title: d.plan })]],
    ["Sleep at", (d) => [d.stay.name, el("div", "sub", d.stay.alt_m ? `~${metres(d.stay.alt_m)}` : "")]],
    ["High / low", (d) => [el("span", "big", d.has_data ? deg(d.tmax) : "—"), el("span", "big-sub", ` / ${d.has_data ? deg(d.tmin) : "—"}`)]],
    ["Sky", (d) => [!d.has_data ? "Not in range yet"
      : (d.sky || "—") + (d.snow_places.length ? `; snow signal: ${d.snow_places.join(", ")}` : "")]],
    ["Road ice", (d) => [pill(d.ice, d.ice_reason)]],
    ["Last snow", (d) => [sinceText(d.days_since_snow)]],
    ["Hour by hour", (d) => [el("a", "view-hours", "View hours", { href: `#hourly/${d.date}/${d.stay.id}` })]],
    ["Based on", (d) => [el("span", "sub", d.has_data ? d.based_on : "No forecast yet")]],
  ];
  const grid = fill($("#days"));
  for (const [label, cell] of rows) {
    grid.append(el("div", "lab", label));
    for (const d of days) {
      const c = el("div", d.spiti ? "cell spiti" : "cell");
      c.append(...cell(d));
      grid.append(c);
    }
  }
}

// ---------- hour by hour ----------

function loadHourly(pid) {
  if (!state.hourly.has(pid)) {
    state.hourly.set(pid, getJSON(`data/hourly/${pid}.json`).catch((e) => { state.hourly.delete(pid); throw e; }));
  }
  return state.hourly.get(pid);
}

function hashChoice() {
  const m = location.hash.match(/^#hourly\/(\d{4}-\d\d-\d\d)\/([a-z_]+)$/);
  return m && state.data.outlook.places.some((p) => p.id === m[2]) ? { date: m[1], place: m[2] } : null;
}

async function renderHourly() {
  const { outlook } = state.data;
  const today = todayIST();
  const choice = hashChoice();
  const tripDay = outlook.days.find((d) => d.date === today) || outlook.days[0];
  const place = choice ? choice.place : tripDay.stay.id;
  const dateSel = $("#hour-date"), placeSel = $("#hour-place"), grid = fill($("#hours")), chips = fill($("#hour-chips"));
  if (!placeSel.options.length) for (const p of outlook.places) placeSel.append(el("option", null, p.name, { value: p.id }));
  placeSel.value = place;
  let h = null;
  try { h = await loadHourly(place); } catch (e) { /* message below */ }
  const dates = h ? [...new Set(h.time.map((t) => t.slice(0, 10)))] : [];
  const date = choice ? choice.date : dates.includes(today) ? today : outlook.days[0].date;
  const label = (d) => {
    const trip = outlook.days.find((x) => x.date === d);
    return weekDay(d) + (d === today ? " (today)" : "") + (trip ? ` · Day ${trip.day}` : "");
  };
  fill(dateSel, ...(dates.includes(date) ? dates : [date, ...dates]).map((d) => el("option", null, label(d), { value: d })));
  dateSel.value = date;
  const idx = h ? h.time.map((t, i) => (t.startsWith(date) ? i : -1)).filter((i) => i >= 0) : [];
  const note = $("#hour-note");
  if (!idx.length) {
    note.textContent = h ? "Hourly data is not available for this date yet." : "Hourly data could not be loaded.";
  } else {
    const sun = h.sun[date] || {};
    const mins = (t) => (t ? Number(t.slice(0, 2)) * 60 + Number(t.slice(3)) : null);
    const up = mins(sun.sunrise), down = mins(sun.sunset);
    const below = idx.filter((i) => h.temperature_2m[i] != null && h.temperature_2m[i] < 0).length;
    const levels = idx.map((i) => h.freezing_level_height[i]).filter((v) => v != null);
    const chipText = [sun.sunrise && `Sunrise ${sun.sunrise}`, sun.sunset && `Sunset ${sun.sunset}`,
      below === idx.length ? "Below freezing in every hour" : `${plural(below, "hour")} below freezing`,
      levels.length && `Lowest freezing level ${metres(Math.min(...levels))}`];
    chips.append(...chipText.filter(Boolean).map((t) => el("span", null, t)));
    const wet = (i) => (h.snowfall[i] > 0 ? [`${num(h.snowfall[i], 1)} cm`] : h.precipitation[i] > 0 ? [`${num(h.precipitation[i], 1)} mm`] : ["–"]);
    const rows = [
      ["Time", "time", (i) => [h.time[i].slice(11, 16)]],
      ["Temperature", "", (i) => [el("span", "temp", deg(h.temperature_2m[i]))]],
      ["Feels like", "", (i) => [deg(h.apparent_temperature[i])]],
      ["Snow / rain", "", wet],
      ["Wind", "", (i) => [`${num(h.wind_speed_10m[i])} m/s`, el("div", "sub", `gust ${num(h.wind_gusts_10m[i])}`)]],
      ["Cloud", "", (i) => [h.cloud_cover[i] == null ? "—" : `${Math.round(h.cloud_cover[i])}%`]],
    ];
    for (const [name, cls, cell] of rows) {
      grid.append(el("div", "lab", name));
      for (const i of idx) {
        const minute = Number(h.time[i].slice(11, 13)) * 60 + 30;
        const c = el("div", `cell ${cls}${up != null && down != null && minute >= up && minute <= down ? " sun" : ""}`);
        c.append(...cell(i));
        grid.append(c);
      }
    }
    note.textContent = `Open-Meteo best-match model for ${h.name}${h.elevation ? `, at ${metres(h.elevation)}` : ""}. Tinted hours are daylight. Times are IST.`;
  }
  if (state.scrollNext) $("#hourly").scrollIntoView({ behavior: "smooth", block: "start" });
  state.scrollNext = false;
}

// ---------- run-up, reports, sources, comparison ----------

function renderRunup() {
  const { outlook, snow } = state.data;
  const sel = $("#runup-place");
  if (!sel.options.length) {
    for (const p of outlook.places) sel.append(el("option", null, p.name, { value: p.id }));
    sel.value = outlook.places.some((p) => p.id === "kaza") ? "kaza" : outlook.places[0].id;
  }
  const rows = snow.filter((s) => s.place === sel.value && s.date < outlook.trip_start);
  fill($("#runup"), ...rows.map((s) => {
    const tile = el("div", "tile");
    let main = s.n_feeds ? `${s.snow_feeds} of ${s.n_feeds}` : s.reported ? "reported" : "no data";
    if (s.snow_feeds && s.snow_cm > 0) main += ` · ${num(s.snow_cm, s.snow_cm < 10 ? 1 : 0)} cm`;
    tile.append(el("div", "sub", fmt(s.date, { weekday: "short", day: "numeric" })), el("b", null, main));
    if (s.reported && s.n_feeds) tile.append(el("div", "sub", "reported"));
    const wrap = el("div");
    wrap.append(pill(s.ice, s.ice_reason));
    tile.append(wrap);
    return tile;
  }));
}

const KINDS = { observed: "Reported snowfall", forecast: "IMD snow forecast", dry_forecast: "IMD dry forecast",
  road: "Road report", outlook: "Outlook" };

function renderReports() {
  const items = state.data.reports;
  if (!items.length) return fill($("#reports"), el("p", "muted small", "No notes yet. Use \"Add Claude notes\" to add some."));
  return fill($("#reports"), ...items.map((n) => {
    const box = el("div", "report");
    const when = n.kind === "dry_forecast" && n.date === n.date_to ? `From ${dayMonth(n.date)}` : dateRange(n.date, n.date_to);
    box.append(el("b", null, `${when} · ${KINDS[n.kind] || n.kind}`));
    box.append(el("div", null, (n.area ? `${n.area}: ` : "") + n.summary));
    const src = el("div", "tiny muted");
    if (/^https?:\/\//.test(n.url || "")) src.append(el("a", null, n.source || "Source", { href: n.url, target: "_blank", rel: "noopener noreferrer" }));
    else src.textContent = n.source || "";
    box.append(src);
    return box;
  }));
}

function renderSources() {
  fill($("#sources"), ...state.data.sources.map((s) => {
    const box = el("div", "source", null, { title: s.detail });
    let sub = s.how === "automatic" ? "Automatic, every 3 hours" : s.last_read ? `Your import, ${dayMonth(s.last_read)}` : "Your import, not imported yet";
    if (s.status !== "ok" && s.last_read) sub += ` · ${s.status === "error" ? "last fetch failed" : s.status}`;
    box.append(el("b", null, s.name), el("div", s.status === "ok" || !s.last_read ? "tiny muted" : "tiny warn", sub));
    return box;
  }));
  const { feeds, days } = state.data.compare;
  const pairText = (v) => (v ? `${deg(v[0])} / ${deg(v[1])}` : "—");
  const head = el("tr");
  head.append(...["Day", "Night stop", "Median", ...feeds.map((f) => f.name)].map((t) => el("th", null, t, { scope: "col" })));
  const thead = el("thead"), tbody = el("tbody");
  thead.append(head);
  for (const d of days) {
    const tr = el("tr");
    tr.append(el("th", null, `${d.day} · ${weekDay(d.date)}`, { scope: "row" }), el("td", null, d.place), el("td", "median", pairText(d.median)));
    tr.append(...feeds.map((f) => el("td", null, pairText(d.values[f.id]))));
    tbody.append(tr);
  }
  fill($("#compare"), thead, tbody);
}

// ---------- import dialog ----------

const MODES = {
  sources: { schema: "spiti-sources/1", prompt: "prompts/collect-sources.md", title: "Import my 5 sources",
    sub: "AccuWeather, IMD, The Weather Network, timeanddate and yr.no, read by Claude in your own browser.",
    run: "Run it in Claude in Chrome. It opens your five pages and returns one block of structured data." },
  notes: { schema: "spiti-notes/1", prompt: "prompts/claude-notes.md", title: "Add Claude notes",
    sub: "Recent snowfall and road news for the route, searched and summarised by Claude.",
    run: "Run it in any Claude chat that can search the web. It returns one block of structured data." },
};

function checkField(label, v, spec, lim, errs) {
  const t = spec.type;
  if (v === null || v === undefined) { if (!spec.nullable) errs.push(`${label} is empty`); }
  else if (t === "number") {
    if (typeof v !== "number" || !Number.isFinite(v)) errs.push(`${label} must be a number`);
    else if ((spec.min != null && v < spec.min) || (spec.max != null && v > spec.max)) errs.push(`${label} is out of range (${v})`);
  } else if (t === "array") {
    if (!Array.isArray(v)) errs.push(`${label} must be a list`);
    else if (spec.enum && v.some((x) => !spec.enum.includes(x))) errs.push(`${label} has a value that is not allowed`);
  } else if (typeof v !== "string") errs.push(`${label} must be text`);
  else if (t === "date") {
    const d = /^\d{4}-\d\d-\d\d$/.test(v) ? new Date(`${v}T00:00:00Z`) : null;
    if (!d || Number.isNaN(d.getTime()) || d.toISOString().slice(0, 10) !== v) errs.push(`${label} must be a date like 2026-11-24`);
    else if (v < lim.date_min || v > lim.date_max) errs.push(`${label} is outside ${lim.date_min} to ${lim.date_max}`);
  } else if (t === "datetime" && !/^\d{4}-\d\d-\d\dT\d\d:\d\d/.test(v)) errs.push(`${label} must be a UTC time like 2026-11-13T09:30:00Z`);
  else if (t === "url" && v && !/^https?:\/\//.test(v)) errs.push(`${label} must start with http:// or https://`);
  else if (spec.enum && !spec.enum.includes(v)) errs.push(`${label} is not an allowed value (${v.slice(0, 40)})`);
  else if (spec.max_len && v.length > spec.max_len) errs.push(`${label} is longer than ${spec.max_len} characters`);
}

function checkObject(prefix, obj, fields, lim, errs) {
  for (const [key, spec] of Object.entries(fields)) {
    if (!(key in obj)) { if (spec.required) errs.push(`${prefix}${key} is missing`); } else checkField(prefix + key, obj[key], spec, lim, errs);
  }
}

function validate(doc, schema, wanted) {
  if (!doc || typeof doc !== "object" || Array.isArray(doc)) return ["This is not a JSON object."];
  if (doc.schema !== wanted) return [`"schema" must be "${wanted}" for this import.`];
  const sp = schema.schemas[wanted], errs = [];
  checkObject("", doc, sp.fields, schema.limits, errs);
  (Array.isArray(doc[sp.list]) ? doc[sp.list] : []).forEach((it, i) => {
    const prefix = `${sp.list} ${i + 1}: `;
    if (!it || typeof it !== "object" || Array.isArray(it)) { errs.push(`${prefix}not an object`); return; }
    checkObject(prefix, it, sp.item, schema.limits, errs);
    for (const [a, b] of sp.lte || []) {
      if (it[a] != null && it[b] != null && typeof it[a] === typeof it[b] && it[a] > it[b]) errs.push(`${prefix}${a} is above ${b}`);
    }
  });
  return errs;
}

function extractJSON(text) {
  // first complete {...} in the paste, ignoring code fences and stray prose around it
  for (let start = text.indexOf("{"); start >= 0; start = text.indexOf("{", start + 1)) {
    let depth = 0, inString = false, escaped = false;
    for (let i = start; i < text.length; i++) {
      const ch = text[i];
      if (inString) { if (escaped) escaped = false; else if (ch === "\\") escaped = true; else if (ch === '"') inString = false; }
      else if (ch === '"') inString = true;
      else if (ch === "{") depth++;
      else if (ch === "}" && --depth === 0) {
        try { return JSON.parse(text.slice(start, i + 1)); } catch (e) { break; }
      }
    }
  }
  return null;
}

function describe(doc) {
  const tripStart = state.data.outlook.trip_start, notes = [];
  if (doc.schema === "spiti-notes/1") {
    const dates = doc.items.flatMap((n) => [n.date, n.date_to || n.date]).sort();
    return { head: doc.items.length ? `Looks right: ${plural(doc.items.length, "note")}, ${dateRange(dates[0], dates[dates.length - 1])}` : "Looks right, but there are no new notes to save.", notes };
  }
  const bySource = new Map();
  for (const r of doc.rows) bySource.set(r.source, [...(bySource.get(r.source) || []), r]);
  for (const name of doc.failed || []) notes.push(`${name} did not load.`);
  for (const [name, rows] of bySource) {
    const last = rows.map((r) => r.date).sort().pop();
    if (last < tripStart) notes.push(`${name} stops at ${dayMonth(last)}.`);
    const far = rows.some((r) => {
      const mid = median(doc.rows.filter((x) => x.date === r.date).map((x) => x.tmax));
      return r.tmax != null && mid != null && Math.abs(r.tmax - mid) > 10;
    });
    if (far) notes.push(`${name} highs are more than 10° from the day's median.`);
  }
  const dates = doc.rows.map((r) => r.date).sort();
  const span = dates.length ? `, ${dateRange(dates[0], dates[dates.length - 1])}` : "";
  return { head: `Looks right: ${plural(bySource.size, "source")}, ${plural(doc.rows.length, "row")}${span}`, notes };
}

function checkPaste() {
  const text = $("#imp-text").value, box = $("#imp-result"), mode = MODES[state.mode];
  try { text.trim() ? localStorage.setItem(`spiti-draft-${state.mode}`, text) : localStorage.removeItem(`spiti-draft-${state.mode}`); } catch (e) { /* drafts are optional */ }
  state.doc = null;
  box.className = "result";
  if (!text.trim()) { box.textContent = "Nothing pasted yet."; $("#imp-save").disabled = true; return; }
  const doc = extractJSON(text);
  const errs = doc ? validate(doc, state.data.schema, mode.schema) : ["No JSON object found in the pasted text."];
  if (errs.length) {
    const list = el("ul");
    list.append(...errs.slice(0, 8).map((e) => el("li", null, e)));
    if (errs.length > 8) list.append(el("li", null, `and ${errs.length - 8} more`));
    fill(box, el("b", null, "This cannot be saved yet:"), list);
    box.className = "result bad";
  } else {
    const d = describe(doc);
    fill(box, el("b", null, d.head));
    if (d.notes.length) box.append(el("div", "muted", `Notes: ${d.notes.join(" ")}`));
    state.doc = doc;
  }
  $("#imp-save").disabled = !state.doc;
}

async function copyText(text) {
  try { await navigator.clipboard.writeText(text); return true; } catch (e) { /* fall through */ }
  const ta = el("textarea");
  ta.value = text;
  $("#import").append(ta);
  ta.select();
  let ok = false;
  try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
  ta.remove();
  return ok;
}

function openImport(modeName) {
  const mode = MODES[modeName];
  state.mode = modeName;
  $("#imp-title").textContent = mode.title;
  $("#imp-sub").textContent = mode.sub;
  $("#imp-run").textContent = mode.run;
  $("#imp-copied").textContent = "";
  let draft = "";
  try { draft = localStorage.getItem(`spiti-draft-${modeName}`) || ""; } catch (e) { draft = ""; }
  $("#imp-text").value = draft;
  checkPaste();
  $("#import").showModal();
}

async function copyPrompt() {
  const out = $("#imp-copied");
  try {
    const res = await fetch(MODES[state.mode].prompt, { cache: "no-cache" });
    if (!res.ok) throw new Error(String(res.status));
    out.textContent = (await copyText(await res.text())) ? "Copied. Paste it into Claude." : "Could not copy. Open the prompt file and copy it by hand.";
  } catch (e) {
    out.textContent = "Could not load the prompt. Check your connection.";
  }
}

async function saveToGitHub() {
  if (!state.doc) return;
  const { meta, schema } = state.data, sp = schema.schemas[state.doc.schema];
  let { owner, repo, branch } = meta.repo || {};
  if (location.hostname.endsWith(".github.io")) {
    owner = location.hostname.split(".")[0];
    repo = location.pathname.split("/").filter(Boolean)[0] || repo;
  }
  const stamp = state.doc[sp.time_key].replace(/^(\d{4}-\d\d-\d\d)T(\d\d):(\d\d).*$/, "$1T$2$3Z");
  const json = JSON.stringify(state.doc, null, 1);
  const copied = await copyText(json);
  const value = encodeURIComponent(json);
  let url = `https://github.com/${owner}/${repo}/new/${branch || "main"}?filename=${encodeURIComponent(`${sp.folder}/${stamp}.json`)}`;
  if (value.length <= 6000) url += `&value=${value}`;
  window.open(url, "_blank", "noopener");
  try { localStorage.removeItem(`spiti-draft-${state.mode}`); } catch (e) { /* drafts are optional */ }
  $("#imp-help").textContent = copied
    ? "GitHub opened in a new tab. If the file box there is empty, paste (the data is already copied), then press Commit changes."
    : "GitHub opened in a new tab. If the file box there is empty, copy the pasted result from step 3 into it, then press Commit changes.";
}

// ---------- start ----------

async function start() {
  const names = ["meta", "outlook", "snow", "reports", "sources", "compare"];
  try {
    const loaded = await Promise.all([...names.map((n) => getJSON(`data/${n}.json`)), getJSON("schema.json")]);
    names.forEach((n, i) => { state.data[n] = loaded[i]; });
    state.data.schema = loaded[names.length];
  } catch (e) {
    $("#status").textContent = "Could not load the data. Check your connection and reload.";
    return;
  }
  renderSummary();
  renderDays();
  renderRunup();
  renderReports();
  renderSources();
  await renderHourly();
  renderHeader();

  addEventListener("hashchange", renderHourly);
  $("#days").addEventListener("click", (e) => { if (e.target.closest("a.view-hours")) state.scrollNext = true; });
  const pick = () => { location.hash = `#hourly/${$("#hour-date").value}/${$("#hour-place").value}`; };
  $("#hour-date").addEventListener("change", pick);
  $("#hour-place").addEventListener("change", pick);
  $("#runup-place").addEventListener("change", renderRunup);
  for (const b of document.querySelectorAll("[data-import]")) b.addEventListener("click", () => openImport(b.dataset.import));
  $("#imp-text").addEventListener("input", checkPaste);
  $("#imp-copy").addEventListener("click", copyPrompt);
  $("#imp-save").addEventListener("click", saveToGitHub);

  if ("serviceWorker" in navigator) {
    try {
      await navigator.serviceWorker.register("sw.js");
      await navigator.serviceWorker.ready;
      // once the worker is in control, fetch every data file through it so the whole trip works offline
      const files = [...names.map((n) => `data/${n}.json`), ...state.data.outlook.places.map((p) => `data/hourly/${p.id}.json`)];
      setTimeout(() => files.forEach((f) => fetch(f, { cache: "no-cache" }).catch(() => {})), 1500);
    } catch (e) { /* offline support is optional */ }
  }
}

start();
