"""Offline tests: python -m unittest scripts/test_build.py"""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build  # noqa: E402

ROOT = build.ROOT
FIXTURES = ROOT / "tests" / "fixtures"
TRIP = build.load_json(ROOT / "config" / "trip.json")
SCHEMA = build.load_json(ROOT / "site" / "schema.json")
TODAY = "2026-11-13"


def r(place, day, feed, tmax=None, tmin=None, snow=None, precip=None, sky=None, at="2026-11-13T00:00:00Z"):
    return build.row(place, day, feed, tmax, tmin, snow, precip, None, None, sky, at)


def note(kind, d, d_to=None, places=()):
    return {"kind": kind, "date": d, "date_to": d_to or d, "places": list(places)}


def snow_of(out, place, day):
    return next(s for s in out["snow"] if s["place"] == place and s["date"] == day)


def day_of(out, n):
    return out["outlook"]["days"][n]


class MedianAndRange(unittest.TestCase):
    def test_median(self):
        self.assertEqual(build.median([3, None, 1, 2]), 2)
        self.assertEqual(build.median([1, 2, 3, 10]), 2.5)
        self.assertIsNone(build.median([None]))

    def test_headline_uses_median_and_full_range(self):
        rows = [r("kaza", "2026-11-25", "om_ecmwf", 6, -8, sky="Clear"), r("kaza", "2026-11-25", "om_gfs", 4, -6),
                r("spiti_area", "2026-11-25", "accuweather", 3, -20), r("spiti_area", "2026-11-25", "timeanddate", 16, 3),
                r("spiti_area", "2026-11-25", "twn", 3, -7)]
        d = day_of(build.compute(TRIP, rows, [], TODAY), 4)
        self.assertEqual((d["tmax"], d["tmin"]), (4, -7))
        self.assertEqual((d["range_lo"], d["range_hi"], d["n_feeds"]), (-20, 16, 5))
        self.assertEqual(d["based_on"], "5 sources, −20° to 16°")
        self.assertEqual(d["sky"], "Clear")

    def test_manual_sources_can_be_left_out_of_the_median(self):
        rows = [r("kaza", "2026-11-25", "om_ecmwf", 6, -8), r("spiti_area", "2026-11-25", "timeanddate", 16, 3)]
        d = day_of(build.compute({**TRIP, "manual_in_median": False}, rows, [], TODAY), 4)
        self.assertEqual((d["tmax"], d["n_feeds"]), (6, 1))

    def test_area_sources_do_not_apply_outside_spiti(self):
        rows = [r("kalpa", "2026-11-23", "om_ecmwf", 10, 1), r("spiti_area", "2026-11-23", "accuweather", 3, -20)]
        self.assertEqual(day_of(build.compute(TRIP, rows, [], TODAY), 2)["n_feeds"], 1)


class SnowSignal(unittest.TestCase):
    def test_rule1_town_feeds(self):
        rows = [r("kalpa", "2026-11-15", "om_ecmwf", 2, -5, snow=1.0),
                r("kalpa", "2026-11-16", "om_ecmwf", 2, -5, snow=0.3), r("kalpa", "2026-11-16", "om_gfs", 2, -5, snow=0.2),
                r("kalpa", "2026-11-17", "om_ecmwf", 2, -5, snow=0.9)]
        out = build.compute(TRIP, rows, [], TODAY)
        self.assertTrue(snow_of(out, "kalpa", "2026-11-15")["snow_signal"])
        self.assertTrue(snow_of(out, "kalpa", "2026-11-16")["snow_signal"])
        self.assertEqual(snow_of(out, "kalpa", "2026-11-16")["snow_feeds"], 2)
        self.assertFalse(snow_of(out, "kalpa", "2026-11-17")["snow_signal"])

    def test_rule2_two_area_sources(self):
        rows = [r("spiti_area", "2026-11-15", "twn", -3, -15, sky="Morning flurries"),
                r("spiti_area", "2026-11-15", "yrno", -8, -22, precip=1.8),
                r("spiti_area", "2026-11-15", "timeanddate", 8, -1, precip=17.1, sky="Rain, overcast"),
                r("spiti_area", "2026-11-16", "accuweather", -5, -19, snow=2)]
        out = build.compute(TRIP, rows, [], TODAY)
        s = snow_of(out, "kaza", "2026-11-15")
        self.assertTrue(s["snow_signal"])
        self.assertEqual((s["snow_feeds"], s["n_feeds"]), (2, 3))
        self.assertFalse(snow_of(out, "kaza", "2026-11-16")["snow_signal"])  # one source is not enough
        self.assertFalse(snow_of(out, "kalpa", "2026-11-15")["snow_signal"])  # not a spiti place

    def test_rule3_notes(self):
        notes = [note("observed", "2026-11-14", "2026-11-15"), note("forecast", "2026-11-17", places=["shimla"]),
                 note("dry_forecast", "2026-11-18")]
        out = build.compute(TRIP, [], notes, TODAY)
        for place in ("kaza", "kalpa"):
            self.assertTrue(snow_of(out, place, "2026-11-15")["reported"])
        self.assertFalse(snow_of(out, "shimla", "2026-11-15")["snow_signal"])
        self.assertTrue(snow_of(out, "shimla", "2026-11-17")["snow_signal"])
        self.assertFalse(snow_of(out, "kaza", "2026-11-17")["snow_signal"])
        self.assertFalse(snow_of(out, "kaza", "2026-11-18")["snow_signal"])


