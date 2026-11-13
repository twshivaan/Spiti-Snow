# Spiti-Snow

A weather dashboard for one road trip: Delhi NCR to Spiti valley and back, 21–28 Nov 2026. A GitHub Actions job runs every 3 hours, fetches free forecast feeds, merges them with files you add by hand, and publishes a static page on GitHub Pages. No server, no keys, no cost.

## Setup (once)

1. Create a free GitHub account and a new **public** repository.
2. Upload everything in this folder ("Add file → Upload files", drag the contents in) and commit.
3. Settings → Pages → Source: **GitHub Actions**.
4. Settings → Actions → General → Workflow permissions: **Read and write permissions**.
5. Actions → **Update data** → **Run workflow**. Wait for the green tick.
6. Open `https://<username>.github.io/<repo>/`.

## Using it

- **Import your five sources.** On the page, press "Import my 5 sources", copy the prompt, run it in Claude in Chrome, paste the reply back, and press "Save to my GitHub". GitHub opens with the file filled in; press **Commit changes**. The page updates a few minutes later. The prompt asks every site for every place in `config/trip.json`, from today to the last trip day; each row is used for its own town. Pages it finds are remembered and written into the next prompt (seed pages live in `config/sources.json`).
- **Add Claude notes.** Same steps with "Add Claude notes", in any Claude chat that can search the web.
- **Change the itinerary.** Edit `config/trip.json` (places, dates, each day's `leg` and `stay`) and commit.
- **Stop it after the trip.** Actions → Update data → "…" → **Disable workflow**.

## Good to know

- GitHub may start scheduled runs several minutes late, and pauses schedules in repositories with no activity for 60 days.
- Past days are never deleted, so snow that fell before the trip stays on the record.
- The page works offline after one visit and says when it is showing saved data.
- Feeds: Open-Meteo (ECMWF, GFS, ICON), MET Norway, and the IMD Spiti page. AccuWeather, The Weather Network, timeanddate and yr.no arrive only through your import. Older imports without a `place` on each row still count, for the Spiti towns only.

## For developers

```
python scripts/build.py                          # live build into site/data
python scripts/build.py --offline tests/fixtures # no network
python -m unittest scripts/test_build.py
cd site && python -m http.server                 # view at http://localhost:8000
```

Python 3 standard library only; plain HTML, CSS and JavaScript; no build step.
