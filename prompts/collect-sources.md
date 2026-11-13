Collect daily weather forecasts for my road trip from five websites. Do it for EVERY place below, and for every date from today up to {{END}}.

Places (id: what to search for, position, height):
{{PLACES}}

Websites, which view to read, and the pages already found for some places:
{{SITES}}

How to work:
- Go site by site, then place by place. If a page is listed for the place, open it. Otherwise type the search text into the site's own search box and pick the match in that state of India. Then switch to the daily view named above.
- If a site has no page for a place, use its nearest location within about 15 km and 300 m of height. If there is none, skip that place on that site and list it in "missing".
- One page may serve several places (IMD's Spiti page covers Nako, Tabo, Kaza and Komic). Repeat its rows under each of those places.
- Read every date the page shows from today up to {{END}}. Many pages stop earlier, and that is fine.
- List every page you read in "pages", so next time the page can be opened directly.

Reply with ONE JSON object and nothing else, in exactly this shape:
{"schema":"spiti-sources/1","read_at":"<now, UTC, ISO 8601>","reader":"claude-in-chrome","failed":[],
 "missing":[{"source":"IMD","place":"home"}],
 "pages":[{"source":"AccuWeather","place":"kaza","url":"https://..."}],
 "rows":[{"source":"AccuWeather","place":"kaza","date":"YYYY-MM-DD","tmax":0,"tmin":0,"sky":"","precip_pct":0,"precip_mm":0,"snow_cm_min":0,"snow_cm_max":0}]}

Rules:
- "source" is exactly one of: AccuWeather, IMD, The Weather Network, timeanddate, yr.no.
- "place" is exactly one of the place ids above.
- One row per source per place per date. Temperatures in °C as numbers. Convert °F if a page shows it.
- "sky" is the page's condition in at most six words, keeping words like snow, flurries, rain.
- Leave out any field the page does not show. Never estimate or fill gaps.
- Snow amounts in cm: "1-3 cm" gives snow_cm_min 1 and snow_cm_max 3.
- If a whole site will not load, add its name to "failed" and give it no rows.
- Do not click anything except what is needed to search and see the daily forecast. Do not accept cookies beyond the essential ones.
