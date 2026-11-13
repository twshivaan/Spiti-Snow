#!/usr/bin/env python3
"""Spiti trip dashboard build: fetch feeds, merge manual files, compute, write site/data.

Standard library only.
  python scripts/build.py                      live run
  python scripts/build.py --offline DIR        read saved responses from DIR, no network
  python scripts/build.py --record DIR         live run that also saves each response into DIR
"""
import argparse
import json
import math
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IST = timezone(timedelta(hours=5, minutes=30))
AREA = "spiti_area"
OM_MODELS = {"om_ecmwf": "ecmwf_ifs025", "om_gfs": "gfs_seamless", "om_icon": "icon_seamless"}
MANUAL = {"AccuWeather": "accuweather", "IMD": "imd_manual", "The Weather Network": "twn",
          "timeanddate": "timeanddate", "yr.no": "yrno"}
FEED_NAMES = {"om_ecmwf": "Open-Meteo ECMWF", "om_gfs": "Open-Meteo GFS", "om_icon": "Open-Meteo ICON",
              "metno": "MET Norway", "imd": "IMD Spiti (automatic)", "accuweather": "AccuWeather",
              "imd_manual": "IMD (your import)", "twn": "The Weather Network",
              "timeanddate": "timeanddate", "yrno": "yr.no (your import)"}
VALUE_KEYS = ("tmax", "tmin", "snow_cm", "precip_mm", "precip_pct", "wind_max", "sky")
ICE_RANK = {"Unknown": 0, "Low": 1, "Moderate": 2, "High": 3}
WMO = {0: "Clear", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast", 45: "Fog", 48: "Fog",
       51: "Light drizzle", 53: "Drizzle", 55: "Drizzle", 56: "Freezing drizzle", 57: "Freezing drizzle",
       61: "Light rain", 63: "Rain", 65: "Heavy rain", 66: "Freezing rain", 67: "Freezing rain",
       71: "Light snow", 73: "Snow", 75: "Heavy snow", 77: "Snow grains", 80: "Rain showers",
       81: "Rain showers", 82: "Heavy showers", 85: "Snow showers", 86: "Snow showers",
       95: "Thunderstorm", 96: "Thunderstorm, hail", 99: "Thunderstorm, hail"}
OM_URL = ("https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
          "&timezone=Asia%2FKolkata&wind_speed_unit=ms&forecast_days=16")
OM_DAILY = ("&past_days=7&models=" + ",".join(OM_MODELS.values()) +
            "&daily=temperature_2m_max,temperature_2m_min,snowfall_sum,precipitation_sum,"
            "precipitation_probability_max,wind_speed_10m_max,weather_code,sunrise,sunset")
HOURLY_VARS = ["temperature_2m", "apparent_temperature", "precipitation", "snowfall", "snow_depth",
               "weather_code", "wind_speed_10m", "wind_gusts_10m", "cloud_cover", "freezing_level_height"]
OM_HOURLY = "&past_days=1&hourly=" + ",".join(HOURLY_VARS)
MODEL_VARS = ["temperature_2m", "apparent_temperature", "precipitation", "snowfall", "wind_speed_10m",
              "wind_gusts_10m", "cloud_cover", "freezing_level_height"]
OM_HOURLY_MODELS = ("&past_days=1&models=" + ",".join(OM_MODELS.values()) + "&hourly=" + ",".join(MODEL_VARS))
HOURLY_SOURCES = [{"id": "best", "name": "Open-Meteo best match"},
                  *({"id": f, "name": FEED_NAMES[f]} for f in (*OM_MODELS, "metno"))]
METNO_URL = "https://api.met.no/weatherapi/locationforecast/2.0/compact?lat={lat}&lon={lon}&altitude={alt}"
IMD_URL = "https://city.imd.gov.in/citywx/city_weather_test_try_warnings.php?id=88815"


# ---------- small helpers ----------

def load_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def pdate(s):
    return date.fromisoformat(s)


def shift(s, days):
    return (pdate(s) + timedelta(days=days)).isoformat()


def short(s):
    d = pdate(s)
    return f"{d.day} {d:%b}"


def median(vals):
    v = sorted(x for x in vals if x is not None)
    if not v:
        return None
    m = len(v) // 2
    return v[m] if len(v) % 2 else (v[m - 1] + v[m]) / 2


def rnd(x):
    return None if x is None else int(math.floor(x + 0.5))


