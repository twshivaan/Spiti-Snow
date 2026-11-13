Open each of these five pages in turn and read the daily forecast for every date shown, from today up to 28 Nov 2026:
1. AccuWeather: https://www.accuweather.com/en/in/dhar-spiti-sarchu/3017155/daily-weather-forecast/3017155
2. IMD: https://city.imd.gov.in/citywx/city_weather_test_try_warnings.php?id=88815
3. The Weather Network: https://www.theweathernetwork.com/en/city/in/himachal-pradesh/spiti/14-days
4. timeanddate: https://www.timeanddate.com/weather/@1265292/ext
5. yr.no: https://www.yr.no/en/forecast/daily-table/2-1255660/India/Himachal%20Pradesh/Spiti

Reply with ONE JSON object and nothing else, in exactly this shape:
{"schema":"spiti-sources/1","read_at":"<now, UTC, ISO 8601>","reader":"claude-in-chrome","failed":[],
 "rows":[{"source":"AccuWeather","date":"YYYY-MM-DD","tmax":0,"tmin":0,"sky":"","precip_pct":null,"precip_mm":null,"snow_cm_min":null,"snow_cm_max":null}]}

Rules:
- "source" is exactly one of: AccuWeather, IMD, The Weather Network, timeanddate, yr.no.
- One row per source per date. Temperatures in °C as numbers. Convert °F if a page shows it.
- "sky" is the page's condition in at most six words, keeping words like snow, flurries, rain.
- Use null for anything the page does not show. Never estimate or fill gaps.
- Snow amounts in cm: "1-3 cm" gives snow_cm_min 1 and snow_cm_max 3.
- If a page will not load, add its source name to "failed" and give it no rows.
- Do not click anything except what is needed to see the daily forecast. Do not accept cookies beyond the essential ones.