class IceRating(unittest.TestCase):
    def test_three_day_window_then_temperature(self):
        rows = [r("kalpa", "2026-11-15", "om_ecmwf", 2, -5, snow=3)]
        rows += [r("kalpa", f"2026-11-{d}", "om_ecmwf", 5, t) for d, t in ((16, -4), (17, -4), (18, -4), (19, -4), (20, 2))]
        out = build.compute(TRIP, rows, [], TODAY)
        got = {d: snow_of(out, "kalpa", f"2026-11-{d}") for d in range(15, 22)}
        self.assertEqual([got[d]["ice"] for d in range(15, 22)],
                         ["High", "High", "High", "High", "Moderate", "Low", "Unknown"])
        self.assertEqual(got[18]["days_since_snow"], 3)
        self.assertEqual(got[18]["ice_reason"], "snow 3 days earlier")
        self.assertEqual(got[19]["ice_reason"], "nights below freezing")

    def test_day_takes_the_worst_place_on_the_leg(self):
        # day 3 drives kalpa -> nako -> tabo; only nako has snow, two days before
        rows = [r("nako", "2026-11-22", "om_ecmwf", 0, -9, snow=4), r("nako", "2026-11-24", "om_ecmwf", 1, -9),
                r("kalpa", "2026-11-24", "om_ecmwf", 12, 3), r("tabo", "2026-11-24", "om_ecmwf", 6, -7)]
        d = day_of(build.compute(TRIP, rows, [], TODAY), 3)
        self.assertEqual((d["ice"], d["days_since_snow"]), ("High", 2))
        self.assertIn("Nako", d["ice_reason"])


class FrozenPast(unittest.TestCase):
    def test_past_rows_are_kept_and_future_rows_updated(self):
        stored = [r("kaza", "2026-11-12", "metno", 1, -9), r("kaza", "2026-11-12", "om_gfs", 1, -9),
                  r("kaza", "2026-11-14", "metno", 1, -9), r("kaza", "2026-11-10", "metno", 0, -8)]
        new = [r("kaza", "2026-11-12", "metno", 5, -5, at="2026-11-13T06:00:00Z"),
               r("kaza", "2026-11-12", "om_gfs", 2, -10, at="2026-11-13T06:00:00Z"),
               r("kaza", "2026-11-14", "metno", 3, -7, at="2026-11-13T06:00:00Z"),
               r("kaza", "2026-11-11", "metno", 0, -6, at="2026-11-13T06:00:00Z")]
        got = {(x["date"], x["feed"]): x["tmax"] for x in build.merge(stored, new, TODAY)}
        self.assertEqual(got[("2026-11-12", "metno")], 1)   # frozen
        self.assertEqual(got[("2026-11-12", "om_gfs")], 2)  # Open-Meteo may correct its own past
        self.assertEqual(got[("2026-11-14", "metno")], 3)   # newest wins from today on
        self.assertEqual(got[("2026-11-10", "metno")], 0)   # never deleted
        self.assertEqual(got[("2026-11-11", "metno")], 0)   # a past day seen for the first time is added

    def test_unchanged_reading_keeps_its_first_time(self):
        stored = [r("kaza", "2026-11-14", "metno", 1, -9)]
        got = build.merge(stored, [r("kaza", "2026-11-14", "metno", 1, -9, at="2026-11-13T06:00:00Z")], TODAY)
        self.assertEqual(got[0]["fetched_at"], "2026-11-13T00:00:00Z")


class ManualFiles(unittest.TestCase):
    def test_seed_files_are_valid(self):
        invalid = []
        src, notes = build.load_manual(ROOT / "data" / "manual", SCHEMA, invalid)
        self.assertEqual(invalid, [])
        self.assertTrue(src and notes)

    def test_invalid_files_are_skipped_and_listed(self):
        good = {"schema": "spiti-sources/1", "read_at": "2026-11-13T09:30:00Z", "failed": [],
                "rows": [{"source": "AccuWeather", "date": "2026-11-24", "tmax": 4, "tmin": -21}]}
        bad = {"a-tmin-above-tmax": {**good, "rows": [{"source": "AccuWeather", "date": "2026-11-24", "tmax": -5, "tmin": 2}]},
               "b-too-hot": {**good, "rows": [{"source": "IMD", "date": "2026-11-24", "tmax": 60, "tmin": 2}]},
               "c-bad-source": {**good, "rows": [{"source": "BBC", "date": "2026-11-24", "tmax": 4, "tmin": 2}]},
               "d-bad-date": {**good, "rows": [{"source": "IMD", "date": "2027-01-02", "tmax": 4, "tmin": 2}]},
               "e-wrong-folder": {"schema": "spiti-notes/1", "written_at": "2026-11-13T11:30:00Z", "items": []}}
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "sources"
            folder.mkdir()
            (Path(tmp) / "notes").mkdir()
            (folder / "0-good.json").write_text(json.dumps(good), encoding="utf-8")
            (folder / "f-broken.json").write_text("{not json", encoding="utf-8")
            for name, doc in bad.items():
                (folder / f"{name}.json").write_text(json.dumps(doc), encoding="utf-8")
            invalid = []
            src, _ = build.load_manual(tmp, SCHEMA, invalid)
        self.assertEqual(len(src), 1)
        self.assertEqual(len(invalid), 6)

    def test_long_summary_is_rejected(self):
        doc = {"schema": "spiti-notes/1", "written_at": "2026-11-13T11:30:00Z",
               "items": [{"kind": "road", "date": "2026-11-13", "summary": "x" * 241, "places": []}]}
        self.assertTrue(build.validate(doc, SCHEMA))
        doc["items"][0]["summary"] = "x" * 240
        self.assertEqual(build.validate(doc, SCHEMA), [])