def deg(x):
    return "—" if x is None else f"{x}°".replace("-", "−")


def row(place, day, feed, tmax, tmin, snow_cm, precip_mm, precip_pct, wind_max, sky, fetched_at):
    return {"place": place, "date": day, "feed": feed, "tmax": tmax, "tmin": tmin, "snow_cm": snow_cm,
            "precip_mm": precip_mm, "precip_pct": precip_pct, "wind_max": wind_max, "sky": sky,
            "fetched_at": fetched_at}


def write_json(path, obj, compact=False):
    """Write only when the content changed. Lists go one item per line to keep diffs small."""
    if compact:
        text = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    elif isinstance(obj, list):
        text = "[\n" + ",\n".join(json.dumps(x, ensure_ascii=False) for x in obj) + "\n]"
    else:
        text = json.dumps(obj, ensure_ascii=False, indent=1)
    text += "\n"
    path = Path(path)
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return True


# ---------- validation (rules live in site/schema.json, shared with the page) ----------

def _check(label, v, spec, lim, errs):
    t = spec["type"]
    if v is None:
        if not spec.get("nullable"):
            errs.append(f"{label} is empty")
    elif t == "number":
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            errs.append(f"{label} must be a number")
        elif ("min" in spec and v < spec["min"]) or ("max" in spec and v > spec["max"]):
            errs.append(f"{label} is out of range ({v})")
    elif t == "array":
        if not isinstance(v, list):
            errs.append(f"{label} must be a list")
        elif "enum" in spec and any(x not in spec["enum"] for x in v):
            errs.append(f"{label} has a value that is not allowed")
    elif not isinstance(v, str):
        errs.append(f"{label} must be text")
    elif t == "date":
        try:
            ok = bool(re.fullmatch(r"\d{4}-\d\d-\d\d", v)) and bool(pdate(v))
        except ValueError:
            ok = False
        if not ok:
            errs.append(f"{label} must be a date like 2026-11-24")
        elif not lim["date_min"] <= v <= lim["date_max"]:
            errs.append(f"{label} is outside {lim['date_min']} to {lim['date_max']}")
    elif t == "datetime" and not re.match(r"\d{4}-\d\d-\d\dT\d\d:\d\d", v):
        errs.append(f"{label} must be a UTC time like 2026-11-13T09:30:00Z")
    elif t == "url" and v and not re.match(r"https?://", v):
        errs.append(f"{label} must start with http:// or https://")
    elif "enum" in spec and v not in spec["enum"]:
        errs.append(f"{label} is not an allowed value ({v[:40]})")
    elif "max_len" in spec and len(v) > spec["max_len"]:
        errs.append(f"{label} is longer than {spec['max_len']} characters")


def _check_obj(prefix, obj, fields, lim, errs):
    for key, spec in fields.items():
        if key not in obj:
            if spec.get("required"):
                errs.append(f"{prefix}{key} is missing")
        else:
            _check(prefix + key, obj[key], spec, lim, errs)


def validate(doc, schema):
    """Return a list of problems; empty means the file is valid."""
    if not isinstance(doc, dict):
        return ["not a JSON object"]
    sp = schema["schemas"].get(doc.get("schema"))
    if not sp:
        return [f"schema must be one of: {', '.join(schema['schemas'])}"]
    errs, lim = [], schema["limits"]
    _check_obj("", doc, sp["fields"], lim, errs)
    items = doc.get(sp["list"])
    for i, it in enumerate(items if isinstance(items, list) else []):
        prefix = f"{sp['list']} {i + 1}: "
        if not isinstance(it, dict):
            errs.append(prefix + "not an object")
            continue
        _check_obj(prefix, it, sp["item"], lim, errs)
        for a, b in sp.get("lte", []):
            x, y = it.get(a), it.get(b)
            if x is not None and y is not None and type(x) in (int, float, str) \
                    and isinstance(y, (int, float) if not isinstance(x, str) else str) and x > y:
                errs.append(f"{prefix}{a} is above {b}")
    return errs


def load_manual(manual_dir, schema, invalid):
    """Read every manual file; invalid ones are listed and skipped, never fatal."""
    out = {"sources": [], "notes": []}
    for kind, docs in out.items():
        for p in sorted((Path(manual_dir) / kind).glob("*.json")):
            doc = load_json(p)
            errs = ["not valid JSON"] if doc is None else validate(doc, schema)
            if not errs and doc["schema"] != f"spiti-{kind}/1":
                errs = [f"wrong schema for the {kind} folder"]
            if errs:
                invalid.append({"file": f"{kind}/{p.name}", "errors": errs[:5]})
            else:
                docs.append(doc)
    return out["sources"], out["notes"]


def manual_rows(docs):
    rows = []
    for doc in sorted(docs, key=lambda d: d["read_at"]):
        for r in doc["rows"]:
            rows.append(row(AREA, r["date"], MANUAL[r["source"]], r.get("tmax"), r.get("tmin"),
                            r.get("snow_cm_max"), r.get("precip_mm"), r.get("precip_pct"), None,
                            r.get("sky"), doc["read_at"]))
    return rows


def merge_notes(docs):
    seen = {}
    for doc in sorted(docs, key=lambda d: d["written_at"]):
        for it in doc["items"]:
            seen[(it.get("url"), it["date"], it["kind"])] = {
                **it, "date_to": it.get("date_to") or it["date"], "places": it.get("places") or [],
                "written_at": doc["written_at"]}
    return sorted(seen.values(), key=lambda n: (n["date"], n["written_at"]), reverse=True)


# ---------- feeds ----------

class Net:
    def __init__(self, offline=None, record=None, ua="spiti-trip-dashboard/1.0"):
        self.offline = Path(offline) if offline else None
        self.record = Path(record) if record else None
        self.ua = ua

    def get(self, name, url, headers=None):
        """Return (text, last_modified). text is None when the server answers 304."""
        if self.offline:
            return (self.offline / name).read_text(encoding="utf-8"), None
        req = urllib.request.Request(url, headers={"User-Agent": self.ua, **(headers or {})})
        for attempt in (1, 2):
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    text, lm = r.read().decode("utf-8", "replace"), r.headers.get("Last-Modified")
                break
            except urllib.error.HTTPError as e:
                if e.code == 304:
                    return None, None
                if attempt == 2 or e.code < 500:
                    raise
            except OSError:
                if attempt == 2:
                    raise
            time.sleep(2)
        if self.record:
            self.record.mkdir(parents=True, exist_ok=True)
            (self.record / name).write_text(text, encoding="utf-8", newline="\n")
        return text, lm


def om_get(net, name, url, place, elev):
    """Open-Meteo call; repeated at the place's own altitude when the grid cell is over 150 m off."""
    pid, alt = place["id"], place["alt_m"]
    known = elev.get(pid) or {}
    if known.get("used") == alt and known.get("grid") != alt:
        return json.loads(net.get(name, f"{url}&elevation={alt}")[0])
    js = json.loads(net.get(name, url)[0])
    grid = js.get("elevation")
    if not net.offline or not known:
        elev[pid] = {"grid": grid, "used": grid}
    if grid is not None and abs(grid - alt) > 150 and not net.offline:
        js = json.loads(net.get(name, f"{url}&elevation={alt}")[0])
        elev[pid] = {"grid": grid, "used": alt}
    return js


def om_daily_rows(pid, js, now_iso):
    d, rows, sun = js["daily"], [], {}
    for fid, model in OM_MODELS.items():
        def g(key, i):
            vals = d.get(f"{key}_{model}") or []
            return vals[i] if i < len(vals) else None
        for i, day in enumerate(d["time"]):
            if g("sunrise", i) and g("sunset", i):
                sun.setdefault(day, {"sunrise": g("sunrise", i)[11:16], "sunset": g("sunset", i)[11:16]})
            tmax, tmin = g("temperature_2m_max", i), g("temperature_2m_min", i)
            if tmax is None and tmin is None:
                continue  # null means "no value", not zero
            rows.append(row(pid, day, fid, tmax, tmin, g("snowfall_sum", i), g("precipitation_sum", i),
                            g("precipitation_probability_max", i), g("wind_speed_10m_max", i),
                            WMO.get(g("weather_code", i)), now_iso))
    return rows, sun


def metno_sky(code):
    if not code:
        return None
    c = code.split("_")[0]
    for key in ("snow", "sleet", "rain"):
        if key in c:
            pre = "Light " if c.startswith("light") else "Heavy " if c.startswith("heavy") else ""
            return (pre + key).capitalize()
    return {"clearsky": "Clear", "fair": "Fair", "partlycloudy": "Partly cloudy", "cloudy": "Overcast",
            "fog": "Fog"}.get(c, c.capitalize())