class Feeds(unittest.TestCase):
    def test_imd_table_is_parsed(self):
        rows = build.imd_rows((FIXTURES / "imd.html").read_text(encoding="utf-8"), "2026-11-13T00:00:00Z")
        self.assertGreaterEqual(len(rows), 5)
        self.assertTrue(all(x["place"] == "spiti_area" and x["date"].startswith("2026-") for x in rows))

    def test_imd_parse_failure_is_tolerated(self):
        for html in ("", "<html><table><tr><td>nothing here</td></tr></table>", "Dated :Nov 13, 2026 <tr><td>13-Nov<td>x<td>y<td>z"):
            self.assertEqual(build.imd_rows(html, "2026-11-13T00:00:00Z"), [])


class OfflineBuild(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        fixtures = cls.tmp / "fixtures"
        shutil.copytree(FIXTURES, fixtures)
        (fixtures / "imd.html").write_text("<html>layout changed</html>", encoding="utf-8")  # broken feed
        (fixtures / "metno_kaza.json").unlink()                                              # missing feed
        cls.out = cls.tmp / "site" / "data"
        cls.code = build.main(["--offline", str(fixtures), "--out", str(cls.out)])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def load(self, name):
        return json.loads((self.out / name).read_text(encoding="utf-8"))

    def test_every_file_is_written(self):
        self.assertEqual(self.code, 0)
        names = ["meta", "daily", "outlook", "snow", "reports", "sources", "compare"]
        names += [f"hourly/{p['id']}" for p in TRIP["places"]]
        for n in names:
            self.assertTrue((self.out / f"{n}.json").exists(), n)

    def test_hourly_files_carry_every_source(self):
        tabo, kaza = self.load("hourly/tabo.json"), self.load("hourly/kaza.json")
        self.assertEqual(set(tabo["sources"]), {"om_ecmwf", "om_gfs", "om_icon", "metno"})
        self.assertNotIn("metno", kaza["sources"])  # its fixture was removed above
        for src in tabo["sources"].values():
            self.assertEqual(len(src["time"]), len(src["temperature_2m"]))
            self.assertIsNotNone(src["temperature_2m"][-1])  # cut off where the forecast ends
        self.assertLess(len(tabo["sources"]["om_icon"]["time"]), len(tabo["time"]))
        ids = [s["id"] for s in self.load("outlook.json")["hourly_sources"]]
        self.assertEqual(ids, ["best", "om_ecmwf", "om_gfs", "om_icon", "metno"])

    def test_compare_has_sky_for_single_source_view(self):
        day = self.load("compare.json")["days"][4]
        self.assertEqual(len(day["values"]["om_ecmwf"]), 3)
        self.assertIsInstance(day["values"]["om_ecmwf"][2], str)

    def test_failed_feeds_are_recorded_not_fatal(self):
        feeds = self.load("meta.json")["feeds"]
        self.assertFalse(feeds["imd"]["ok"])
        self.assertFalse(feeds["metno"]["ok"])
        self.assertTrue(feeds["om_ecmwf"]["ok"])

    def test_seed_acceptance(self):
        snow = {(s["place"], s["date"]): s for s in self.load("snow.json")}
        for place in ("nako", "tabo", "kaza", "komic"):
            self.assertTrue(snow[(place, "2026-11-15")]["snow_signal"], place)
            for d in ("2026-11-16", "2026-11-17", "2026-11-18"):
                self.assertEqual(snow[(place, d)]["ice"], "High", (place, d))
        for d in self.load("outlook.json")["days"]:
            if d["spiti"]:
                self.assertIn(d["ice"], ("Moderate", "High"), d["date"])

    def test_second_run_changes_nothing_but_meta(self):
        before = {p.name: p.read_text(encoding="utf-8") for p in self.out.rglob("*.json") if p.name != "meta.json"}
        build.main(["--offline", str(self.tmp / "fixtures"), "--out", str(self.out)])
        after = {p.name: p.read_text(encoding="utf-8") for p in self.out.rglob("*.json") if p.name != "meta.json"}
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