def metno_rows(pid, js, now_iso):
    days = {}
    for ts in js["properties"]["timeseries"]:
        t = datetime.fromisoformat(ts["time"].replace("Z", "+00:00")).astimezone(IST)
        data = ts["data"]
        det = data["instant"]["details"]
        b = days.setdefault(t.date().isoformat(), {"t": [], "w": [], "p": 0.0, "sym": None, "gap": 99})
        if det.get("air_temperature") is not None:
            b["t"].append(det["air_temperature"])
        if det.get("wind_speed") is not None:
            b["w"].append(det["wind_speed"])
        nxt = data.get("next_1_hours") or data.get("next_6_hours") or {}
        b["p"] += (nxt.get("details") or {}).get("precipitation_amount") or 0
        sym = ((data.get("next_6_hours") or data.get("next_1_hours") or {}).get("summary") or {}).get("symbol_code")
        if sym and abs(t.hour - 12) < b["gap"]:
            b["sym"], b["gap"] = sym, abs(t.hour - 12)
    return [row(pid, day, "metno", max(b["t"]), min(b["t"]), None, round(b["p"], 1), None,
                max(b["w"]) if b["w"] else None, metno_sky(b["sym"]), now_iso)
            for day, b in sorted(days.items()) if len(b["t"]) >= 3]


def om_model_hours(js):
    """Per-model hourly series, each cut off where that model's forecast ends."""
    h, out = js["hourly"], {}
    for fid, model in OM_MODELS.items():
        temps = h.get(f"temperature_2m_{model}") or []
        n = max((i + 1 for i, v in enumerate(temps) if v is not None), default=0)
        if n:
            out[fid] = {"time": h["time"][:n]}
            for k in MODEL_VARS:
                vals = (h.get(f"{k}_{model}") or [])[:n]
                if any(v is not None for v in vals):
                    out[fid][k] = vals
    return out


def metno_hours(js):
    """MET Norway time steps in IST: hourly at first, then every 6 hours."""
    out = {k: [] for k in ("time", "temperature_2m", "precipitation", "wind_speed_10m", "cloud_cover")}
    for ts in js["properties"]["timeseries"]:
        t = datetime.fromisoformat(ts["time"].replace("Z", "+00:00")).astimezone(IST)
        data = ts["data"]
        det = data["instant"]["details"]
        nxt = data.get("next_1_hours") or data.get("next_6_hours") or {}
        out["time"].append(t.strftime("%Y-%m-%dT%H:%M"))
        out["temperature_2m"].append(det.get("air_temperature"))
        out["wind_speed_10m"].append(det.get("wind_speed"))
        out["cloud_cover"].append(det.get("cloud_area_fraction"))
        out["precipitation"].append((nxt.get("details") or {}).get("precipitation_amount"))
    return out


class _TableRows(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows, self.row, self.cell = [], None, None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.row, self.cell = [], None
        elif tag == "td" and self.row is not None:
            self.cell = []
            self.row.append(self.cell)

    def handle_endtag(self, tag):
        if tag == "tr" and self.row is not None:
            self.rows.append([" ".join("".join(c).split()) for c in self.row])
            self.row, self.cell = None, None

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)


def imd_rows(html, now_iso):
    """Parse the IMD 7-day table. Any layout surprise returns [] instead of raising."""
    try:
        m = re.search(r"Dated\s*:\s*([A-Za-z]{3})[a-z]*\s+(\d{1,2}),\s*(\d{4})", html)
        dated = datetime.strptime(f"{m.group(2)} {m.group(1)} {m.group(3)}", "%d %b %Y").date()
        parser = _TableRows()
        parser.feed(html)
        rows = []
        for cells in parser.rows:
            c = [x for x in cells if x]
            if len(c) < 4 or not re.fullmatch(r"\d{1,2}-[A-Za-z]{3}", c[0]):
                continue
            d = datetime.strptime(f"{c[0]}-{dated.year}", "%d-%b-%Y").date()
            if d < dated - timedelta(days=60):
                d = d.replace(year=d.year + 1)
            tmin, tmax = float(c[1]), float(c[2])
            if -50 <= tmin <= tmax <= 45:
                rows.append(row(AREA, d.isoformat(), "imd", tmax, tmin, None, None, None, None,
                                c[3].capitalize(), now_iso))
        return rows
    except Exception:
        return []


def fetch_feeds(net, trip, prev, now_iso):
    """Fetch every feed for every place. One failure never stops the others."""
    rows, hourly, extra, errs = [], {}, defaultdict(dict), defaultdict(list)
    elev = dict(prev.get("elevations") or {})
    lms = dict(prev.get("metno_last_modified") or {})
    for p in trip["places"]:
        pid, sun = p["id"], {}
        base = OM_URL.format(lat=p["lat"], lon=p["lon"])
        try:
            new, sun = om_daily_rows(pid, om_get(net, f"om_daily_{pid}.json", base + OM_DAILY, p, elev), now_iso)
            rows += new
        except Exception as e:
            errs["om_daily"].append(f"{pid}: {e}")
        try:
            js = om_get(net, f"om_hourly_{pid}.json", base + OM_HOURLY, p, elev)
            hourly[pid] = {"place": pid, "name": p["name"], "elevation": js.get("elevation"),
                           **{k: js["hourly"].get(k) for k in ["time"] + HOURLY_VARS}, "sun": sun}
        except Exception as e:
            errs["om_hourly"].append(f"{pid}: {e}")
        try:
            extra[pid].update(om_model_hours(
                om_get(net, f"om_hourly_models_{pid}.json", base + OM_HOURLY_MODELS, p, elev)))
        except Exception as e:
            errs["om_hourly"].append(f"{pid} models: {e}")
        try:
            hdr ={"If-Modified-Since": lms[pid]} if lms.get(pid) and not net.record else {}
            url = METNO_URL.format(lat=round(p["lat"], 4), lon=round(p["lon"], 4), alt=p["alt_m"])
            text, lm = net.get(f"metno_{pid}.json", url, hdr)
            if text is not None:
                rows += metno_rows(pid, json.loads(text), now_iso)
                extra[pid]["metno"] = metno_hours(json.loads(text))
                if lm:
                    lms[pid] = lm
        except Exception as e:
            errs["metno"].append(f"{pid}: {e}")
    try:
        new = imd_rows(net.get("imd.html", IMD_URL)[0], now_iso)
        rows += new
        if not new:
            errs["imd"].append("page layout not recognised, skipped")
    except Exception as e:
        errs["imd"].append(str(e))

    def state(fid, key):
        e = errs.get(key)
        old = (prev.get("feeds") or {}).get(fid) or {}
        return {"ok": not e, "fetched_at": old.get("fetched_at") if e else now_iso,
                "error": "; ".join(e)[:300] if e else None}
    status = {fid: state(fid, "om_daily") for fid in OM_MODELS}
    status.update({k: state(k, k) for k in ("om_hourly", "metno", "imd")})
    return {"rows": rows, "hourly": hourly, "hourly_sources": extra, "status": status, "elevations": elev,
            "metno_last_modified": lms}


# ---------- merge and compute ----------

def merge(stored, new, today):
    """Past days are frozen (Open-Meteo may correct its own); from today on, the newest reading wins."""
    out = {(r["place"], r["date"], r["feed"]): r for r in stored}
    for r in new:
        key = (r["place"], r["date"], r["feed"])
        old = out.get(key)
        if old:
            if r["date"] < today and not r["feed"].startswith("om_"):
                continue
            if r["fetched_at"] < old["fetched_at"]:
                continue
            if r["feed"] == "metno" and r["date"] == today:
                # today's forecast only covers the hours left, so keep the wider range seen so far
                r = {**r, "tmax": max(x for x in (r["tmax"], old["tmax"]) if x is not None),
                     "tmin": min(x for x in (r["tmin"], old["tmin"]) if x is not None)}
            if all(old.get(k) == r.get(k) for k in VALUE_KEYS):
                continue  # unchanged: keep the time it was first seen
        out[key] = r
    return sorted(out.values(), key=lambda r: (r["date"], r["place"], r["feed"]))


def shows_snow(r):
    return bool((r.get("snow_cm") or 0) > 0 or re.search(r"snow|flurr|sleet", r.get("sky") or "", re.I)
                or ((r.get("precip_mm") or 0) > 0 and r.get("tmax") is not None and r["tmax"] <= 2))


def compute(trip, rows, notes, today):
    places = {p["id"]: p for p in trip["places"]}
    manual_ok = trip.get("manual_in_median", True)
    days = trip["days"]
    start, end = days[0]["date"], days[-1]["date"]
    by = defaultdict(list)
    for r in rows:
        by[(r["place"], r["date"])].append(r)
    snow_notes = [n for n in notes if n["kind"] in ("observed", "forecast")]
    first = min([r["date"] for r in rows] + [n["date"] for n in snow_notes] + [shift(start, -7)])
    dates = [shift(first, i) for i in range((pdate(end) - pdate(first)).days + 1)]

    def applicable(pid, d):
        return by.get((pid, d), []) + (by.get((AREA, d), []) if places[pid]["area"] == "spiti" else [])

    def headline(pid, d):
        rs = [r for r in applicable(pid, d) if manual_ok or r["feed"] not in MANUAL.values()]
        his = [r["tmax"] for r in rs if r["tmax"] is not None]
        los = [r["tmin"] for r in rs if r["tmin"] is not None]
        n = sum(1 for r in rs if r["tmax"] is not None or r["tmin"] is not None)
        if not n:
            return None
        sky = next((r["sky"] for r in rs if r["feed"] == "om_ecmwf" and r["sky"]), None) \
            or next((r["sky"] for r in rs if r["sky"]), None)
        lo, hi = rnd(min(los, default=None)), rnd(max(his, default=None))
        return {"tmax": rnd(median(his)), "tmin": rnd(median(los)), "range_lo": lo, "range_hi": hi,
                "n_feeds": n, "based_on": f"{n} source{'' if n == 1 else 's'}, {deg(lo)} to {deg(hi)}",
                "sky": sky, "raw_tmin": median(los)}

    head, snow = {}, {}
    for pid, p in places.items():
        last = None
        for d in dates:
            town = by.get((pid, d), [])
            area = by.get((AREA, d), []) if p["area"] == "spiti" else []
            amounts = [r["snow_cm"] for r in town if r.get("snow_cm") is not None]
            town_snow = [a for a in amounts if a >= 0.2]
            area_snow = [r for r in area if shows_snow(r)]
            reported = any(n["date"] <= d <= n["date_to"] and
                           (pid in n["places"] if n["places"] else p["area"] in ("spiti", "kinnaur"))
                           for n in snow_notes)
            signal = bool(any(a >= 1.0 for a in amounts) or len(town_snow) >= 2
                          or len(area_snow) >= 2 or reported)
            if signal:
                last = d
            since = (pdate(d) - pdate(last)).days if last else None
            h = head[(pid, d)] = headline(pid, d)
            if since is not None and since <= 3:
                ice = "High"
                why = "snow that day" if since == 0 else f"snow {since} day{'' if since == 1 else 's'} earlier"
            elif not h or h["raw_tmin"] is None:
                ice, why = "Unknown", "no temperature data"
            elif h["raw_tmin"] < 0:
                ice, why = "Moderate", "nights below freezing"
            else:
                ice, why = "Low", "nights above freezing"
            cm = max(amounts + [r["snow_cm"] for r in area if r.get("snow_cm") is not None], default=None)
            snow[(pid, d)] = {"place": pid, "date": d, "snow_signal": signal,
                              "snow_feeds": len(town_snow) + len(area_snow), "n_feeds": len(town) + len(area),
                              "snow_cm": cm, "reported": reported, "ice": ice, "ice_reason": why,
                              "days_since_snow": since}

    spiti_days = trip.get("spiti_days", [])
    out_days, compare = [], []
    for dy in days:
        d, stay = dy["date"], places[dy["stay"]]
        h = head.get((stay["id"], d))
        leg = [snow[(pid, d)] for pid in dy["leg"]]
        worst = max(leg, key=lambda s: ICE_RANK[s["ice"]])
        out_days.append({
            "day": dy["day"], "date": d, "route": dy["route"], "plan": dy["plan"], "leg": dy["leg"],
            "spiti": dy["day"] in spiti_days,
            "stay": {"id": stay["id"], "name": stay["name"],
                     "alt_m": None if stay["id"] == "home" else stay["alt_m"]},
            "has_data": bool(h), **{k: (h or {}).get(k) for k in
                                    ("tmax", "tmin", "sky", "n_feeds", "based_on", "range_lo", "range_hi")},
            "snow_places": [places[s["place"]]["name"] for s in leg if s["snow_signal"]],
            "ice": worst["ice"], "ice_reason": f"{worst['ice_reason']} ({places[worst['place']]['name']})",
            "days_since_snow": min((s["days_since_snow"] for s in leg if s["days_since_snow"] is not None),
                                   default=None)})
        compare.append({"day": dy["day"], "date": d, "place": stay["name"],
                        "median": [h["tmax"], h["tmin"]] if h else None,
                        "values": {r["feed"]: [r["tmax"], r["tmin"], r["sky"]] for r in applicable(stay["id"], d)}})

    # summary sentence parts and the three headline facts
    covered = [x for x in out_days if x["has_data"]]
    snow_dates = [x["date"] for x in out_days if x["snow_places"]]
    spiti_first = next((x["date"] for x in out_days if x["spiti"]), start)
    bound = max(today, shift(spiti_first, -1))
    last_snow = max((d for (pid, d), s in snow.items()
                     if places[pid]["area"] == "spiti" and s["snow_signal"] and d <= bound), default=None)
    freeze = next((x["stay"]["name"] for x in covered if x["tmin"] is not None and x["tmin"] < 0), None)
    cold = min((x for x in covered if x["tmin"] is not None), key=lambda x: x["tmin"], default=None)
    parts = []
    if snow_dates:
        parts.append(f"Snow is signalled on {', '.join(short(d) for d in snow_dates)} of the trip.")
    elif covered:
        parts.append("Dry on every trip date so far.")
    else:
        parts.append("The trip dates are not in forecast range yet.")
    if last_snow and last_snow < spiti_first:
        n = (pdate(spiti_first) - pdate(last_snow)).days
        verb = "was" if last_snow <= today else "is forecast for"
        parts.append(f"The last snow {verb} {short(last_snow)}, {n} day{'' if n == 1 else 's'} "
                     "before you reach Nako and Spiti.")
    elif last_snow:
        parts.append(f"The last snow in Spiti was {short(last_snow)}.")
    else:
        parts.append("No snow has been seen in the run-up so far.")
    if freeze:
        parts.append(f"Nights freeze from {freeze} onward, so expect black ice in the shade each morning.")
    elif covered:
        parts.append("Nights stay above freezing at every stop so far.")
    outlook = {
        "title": trip.get("title"), "trip_start": start, "trip_end": end,
        "places": [{"id": p["id"], "name": p["name"], "alt_m": None if p["id"] == "home" else p["alt_m"],
                    "area": p["area"]} for p in trip["places"]],
        "days": out_days, "hourly_sources": HOURLY_SOURCES,
        "summary": {"parts": parts, "snow_dates": snow_dates, "freeze_from": freeze},
        "facts": {"last_snow": last_snow,
                  "coldest": {"tmin": cold["tmin"], "place": cold["stay"]["name"], "date": cold["date"]}
                  if cold else None}}
    run_up = shift(start, -7)
    used = {f for c in compare for f in c["values"]}
    return {"outlook": outlook,
            "snow": [s for (pid, d), s in sorted(snow.items(), key=lambda kv: (kv[0][1], kv[0][0])) if d >= run_up],
            "compare": {"feeds": [{"id": f, "name": n} for f, n in FEED_NAMES.items() if f in used],
                        "days": compare}}


def sources_list(status, docs, cfg):
    out = [{"name": name, "how": "automatic", "last_read": status[fid]["fetched_at"],
            "status": "ok" if status[fid]["ok"] else "error", "detail": status[fid]["error"]}
           for name, fid in (("Open-Meteo, 3 models", "om_ecmwf"), ("MET Norway (yr.no)", "metno"),
                             ("IMD Spiti", "imd"))]
    latest = max(docs, key=lambda d: d["read_at"], default=None)
    for c in cfg:
        last = max((d["read_at"] for d in docs if any(r["source"] == c["name"] for r in d["rows"])),
                   default=None)
        failed = bool(latest and c["name"] in (latest.get("failed") or []))
        out.append({"name": c["name"], "how": "import", "last_read": last,
                    "status": "failed in last import" if failed else "ok" if last else "not imported yet",
                    "detail": f"{c['point']}. {c['note']}"})
    return out


# ---------- main ----------

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--offline", metavar="DIR", help="read saved responses from DIR instead of the network")
    ap.add_argument("--record", metavar="DIR", help="also save each live response into DIR")
    ap.add_argument("--out", default=str(ROOT / "site" / "data"), help="output folder (default site/data)")
    ap.add_argument("--manual", default=str(ROOT / "data" / "manual"), help="manual input folder")
    ap.add_argument("--now", help="pretend it is this UTC time (ISO 8601)")
    a = ap.parse_args(argv)
    out = Path(a.out)

    stamp = a.now
    if not stamp and a.offline and (Path(a.offline) / "recorded_at.txt").exists():
        stamp = (Path(a.offline) / "recorded_at.txt").read_text(encoding="utf-8").strip()
    now = datetime.fromisoformat(stamp.replace("Z", "+00:00")) if stamp else datetime.now(timezone.utc)
    now_iso = now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    today = now.astimezone(IST).date().isoformat()
    if a.record:
        Path(a.record).mkdir(parents=True, exist_ok=True)
        (Path(a.record) / "recorded_at.txt").write_text(now_iso + "\n", encoding="utf-8")

    trip = load_json(ROOT / "config" / "trip.json")
    schema = load_json(ROOT / "site" / "schema.json")
    site = load_json(ROOT / "config" / "site.json", {}) or {}
    repo = os.environ.get("GITHUB_REPOSITORY") or f"{site.get('owner', '')}/{site.get('repo', '')}"
    owner, _, name = repo.partition("/")
    net = Net(a.offline, a.record, f"spiti-trip-dashboard/1.0 https://github.com/{repo}")

    prev = load_json(out / "meta.json", {}) or {}
    stored = load_json(out / "daily.json", []) or []
    # where an hourly file has no MET Norway series yet, ask for a full reply rather than "not modified"
    for p in trip["places"]:
        old = load_json(out / "hourly" / f"{p['id']}.json", {}) or {}
        if "metno" not in (old.get("sources") or {}):
            (prev.get("metno_last_modified") or {}).pop(p["id"], None)
    invalid = []
    src_docs, note_docs = load_manual(a.manual, schema, invalid)
    f = fetch_feeds(net, trip, prev, now_iso)
    rows = merge(stored, f["rows"] + manual_rows(src_docs), today)
    reports = merge_notes(note_docs)
    c = compute(trip, rows, reports, today)

    changed = [n for n, obj in (("daily", rows), ("outlook", c["outlook"]), ("snow", c["snow"]),
                                ("reports", reports), ("compare", c["compare"]),
                                ("sources", sources_list(f["status"], src_docs, load_json(ROOT / "config" / "sources.json", []))))
               if write_json(out / f"{n}.json", obj)]
    for pid, doc in f["hourly"].items():
        path = out / "hourly" / f"{pid}.json"
        old = load_json(path, {}) or {}
        if not doc["sun"]:
            doc["sun"] = old.get("sun", {})
        # a source that could not be fetched this time (or answered "not modified") keeps its last series
        doc["sources"] = {**(old.get("sources") or {}), **f["hourly_sources"].get(pid, {})}
        if write_json(path, doc, compact=True):
            changed.append(f"hourly/{pid}")
    write_json(out / "meta.json", {
        "built_at": now_iso, "repo": {"owner": owner, "repo": name, "branch": site.get("branch", "main")},
        "feeds": f["status"],
        "manual_read_at": max((d["read_at"] for d in src_docs), default=None),
        "notes_written_at": max((d["written_at"] for d in note_docs), default=None),
        "first_date": min((r["date"] for r in rows), default=None),
        "last_date": max((r["date"] for r in rows), default=None),
        "invalid_files": invalid, "elevations": f["elevations"],
        "metno_last_modified": f["metno_last_modified"]})

    # the page fetches the prompts from the site; the service worker cache is versioned per deploy
    (out.parent / "prompts").mkdir(parents=True, exist_ok=True)
    for p in (ROOT / "prompts").glob("*.md"):
        shutil.copyfile(p, out.parent / "prompts" / p.name)
    sw = out.parent / "sw.js"
    if os.environ.get("GITHUB_ACTIONS") and sw.exists():
        text = sw.read_text(encoding="utf-8")
        sw.write_text(re.sub(r'const VERSION = "[^"]*"', f'const VERSION = "{now_iso}"', text),
                      encoding="utf-8", newline="\n")

    bad = [k for k, s in f["status"].items() if not s["ok"]]
    print(f"built {now_iso}: {len(rows)} daily rows, changed: {', '.join(changed) or 'nothing'}")
    for k in bad:
        print(f"  feed {k} failed: {f['status'][k]['error']}")
    for x in invalid:
        print(f"  skipped {x['file']}: {'; '.join(x['errors'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
